"""Per-symbol 数据管道状态 / 历史 / 重试 API。

三个端点均以 `/api/stocks/{symbol}/pipeline*` 命名，供前端"价格走势 & 预测区间"
卡片内的诊断栏与 Drawer 消费。
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy import func

from ..core.db import SessionLocal
from ..core.models import (
    Forecast,
    PipelineRun,
    PriceDaily,
    Report,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["pipeline-status"])


_KNOWN_RUN_TYPES = ("daily_pipeline", "fetch_daily", "compute_signal", "predict", "full_report")


def _summarise_run(row: PipelineRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "run_type": row.run_type,
        "status": row.status,
        "run_at": row.run_at.isoformat() if row.run_at else None,
        "duration_ms": row.duration_ms,
        "message": row.message,
        "error_message": row.error_message,
        "trigger": row.trigger,
    }


@router.get("/{symbol}/pipeline-status")
async def pipeline_status(symbol: str) -> dict[str, Any]:
    """汇总一只股票最近一次各 run_type 的执行摘要 + 预测/行情新鲜度。

    防御策略：任一子查询失败（表缺失、权限异常等）都降级为 None 并记录警告，
    确保前端状态条始终有可用数据结构，不会因单点故障返回 500。
    """
    sym = symbol.upper()
    latest_by_type: dict[str, dict[str, Any]] = {}
    latest_price = None
    latest_forecast_run = None
    latest_report_updated = None
    degraded: list[str] = []

    with SessionLocal() as session:
        # pipeline_runs 查询（若表不存在则降级为空）
        try:
            for run_type in _KNOWN_RUN_TYPES:
                row = session.execute(
                    select(PipelineRun)
                    .where(
                        PipelineRun.symbol == sym,
                        PipelineRun.run_type == run_type,
                    )
                    .order_by(PipelineRun.run_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if row is not None:
                    latest_by_type[run_type] = _summarise_run(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline_runs query failed for %s: %s", sym, exc)
            degraded.append("pipeline_runs")
            try:
                session.rollback()
            except Exception:
                pass

        try:
            latest_price = session.execute(
                select(PriceDaily.trade_date)
                .where(PriceDaily.symbol == sym)
                .order_by(PriceDaily.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001
            logger.warning("prices_daily query failed for %s: %s", sym, exc)
            degraded.append("prices_daily")
            try:
                session.rollback()
            except Exception:
                pass

        try:
            latest_forecast_run = session.execute(
                select(func.max(Forecast.run_at)).where(Forecast.symbol == sym)
            ).scalar()
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecasts query failed for %s: %s", sym, exc)
            degraded.append("forecasts")
            try:
                session.rollback()
            except Exception:
                pass

        try:
            latest_report_updated = session.execute(
                select(Report.created_at)
                .where(Report.symbol == sym, Report.is_latest == True)  # noqa: E712
                .order_by(Report.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001
            logger.warning("reports query failed for %s: %s", sym, exc)
            degraded.append("reports")
            try:
                session.rollback()
            except Exception:
                pass

    # overall status：优先看 daily_pipeline，否则取最新一条
    overall: dict[str, Any] | None = latest_by_type.get("daily_pipeline")
    if overall is None and latest_by_type:
        overall = sorted(
            latest_by_type.values(),
            key=lambda r: r.get("run_at") or "",
            reverse=True,
        )[0]

    return {
        "symbol": sym,
        "overall": overall,
        "latest_by_type": latest_by_type,
        "latest_price_date": latest_price.isoformat() if latest_price else None,
        "latest_forecast_run_at": (
            latest_forecast_run.isoformat() if latest_forecast_run else None
        ),
        "latest_report_updated_at": (
            latest_report_updated.isoformat() if latest_report_updated else None
        ),
        "degraded": degraded,
    }


@router.get("/{symbol}/pipeline-history")
async def pipeline_history(
    symbol: str,
    limit: int = Query(20, ge=1, le=200),
    run_type: str | None = Query(None),
) -> dict[str, Any]:
    """返回该股票最近 N 条 pipeline_runs 记录（含完整错误与日志尾部）。"""
    sym = symbol.upper()
    rows: list[PipelineRun] = []
    degraded = False
    with SessionLocal() as session:
        try:
            stmt = select(PipelineRun).where(PipelineRun.symbol == sym)
            if run_type:
                stmt = stmt.where(PipelineRun.run_type == run_type)
            stmt = stmt.order_by(PipelineRun.run_at.desc()).limit(limit)
            rows = list(session.execute(stmt).scalars().all())
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline_history query failed for %s: %s", sym, exc)
            degraded = True
            try:
                session.rollback()
            except Exception:
                pass

    items = []
    for r in rows:
        item = _summarise_run(r)
        item["log_excerpt"] = r.log_excerpt
        items.append(item)
    return {"symbol": sym, "count": len(items), "items": items, "degraded": degraded}


# 单只股票重试的并发控制与简易任务注册表
_RETRY_LOCK = asyncio.Lock()
_RETRY_JOBS: dict[str, dict[str, Any]] = {}
_RETRY_MIN_INTERVAL_SECONDS = int(os.getenv("PIPELINE_RETRY_MIN_INTERVAL", "30"))


async def _run_single_symbol_pipeline(symbol: str, job_id: str) -> None:
    """异步跑"仅一只股票"版 daily_pipeline。

    实现策略：复用 run_daily_pipeline 的构建块，但只针对传入 symbol。为避免拷贝
    大量代码，这里采用直接内联 fetch_daily + predict_stock_price 的最简路径，
    与 scheduler 的主路径保持 API 一致（写 prices_daily + forecasts + pipeline_runs）。
    """
    from ..data.data_source import fetch_daily
    from ..prediction.forecast import predict_stock_price
    from ..core.trading_calendar import get_next_n_trading_days
    from ..tasks.pipeline_recorder import persist_pipeline_run, TailCollector

    import pandas as pd
    import time as _time

    _started = _time.monotonic()
    _tail = TailCollector().attach()
    _status = "success"
    _message: str | None = None
    _error_message: str | None = None

    try:
        _RETRY_JOBS[job_id] = {
            "symbol": symbol,
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
        }
        start = (datetime.utcnow() - timedelta(days=365 * 3)).strftime("%Y%m%d")
        df = await asyncio.to_thread(fetch_daily, symbol, start)
        inserted = 0
        if df is not None and not df.empty:
            with SessionLocal() as session:
                existing = {
                    r[0]
                    for r in session.execute(
                        text("SELECT trade_date FROM prices_daily WHERE symbol = :sym"),
                        {"sym": symbol},
                    ).fetchall()
                }
                to_insert = []
                for _, row in df.iterrows():
                    if row["trade_date"] in existing:
                        continue
                    to_insert.append(
                        {
                            "symbol": row["symbol"],
                            "trade_date": row["trade_date"],
                            "open": row.get("open"),
                            "high": row.get("high"),
                            "low": row.get("low"),
                            "close": row.get("close"),
                            "pct_chg": row.get("pct_chg"),
                            "vol": int(row["vol"]) if pd.notna(row.get("vol")) else None,
                            "amount": row.get("amount"),
                        }
                    )
                if to_insert:
                    session.execute(
                        text(
                            "INSERT INTO prices_daily (symbol, trade_date, open, high, low, close, pct_chg, vol, amount) "
                            "VALUES (:symbol, :trade_date, :open, :high, :low, :close, :pct_chg, :vol, :amount)"
                        ),
                        to_insert,
                    )
                    session.commit()
                    inserted = len(to_insert)

        # 重新预测
        pred_inserted = 0
        with SessionLocal() as session:
            qdf = pd.read_sql_query(
                "SELECT trade_date, open, high, low, close, pct_chg, vol, amount "
                "FROM prices_daily WHERE symbol = %s ORDER BY trade_date",
                con=session.get_bind(),
                params=(symbol,),
            )
            if len(qdf) >= 50:
                result_pred = await asyncio.to_thread(predict_stock_price, qdf, symbol, 5)
                pred_list = result_pred.get("predictions", []) if result_pred else []
                if pred_list:
                    last_data_date = qdf["trade_date"].iloc[-1]
                    if hasattr(last_data_date, "date") and callable(getattr(last_data_date, "date", None)):
                        last_data_date = last_data_date.date()
                    future_days = get_next_n_trading_days(last_data_date, len(pred_list))
                    run_at = datetime.utcnow()
                    for i, pred in enumerate(pred_list):
                        target_date = future_days[i] if i < len(future_days) else last_data_date + timedelta(days=i + 1)
                        session.execute(
                            text(
                                "INSERT INTO forecasts (symbol, target_date, yhat, yhat_upper, yhat_lower, run_at, model) "
                                "VALUES (:symbol, :target_date, :yhat, :yhat_upper, :yhat_lower, :run_at, :model)"
                            ),
                            {
                                "symbol": symbol,
                                "target_date": target_date,
                                "yhat": float(pred.get("predicted_price", pred.get("yhat"))),
                                "yhat_upper": float(pred.get("upper_bound", pred.get("yhat_upper"))),
                                "yhat_lower": float(pred.get("lower_bound", pred.get("yhat_lower"))),
                                "run_at": run_at,
                                "model": (result_pred.get("method", "retry") or "retry").upper(),
                            },
                        )
                    session.commit()
                    pred_inserted = len(pred_list)

        _message = f"fetched_new={inserted}, forecast_pts={pred_inserted}"
        _RETRY_JOBS[job_id].update(
            {"status": "success", "finished_at": datetime.utcnow().isoformat(), "message": _message}
        )
    except Exception as exc:  # noqa: BLE001
        _status = "failed"
        _error_message = f"{type(exc).__name__}: {exc}"
        logger.warning("manual pipeline retry failed for %s: %s", symbol, exc, exc_info=True)
        _RETRY_JOBS[job_id].update(
            {"status": "failed", "finished_at": datetime.utcnow().isoformat(), "error": _error_message}
        )
    finally:
        try:
            _tail.detach()
        except Exception:
            pass
        persist_pipeline_run(
            symbol=symbol,
            run_type="daily_pipeline",
            status=_status,
            trigger="manual",
            duration_ms=int((_time.monotonic() - _started) * 1000),
            message=_message,
            error_message=_error_message,
            log_excerpt=_tail.excerpt(),
        )


@router.post("/{symbol}/pipeline/retry")
async def pipeline_retry(symbol: str) -> dict[str, Any]:
    """异步触发一次仅针对 `symbol` 的 daily_pipeline 执行。"""
    sym = symbol.upper()

    async with _RETRY_LOCK:
        # 防抖：避免快速多次点击重试
        recent = [
            j for j in _RETRY_JOBS.values()
            if j.get("symbol") == sym and j.get("status") == "running"
        ]
        if recent:
            raise HTTPException(
                status_code=409,
                detail=f"pipeline retry already running for {sym}",
            )

        latest = None
        with SessionLocal() as session:
            try:
                latest = session.execute(
                    select(PipelineRun)
                    .where(
                        PipelineRun.symbol == sym,
                        PipelineRun.run_type == "daily_pipeline",
                        PipelineRun.trigger == "manual",
                    )
                    .order_by(PipelineRun.run_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
            except Exception as exc:  # noqa: BLE001
                logger.warning("pipeline_runs rate-limit query failed for %s: %s", sym, exc)
                try:
                    session.rollback()
                except Exception:
                    pass
        if latest and latest.run_at:
            elapsed = (datetime.utcnow() - latest.run_at).total_seconds()
            if elapsed < _RETRY_MIN_INTERVAL_SECONDS:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"retry too frequent; please wait "
                        f"{int(_RETRY_MIN_INTERVAL_SECONDS - elapsed)}s"
                    ),
                )

        job_id = uuid.uuid4().hex
        _RETRY_JOBS[job_id] = {
            "symbol": sym,
            "status": "queued",
            "queued_at": datetime.utcnow().isoformat(),
        }

    asyncio.create_task(_run_single_symbol_pipeline(sym, job_id))
    return {"symbol": sym, "job_id": job_id, "status": "queued"}


@router.get("/{symbol}/pipeline/retry/{job_id}")
async def pipeline_retry_status(symbol: str, job_id: str) -> dict[str, Any]:
    job = _RETRY_JOBS.get(job_id)
    if not job or job.get("symbol") != symbol.upper():
        raise HTTPException(status_code=404, detail="retry job not found")
    return {"job_id": job_id, **job}


__all__ = ["router"]
