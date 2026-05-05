"""
预测服务（PredictionService）

职责：
1. 记录每次预测结果（写入 prediction_evaluations，predicted 部分）
2. 回填实际价格（actual_price / actual_direction / error_pct / direction_correct）
3. 查询某个 symbol 的预测历史与评估摘要
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from sqlalchemy import select, text, update, and_
from sqlalchemy.orm import Session

from ...core.models import Forecast, PredictionEvaluation, PriceDaily

logger = logging.getLogger(__name__)


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def calculate_direction(value: Optional[float], base: Optional[float], flat_threshold_pct: float = 0.001) -> Optional[str]:
    """按相对变化判断 up/down/flat，输入缺失时返回 None。"""
    if value is None or base is None or base <= 0:
        return None
    change = (value - base) / base
    if abs(change) <= flat_threshold_pct:
        return "flat"
    return "up" if change > 0 else "down"


def classify_deviation_level(
    error_pct: Optional[float],
    direction_correct: Optional[bool] = None,
    interval_hit: Optional[bool] = None,
) -> str:
    """把偏差转为 UI 可读等级，避免前端重复业务阈值。"""
    if error_pct is None:
        return "pending"
    if error_pct >= 15 or (error_pct >= 8 and direction_correct is False and interval_hit is False):
        return "critical"
    if error_pct >= 8 or direction_correct is False or interval_hit is False:
        return "high"
    if error_pct >= 3:
        return "medium"
    return "low"


def _forecast_for_evaluation(pe: PredictionEvaluation, forecast_lookup: Optional[dict]) -> Optional[Forecast]:
    if not forecast_lookup:
        return None
    return (
        forecast_lookup.get((pe.prediction_date, pe.target_date, pe.model_name))
        or forecast_lookup.get((pe.prediction_date, pe.target_date))
    )


def _interval_hit(actual: Optional[float], lower: Optional[float], upper: Optional[float]) -> Optional[bool]:
    if actual is None or lower is None or upper is None:
        return None
    if upper < lower:
        lower, upper = upper, lower
    return lower <= actual <= upper


def build_deviation_cases(
    evaluations: List[PredictionEvaluation],
    forecast_lookup: Optional[dict] = None,
    limit: int = 8,
    horizon_resolver: Optional[Callable[[date, date], int]] = None,
) -> List[dict]:
    """生成偏差复盘列表，按严重程度和日期排序。"""
    cases: List[dict] = []
    for pe in evaluations:
        predicted = _to_float(pe.predicted_price)
        actual = _to_float(pe.actual_price)
        if predicted is None or actual is None or actual <= 0:
            continue
        fc = _forecast_for_evaluation(pe, forecast_lookup)
        lower = _to_float(getattr(fc, "yhat_lower", None)) if fc is not None else None
        upper = _to_float(getattr(fc, "yhat_upper", None)) if fc is not None else None
        signed_error_pct = (predicted - actual) / actual * 100.0
        error_pct = _to_float(pe.error_pct)
        if error_pct is None:
            error_pct = abs(signed_error_pct)
        interval = _interval_hit(actual, lower, upper)
        direction_correct = pe.direction_correct
        level = classify_deviation_level(error_pct, direction_correct, interval)

        pred_date = _to_date(pe.prediction_date)
        target_date = _to_date(pe.target_date)
        horizon_days = None
        if pred_date is not None and target_date is not None:
            if horizon_resolver:
                try:
                    horizon_days = horizon_resolver(pred_date, target_date)
                except Exception:
                    horizon_days = max((target_date - pred_date).days, 0)
            else:
                horizon_days = max((target_date - pred_date).days, 0)

        reasons = []
        if error_pct >= 8:
            reasons.append("价格偏差较大")
        if direction_correct is False:
            reasons.append("方向判断未命中")
        if interval is False:
            reasons.append("实际收盘落在预测区间外")
        if not reasons:
            reasons.append("轻微偏差，继续观察")

        cases.append({
            "target_date": target_date.isoformat() if target_date else None,
            "prediction_date": pred_date.isoformat() if pred_date else None,
            "model": pe.model_name,
            "horizon_days": horizon_days,
            "predicted_price": round(predicted, 2),
            "actual_price": round(actual, 2),
            "lower": round(lower, 2) if lower is not None else None,
            "upper": round(upper, 2) if upper is not None else None,
            "error_pct": round(error_pct, 2),
            "signed_error_pct": round(signed_error_pct, 2),
            "direction_correct": direction_correct,
            "interval_hit": interval,
            "deviation_level": level,
            "reason": "、".join(reasons),
        })

    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "pending": 4}
    cases.sort(key=lambda c: (rank.get(c.get("deviation_level"), 9), -(c.get("error_pct") or 0), c.get("target_date") or ""))
    return cases[:limit]


def aggregate_stock_evaluation_summary(
    evaluations: List[PredictionEvaluation],
    forecast_lookup: Optional[dict] = None,
) -> dict:
    """聚合单只股票的评估摘要，用于产品侧解释和持续评估闭环。"""
    evaluated = [e for e in evaluations if _to_float(e.actual_price) is not None and _to_float(e.predicted_price) is not None]
    errors = []
    signed_errors = []
    directions = []
    intervals = []
    levels = []
    latest_eval = None
    for pe in evaluated:
        predicted = _to_float(pe.predicted_price)
        actual = _to_float(pe.actual_price)
        if predicted is None or actual is None or actual <= 0:
            continue
        signed = (predicted - actual) / actual * 100.0
        error = _to_float(pe.error_pct)
        if error is None:
            error = abs(signed)
        errors.append(error)
        signed_errors.append(signed)
        if pe.direction_correct is not None:
            directions.append(bool(pe.direction_correct))
        fc = _forecast_for_evaluation(pe, forecast_lookup)
        interval = _interval_hit(actual, _to_float(getattr(fc, "yhat_lower", None)) if fc else None, _to_float(getattr(fc, "yhat_upper", None)) if fc else None)
        if interval is not None:
            intervals.append(interval)
        levels.append(classify_deviation_level(error, pe.direction_correct, interval))
        if pe.evaluated_at and (latest_eval is None or pe.evaluated_at > latest_eval):
            latest_eval = pe.evaluated_at

    return {
        "total_records": len(evaluations),
        "evaluated_records": len(evaluated),
        "pending_records": sum(1 for e in evaluations if _to_float(e.actual_price) is None),
        "mape": round(sum(errors) / len(errors), 2) if errors else None,
        "signed_bias_pct": round(sum(signed_errors) / len(signed_errors), 2) if signed_errors else None,
        "direction_accuracy": round(sum(1 for ok in directions if ok) / len(directions) * 100, 1) if directions else None,
        "interval_hit_rate": round(sum(1 for ok in intervals if ok) / len(intervals) * 100, 1) if intervals else None,
        "high_deviation_count": sum(1 for level in levels if level in ("high", "critical")),
        "latest_evaluated_at": latest_eval.isoformat() if latest_eval else None,
    }


def build_evaluation_availability(
    symbol: str,
    evaluations: List[PredictionEvaluation],
    forecasts: List[Forecast],
    price_rows: List[PriceDaily],
    latest_pipeline_run: Optional[Any] = None,
    min_samples: int = 3,
    today: Optional[date] = None,
    supported_record_count: Optional[int] = None,
) -> dict:
    """说明历史预测对比为什么可用/不可用。"""
    today = today or date.today()
    price_dates = {_to_date(p.trade_date) for p in price_rows if _to_date(p.trade_date) is not None and _to_float(p.close) is not None}
    latest_price_date = max(price_dates) if price_dates else None
    evaluated_count = sum(1 for e in evaluations if _to_float(e.actual_price) is not None)
    valid_pred_count = sum(1 for e in evaluations if _to_float(e.predicted_price) is not None)
    forecast_valid_count = sum(1 for f in forecasts if _to_float(f.yhat) is not None)
    latest_forecast = max(forecasts, key=lambda f: (getattr(f, "run_at", datetime.min) or datetime.min, getattr(f, "target_date", date.min) or date.min), default=None)
    latest_eval = max(evaluations, key=lambda e: (e.target_date, e.prediction_date), default=None)
    pipeline_status = getattr(latest_pipeline_run, "status", None) if latest_pipeline_run is not None else None
    pipeline_run_type = getattr(latest_pipeline_run, "run_type", None) if latest_pipeline_run is not None else None
    pipeline_message = getattr(latest_pipeline_run, "error_message", None) or getattr(latest_pipeline_run, "message", None) if latest_pipeline_run is not None else None

    due_missing = [
        e for e in evaluations
        if e.target_date <= today and _to_float(e.actual_price) is None
    ]
    due_forecast_missing = [
        f for f in forecasts
        if f.target_date <= today and f.target_date not in price_dates
    ]
    pending_targets = [
        f for f in forecasts
        if f.target_date > today
    ]

    status = "available"
    reason = "已有可复盘的历史预测样本。"
    next_action = "继续按日评估，并关注高偏差样本。"
    available = evaluated_count > 0

    if not forecasts and not evaluations:
        status = "no_prediction_snapshot"
        reason = "当前股票还没有可用于复盘的预测快照。"
        next_action = "等待下一次日常预测任务生成 Forecast 记录。"
        available = False
    elif pipeline_status == "failed" and evaluated_count == 0:
        status = "task_failed"
        reason = "最近一次预测或行情任务失败，暂时无法形成对比样本。"
        next_action = "请先查看流水线诊断，修复失败任务后重新生成预测。"
        available = False
    elif valid_pred_count == 0 and forecast_valid_count == 0:
        status = "invalid_prediction_data"
        reason = "预测记录存在，但预测价格为空或不可用。"
        next_action = "需要重新生成预测，或检查模型输出字段。"
        available = False
    elif evaluated_count == 0 and pending_targets:
        next_target = min(f.target_date for f in pending_targets)
        status = "pending_target_date"
        reason = f"最新预测目标日 {next_target.isoformat()} 尚未到达，暂时不能与实际收盘比较。"
        next_action = "目标交易日收盘数据入库后会自动进入复盘。"
        available = False
    elif evaluated_count == 0 and (due_missing or due_forecast_missing):
        status = "missing_actual_price"
        reason = "已有到期预测，但缺少目标日实际收盘价。"
        next_action = "请检查日线行情同步任务或数据源回退链路。"
        available = False
    elif evaluated_count > 0 and supported_record_count == 0:
        status = "unsupported_horizon"
        reason = "已有评估样本，但预测跨度不属于当前图表支持的 D-1/D-5 复盘线。"
        next_action = "可在偏差复盘中查看全部跨度，图表层后续可扩展更多 horizon。"
        available = False
    elif 0 < evaluated_count < min_samples:
        status = "insufficient_samples"
        reason = f"当前只有 {evaluated_count} 条已评估样本，统计稳定性不足。"
        next_action = "继续累积样本后再解读 MAPE、方向准确率等指标。"
        available = True

    latest_prediction_date = None
    latest_target_date = None
    if latest_forecast is not None:
        latest_prediction_date = _to_date(getattr(latest_forecast, "run_at", None))
        latest_target_date = _to_date(getattr(latest_forecast, "target_date", None))
    elif latest_eval is not None:
        latest_prediction_date = _to_date(latest_eval.prediction_date)
        latest_target_date = _to_date(latest_eval.target_date)

    next_evaluable_date = min((f.target_date for f in pending_targets), default=None)
    return {
        "symbol": symbol,
        "available": available,
        "status": status,
        "reason": reason,
        "next_action": next_action,
        "min_samples": min_samples,
        "forecast_records": len(forecasts),
        "evaluation_records": len(evaluations),
        "evaluated_records": evaluated_count,
        "supported_records": supported_record_count,
        "pending_records": sum(1 for e in evaluations if _to_float(e.actual_price) is None),
        "missing_actual_records": len(due_missing) + len(due_forecast_missing),
        "latest_prediction_date": latest_prediction_date.isoformat() if latest_prediction_date else None,
        "latest_target_date": latest_target_date.isoformat() if latest_target_date else None,
        "latest_actual_date": latest_price_date.isoformat() if latest_price_date else None,
        "next_evaluable_date": next_evaluable_date.isoformat() if next_evaluable_date else None,
        "pipeline_status": pipeline_status,
        "pipeline_run_type": pipeline_run_type,
        "pipeline_message": str(pipeline_message)[:200] if pipeline_message else None,
    }


def build_prediction_quality(
    symbol: str,
    summary: dict,
    availability: dict,
    deviation_cases: Optional[List[dict]] = None,
) -> dict:
    """把历史预测复盘聚合为产品侧质量等级。"""
    deviation_cases = deviation_cases or []
    evaluated_count = int(summary.get("evaluated_records") or 0)
    min_samples = int(availability.get("min_samples") or 3)
    mape = _to_float(summary.get("mape"))
    direction_accuracy = _to_float(summary.get("direction_accuracy"))
    interval_hit_rate = _to_float(summary.get("interval_hit_rate"))
    signed_bias_pct = _to_float(summary.get("signed_bias_pct"))
    high_deviation_count = int(summary.get("high_deviation_count") or 0)

    score = None
    if evaluated_count > 0 and mape is not None:
        score = 100.0
        score -= min(max(mape, 0), 30) * 3.2
        if direction_accuracy is not None:
            score += (direction_accuracy - 50.0) * 0.35
        if interval_hit_rate is not None:
            score += (interval_hit_rate - 50.0) * 0.15
        if signed_bias_pct is not None:
            score -= min(abs(signed_bias_pct), 20) * 1.2
        score -= high_deviation_count * 5.0
        if evaluated_count < min_samples:
            score -= (min_samples - evaluated_count) * 8.0
        score = round(max(0.0, min(100.0, score)), 1)

    if score is None:
        grade = "unknown"
    elif score >= 80:
        grade = "excellent"
    elif score >= 65:
        grade = "good"
    elif score >= 50:
        grade = "watch"
    else:
        grade = "risk"

    if evaluated_count >= 15:
        confidence_level = "high"
    elif evaluated_count >= 5:
        confidence_level = "medium"
    elif evaluated_count > 0:
        confidence_level = "low"
    else:
        confidence_level = "unknown"

    warnings: List[str] = []
    if evaluated_count == 0:
        warnings.append(availability.get("reason") or "暂无可评估样本。")
    elif evaluated_count < min_samples:
        warnings.append("样本数偏少，质量评分仅供趋势参考。")
    if high_deviation_count > 0:
        warnings.append(f"近窗存在 {high_deviation_count} 个高偏差样本，建议优先复盘。")
    if signed_bias_pct is not None and abs(signed_bias_pct) >= 5:
        direction = "高估" if signed_bias_pct > 0 else "低估"
        warnings.append(f"模型近期存在系统性{direction}倾向。")
    if availability.get("pipeline_status") == "failed":
        warnings.append("最近流水线失败，质量判断可能滞后。")

    grade_labels = {
        "excellent": "稳定",
        "good": "可用",
        "watch": "观察",
        "risk": "高风险",
        "unknown": "待评估",
    }
    if grade == "unknown":
        headline = availability.get("reason") or "暂无足够预测评估样本。"
    elif grade == "risk":
        headline = "近期预测偏差较大，建议降低对单次预测的依赖。"
    elif grade == "watch":
        headline = "预测质量处于观察区间，需要结合偏差复盘使用。"
    else:
        headline = "近期预测质量可用于辅助判断，但仍需结合风险约束。"

    return {
        "symbol": symbol,
        "quality_score": score,
        "quality_grade": grade,
        "quality_label": grade_labels[grade],
        "confidence_level": confidence_level,
        "sample_count": evaluated_count,
        "min_samples": min_samples,
        "mape": mape,
        "signed_bias_pct": signed_bias_pct,
        "direction_accuracy": direction_accuracy,
        "interval_hit_rate": interval_hit_rate,
        "high_deviation_count": high_deviation_count,
        "latest_evaluated_at": summary.get("latest_evaluated_at"),
        "availability_status": availability.get("status"),
        "headline": headline,
        "next_action": availability.get("next_action") or "继续累积样本并观察高偏差案例。",
        "warnings": warnings[:4],
        "top_deviation_cases": deviation_cases[:3],
    }


class PredictionService:
    """预测结果的记录、回填与查询"""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # 1. 从 forecasts 表同步预测记录到 prediction_evaluations
    # ------------------------------------------------------------------

    def sync_forecasts(self, lookback_days: int = 7, symbol: Optional[str] = None) -> int:
        """将近 N 天新产生的 Forecast 行同步到 prediction_evaluations

        只写入 predicted 部分，actual 部分由 backfill_actuals() 回填。
        Returns: 新插入的行数
        """
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        stmt = select(Forecast).where(Forecast.run_at >= cutoff)
        if symbol:
            stmt = stmt.where(Forecast.symbol == symbol.upper())

        forecasts = self.session.execute(stmt).scalars().all()

        inserted = 0
        for fc in forecasts:
            pred_date = fc.run_at.date() if isinstance(fc.run_at, datetime) else fc.run_at
            target_date = fc.target_date
            model_name = fc.model or "unknown"

            exists = self.session.execute(
                select(PredictionEvaluation.id).where(
                    PredictionEvaluation.symbol == fc.symbol,
                    PredictionEvaluation.prediction_date == pred_date,
                    PredictionEvaluation.target_date == target_date,
                    PredictionEvaluation.model_name == model_name,
                )
            ).scalar_one_or_none()

            if exists is not None:
                continue

            pe = PredictionEvaluation(
                symbol=fc.symbol,
                prediction_date=pred_date,
                target_date=target_date,
                model_name=model_name,
                predicted_price=float(fc.yhat) if fc.yhat else None,
                confidence=None,
            )
            self.session.add(pe)
            inserted += 1

        self.session.commit()
        if inserted:
            logger.info("sync_forecasts: 新增 %d 条预测评估记录", inserted)
        return inserted

    # ------------------------------------------------------------------
    # 2. 回填实际价格
    # ------------------------------------------------------------------

    def backfill_actuals(self, symbol: Optional[str] = None) -> int:
        """回填尚未评估的 prediction_evaluations 行

        读取 prices_daily 获取 target_date 当日的实际收盘价，
        计算 error_pct + direction_correct。
        Returns: 回填的行数
        """
        stmt = select(PredictionEvaluation).where(
            PredictionEvaluation.actual_price.is_(None),
            PredictionEvaluation.target_date <= date.today(),
        )
        if symbol:
            stmt = stmt.where(PredictionEvaluation.symbol == symbol.upper())

        pending = self.session.execute(stmt).scalars().all()

        if not pending:
            return 0

        symbols = set(p.symbol for p in pending)
        target_dates = set(p.target_date for p in pending)

        # 批量加载实际价格
        prices = self.session.execute(
            select(PriceDaily).where(
                PriceDaily.symbol.in_(symbols),
                PriceDaily.trade_date.in_(target_dates),
            )
        ).scalars().all()

        price_map: Dict[tuple, float] = {}
        for p in prices:
            td = p.trade_date
            if isinstance(td, datetime):
                td = td.date()
            price_map[(p.symbol, td)] = float(p.close)

        # 收集所有相关日期范围，用于查找 target_date 前一天的收盘价
        all_price_rows = self.session.execute(
            select(PriceDaily).where(
                PriceDaily.symbol.in_(symbols),
            ).order_by(PriceDaily.trade_date)
        ).scalars().all()

        # symbol → sorted list of (date, close)
        from collections import defaultdict
        symbol_prices: Dict[str, list] = defaultdict(list)
        for p in all_price_rows:
            td = p.trade_date
            if isinstance(td, datetime):
                td = td.date()
            if p.close is not None:
                symbol_prices[p.symbol].append((td, float(p.close)))

        def _get_prev_close(sym: str, target: date) -> Optional[float]:
            """获取 target_date 之前最近一个交易日的收盘价"""
            pts = symbol_prices.get(sym, [])
            prev = None
            for d, c in pts:
                if d >= target:
                    break
                prev = c
            return prev

        filled = 0
        for pe in pending:
            td = pe.target_date
            if isinstance(td, datetime):
                td = td.date()
            actual = price_map.get((pe.symbol, td))
            if actual is None:
                continue

            prev_close = _get_prev_close(pe.symbol, td)

            pe.actual_price = actual
            pe.evaluated_at = datetime.utcnow()

            if pe.predicted_price and actual:
                pe.error_pct = abs(pe.predicted_price - actual) / actual * 100.0

            if prev_close and actual and pe.predicted_price:
                pe.actual_direction = "up" if actual > prev_close else "down"
                pe.predicted_direction = "up" if pe.predicted_price > prev_close else "down"
                pe.direction_correct = pe.predicted_direction == pe.actual_direction
            filled += 1

        self.session.commit()
        if filled:
            logger.info("backfill_actuals: 回填 %d 条预测评估", filled)
        return filled

    # ------------------------------------------------------------------
    # 3. 查询
    # ------------------------------------------------------------------

    def get_recent_evaluations(
        self, symbol: str, n: int = 20
    ) -> List[PredictionEvaluation]:
        """查询某个 symbol 最近 n 条已评估的记录"""
        return list(
            self.session.execute(
                select(PredictionEvaluation)
                .where(
                    PredictionEvaluation.symbol == symbol,
                    PredictionEvaluation.actual_price.isnot(None),
                )
                .order_by(PredictionEvaluation.target_date.desc())
                .limit(n)
            ).scalars().all()
        )

    def get_accuracy_summary(self, symbol: str, days: int = 30) -> Dict:
        """获取 symbol 过去 N 天的预测准确率摘要"""
        cutoff = date.today() - timedelta(days=days)
        evals = self.session.execute(
            select(PredictionEvaluation).where(
                PredictionEvaluation.symbol == symbol,
                PredictionEvaluation.actual_price.isnot(None),
                PredictionEvaluation.target_date >= cutoff,
            )
        ).scalars().all()

        if not evals:
            return {"symbol": symbol, "total": 0}

        total = len(evals)
        direction_evals = [e for e in evals if e.direction_correct is not None]
        dir_correct = sum(1 for e in direction_evals if e.direction_correct is True)
        errors = [float(e.error_pct) for e in evals if e.error_pct is not None]
        avg_error = sum(errors) / len(errors) if errors else 0.0

        return {
            "symbol": symbol,
            "total": total,
            "direction_accuracy": dir_correct / len(direction_evals) if direction_evals else 0,
            "avg_error_pct": avg_error,
            "days": days,
        }

    def count_consecutive_failures(
        self,
        symbol: str,
        error_threshold_pct: Optional[float] = None,
    ) -> int:
        """计算 symbol 最近连续失败次数。

        默认沿用方向预测错误；传入 error_threshold_pct 后，严重价格偏差也计为失败。
        """
        evals = self.session.execute(
            select(PredictionEvaluation)
            .where(
                PredictionEvaluation.symbol == symbol,
                PredictionEvaluation.actual_price.isnot(None),
            )
            .order_by(PredictionEvaluation.target_date.desc())
            .limit(20)
        ).scalars().all()

        streak = 0
        for e in evals:
            direction_failed = e.direction_correct is False
            error_failed = (
                error_threshold_pct is not None
                and e.error_pct is not None
                and float(e.error_pct) >= float(error_threshold_pct)
            )
            if direction_failed or error_failed:
                streak += 1
            else:
                break
        return streak
