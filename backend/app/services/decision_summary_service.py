"""Dashboard decision summary aggregation service.

This module builds a stable, UI-friendly contract for the main decision
workbench by reusing existing prediction, trade decision, factor context and
Agent review services. It does not place orders or generate investment advice.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..core.models import (
    Forecast,
    PipelineRun,
    PredictionEvaluation,
    PriceDaily,
    StockPoolMember,
    StockProfile,
    Watchlist,
)
from ..prediction.services.agent_review_service import build_agent_review
from ..prediction.services.agent_verification_service import build_agent_verification
from ..prediction.services.failure_analysis_service import build_failure_analysis
from ..prediction.services.factor_context_service import load_stock_factor_context
from ..prediction.services.feature_snapshot_service import build_feature_snapshot
from ..prediction.services.prediction_service import (
    aggregate_stock_evaluation_summary,
    build_deviation_cases,
    build_evaluation_availability,
    build_prediction_quality,
)
from ..prediction.services.trade_decision_service import DISCLAIMER, build_trade_decision
from ..quant_engine.models import QEPrediction, QESignal, QEModelVersion, QEStockModel


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return None


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _latest_or_none(session: Session, model: Any, symbol: str, order_field: Any) -> Any:
    return session.execute(
        select(model)
        .where(model.symbol == symbol)
        .order_by(order_field.desc())
        .limit(1)
    ).scalar_one_or_none()


def _load_symbols(
    session: Session,
    *,
    symbol: Optional[str],
    limit: int,
    pinned_only: bool,
) -> tuple[list[str], str]:
    if symbol:
        return [symbol.upper()], "selected-symbol"

    stmt = select(StockPoolMember.symbol).where(StockPoolMember.exit_date.is_(None))
    if pinned_only:
        stmt = stmt.join(Watchlist, Watchlist.symbol == StockPoolMember.symbol).where(Watchlist.pinned.is_(True))
    stmt = stmt.order_by(StockPoolMember.last_seen_date.desc(), StockPoolMember.symbol.asc()).limit(limit)
    symbols = [row[0] for row in session.execute(stmt).all()]

    if symbols or pinned_only:
        return symbols, "pinned-stock-pool" if pinned_only else "stock-pool"

    fallback_stmt = (
        select(Watchlist.symbol)
        .where(and_(Watchlist.status == "active", Watchlist.enabled.is_(True)))
        .order_by(Watchlist.pinned.desc(), Watchlist.score.desc(), Watchlist.symbol.asc())
        .limit(limit)
    )
    return [row[0] for row in session.execute(fallback_stmt).all()], "active-watchlist"


def _load_meta(session: Session, symbols: list[str]) -> dict[str, dict[str, Optional[str]]]:
    if not symbols:
        return {}
    profiles = session.execute(select(StockProfile).where(StockProfile.symbol.in_(symbols))).scalars().all()
    watch_rows = session.execute(select(Watchlist).where(Watchlist.symbol.in_(symbols))).scalars().all()
    meta = {sym: {"name": None, "sector": None, "market": None} for sym in symbols}
    for profile in profiles:
        meta.setdefault(profile.symbol, {})
        meta[profile.symbol].update({
            "name": profile.company_name,
            "sector": profile.industry,
            "market": profile.market,
        })
    for watch in watch_rows:
        meta.setdefault(watch.symbol, {})
        if not meta[watch.symbol].get("name"):
            meta[watch.symbol]["name"] = watch.name
        if not meta[watch.symbol].get("sector"):
            meta[watch.symbol]["sector"] = watch.sector
    return meta


def _load_model_accuracy(session: Session, symbol: str) -> Optional[float]:
    verified = session.execute(
        select(QEPrediction)
        .where(and_(QEPrediction.symbol == symbol, QEPrediction.actual_direction.isnot(None)))
        .order_by(QEPrediction.predict_date.desc())
        .limit(30)
    ).scalars().all()
    eligible = [p for p in verified if p.direction_prob_up is not None]
    if not eligible:
        return None
    correct = sum(1 for p in eligible if (p.direction_prob_up > 0.5) == (p.actual_direction == 1))
    return round(correct / len(eligible) * 100, 1)


def _load_model_metrics(session: Session, symbol: str) -> dict:
    stock_model = session.execute(select(QEStockModel).where(QEStockModel.symbol == symbol).limit(1)).scalar_one_or_none()
    active_version = getattr(stock_model, "active_version", None)
    if not active_version:
        return {}
    model_version = session.execute(select(QEModelVersion).where(QEModelVersion.id == active_version)).scalar_one_or_none()
    return _json_dict(getattr(model_version, "metrics_json", None))


def _build_quality_bundle(session: Session, symbol: str, lookback_days: int) -> dict:
    cutoff = date.today() - timedelta(days=lookback_days)
    forecast_cutoff = datetime.combine(cutoff - timedelta(days=10), datetime.min.time())

    forecasts = list(session.execute(
        select(Forecast)
        .where(Forecast.symbol == symbol, Forecast.run_at >= forecast_cutoff)
        .order_by(Forecast.run_at.desc())
        .limit(300)
    ).scalars().all())
    evaluations = list(session.execute(
        select(PredictionEvaluation)
        .where(PredictionEvaluation.symbol == symbol, PredictionEvaluation.target_date >= cutoff)
        .order_by(PredictionEvaluation.target_date.asc(), PredictionEvaluation.prediction_date.desc())
    ).scalars().all())
    price_rows = list(session.execute(
        select(PriceDaily)
        .where(
            PriceDaily.symbol == symbol,
            PriceDaily.trade_date >= cutoff - timedelta(days=10),
            PriceDaily.trade_date <= date.today(),
        )
        .order_by(PriceDaily.trade_date.asc())
    ).scalars().all())
    latest_pipeline_run = session.execute(
        select(PipelineRun)
        .where(PipelineRun.symbol == symbol, PipelineRun.run_type.in_(["fetch_daily", "predict", "daily_pipeline", "full_report"]))
        .order_by(PipelineRun.run_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    forecast_lookup = {
        (fc.run_at.date() if isinstance(fc.run_at, datetime) else fc.run_at, fc.target_date, fc.model): fc
        for fc in forecasts
    }
    summary = aggregate_stock_evaluation_summary(evaluations, forecast_lookup)
    availability = build_evaluation_availability(
        symbol,
        evaluations,
        forecasts,
        price_rows,
        latest_pipeline_run=latest_pipeline_run,
        supported_record_count=len(evaluations),
    )
    deviation_cases = build_deviation_cases(evaluations, forecast_lookup, limit=5)
    quality = build_prediction_quality(symbol, summary, availability, deviation_cases)
    return {
        "summary": summary,
        "availability": availability,
        "deviation_cases": deviation_cases,
        "quality": quality,
        "diagnostics": {
            "forecast_records": len(forecasts),
            "evaluation_records": len(evaluations),
            "price_records": len(price_rows),
        },
    }


def _dashboard_label(trade_decision: dict, quality: dict, feature_snapshot: Optional[dict]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    label = trade_decision.get("signal_label") or "观望"
    sample_count = int(quality.get("sample_count") or 0)
    min_samples = int(quality.get("min_samples") or 3)
    grade = quality.get("quality_grade")
    completeness = _to_float((feature_snapshot or {}).get("completeness_score"))

    if sample_count < min_samples:
        label = "观察"
        warnings.append("预测评估样本偏少，首页仅给观察级辅助结论。")
    if grade in {"risk", "unknown"}:
        label = "观察"
        warnings.append(quality.get("headline") or "预测质量不足，已降级为观察。")
    if trade_decision.get("risk_level") in {"high", "extreme"}:
        warnings.append("风险评分偏高，仓位建议需从严控制。")
    if completeness is not None and completeness < 60:
        label = "观察"
        warnings.append(f"特征覆盖率 {completeness:.1f}%，证据不足。")
    return label, warnings[:4]


def _score_recommendation(trade_decision: dict, quality: dict, latest_signal: Any, feature_snapshot: Optional[dict]) -> float:
    confidence = _to_float(trade_decision.get("confidence")) or 0.0
    expected_return = _to_float(trade_decision.get("expected_return")) or 0.0
    signal_score = _to_float(getattr(latest_signal, "score", None)) or 50.0
    risk_score = _to_float(trade_decision.get("risk_score")) or 50.0
    quality_score = _to_float(quality.get("quality_score"))
    completeness = _to_float((feature_snapshot or {}).get("completeness_score"))

    score = signal_score * 0.36 + confidence * 100 * 0.22
    score += max(min(expected_return * 100, 12), -12) * 1.2
    score += (quality_score if quality_score is not None else 45) * 0.18
    score += (completeness if completeness is not None else 55) * 0.10
    score -= max(risk_score - 50, 0) * 0.30
    return round(max(0.0, min(100.0, score)), 1)


def _build_recommendation(session: Session, symbol: str, meta: dict, lookback_days: int) -> dict:
    latest_signal = _latest_or_none(session, QESignal, symbol, QESignal.signal_date)
    latest_prediction = _latest_or_none(session, QEPrediction, symbol, QEPrediction.predict_date)
    latest_price = _latest_or_none(session, PriceDaily, symbol, PriceDaily.trade_date)
    current_price = _to_float(getattr(latest_price, "close", None))
    factors = _json_dict(getattr(latest_signal, "factors_json", None))
    model_accuracy = _load_model_accuracy(session, symbol)
    quality_bundle = _build_quality_bundle(session, symbol, lookback_days)

    factor_context = None
    try:
        factor_context = load_stock_factor_context(session, symbol, factors=factors, window_days=7)
    except Exception:
        factor_context = None

    model_metrics = _load_model_metrics(session, symbol)
    feature_snapshot = None
    try:
        feature_snapshot = build_feature_snapshot(
            symbol,
            prediction=latest_prediction,
            signal=latest_signal,
            latest_price=latest_price,
            factors=factors,
            factor_context=factor_context,
            model_metrics=model_metrics,
        )
    except Exception:
        feature_snapshot = None

    trade_decision = build_trade_decision(
        symbol=symbol,
        signal=latest_signal,
        prediction=latest_prediction,
        current_price=current_price,
        factors=factors,
        model_accuracy=model_accuracy,
    )
    dashboard_label, warnings = _dashboard_label(trade_decision, quality_bundle["quality"], feature_snapshot)
    factor_counts = (feature_snapshot or {}).get("factor_counts") or {}
    macro = (factor_context or {}).get("macro") or {}
    recommendation = {
        "symbol": symbol,
        "name": meta.get("name") or symbol,
        "sector": meta.get("sector"),
        "market": meta.get("market"),
        "decision_signal": trade_decision.get("signal"),
        "decision_label": trade_decision.get("signal_label"),
        "dashboard_label": dashboard_label,
        "confidence": trade_decision.get("confidence"),
        "composite_score": _score_recommendation(trade_decision, quality_bundle["quality"], latest_signal, feature_snapshot),
        "expected_return": trade_decision.get("expected_return"),
        "risk_level": trade_decision.get("risk_level"),
        "risk_score": trade_decision.get("risk_score"),
        "latest_price": current_price,
        "price_change_pct": _to_float(getattr(latest_price, "pct_chg", None)),
        "price_date": _iso(getattr(latest_price, "trade_date", None)),
        "signal_date": _iso(getattr(latest_signal, "signal_date", None)),
        "prediction_target_date": _iso(getattr(latest_prediction, "target_date", None)),
        "quality_grade": quality_bundle["quality"].get("quality_grade"),
        "quality_label": quality_bundle["quality"].get("quality_label"),
        "quality_score": quality_bundle["quality"].get("quality_score"),
        "sample_count": quality_bundle["quality"].get("sample_count"),
        "data_completeness": (feature_snapshot or {}).get("completeness_score"),
        "news_article_count": int(factor_counts.get("news_articles") or 0),
        "macro_breadth_label": macro.get("breadth_label"),
        "reasons": (trade_decision.get("reasons") or [])[:4],
        "warnings": warnings + (quality_bundle["quality"].get("warnings") or [])[:2],
        "trade_decision": trade_decision,
        "diagnostics": quality_bundle["diagnostics"],
        "_quality_bundle": quality_bundle,
        "_feature_snapshot": feature_snapshot,
        "_factor_context": factor_context,
    }
    return recommendation


def _build_selected_stock(recommendation: Optional[dict]) -> Optional[dict]:
    if not recommendation:
        return None
    quality_bundle = recommendation.pop("_quality_bundle", None) or {}
    feature_snapshot = recommendation.pop("_feature_snapshot", None)
    factor_context = recommendation.pop("_factor_context", None)
    failure_analysis = build_failure_analysis(
        recommendation["symbol"],
        quality_bundle.get("deviation_cases") or [],
        quality=quality_bundle.get("quality") or {},
        feature_snapshot=feature_snapshot,
    )
    agent_review = build_agent_review(
        recommendation["symbol"],
        failure_analysis=failure_analysis,
        feature_snapshot=feature_snapshot,
    )
    verification = build_agent_verification(agent_review, failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)
    agent_review["verification_status"] = verification["verification_status"]
    agent_review["verification_checks"] = verification["checks"]
    agent_review["gate_result"] = verification["gate_result"]
    return {
        "symbol": recommendation["symbol"],
        "name": recommendation["name"],
        "sector": recommendation.get("sector"),
        "market": recommendation.get("market"),
        "latest_price": recommendation.get("latest_price"),
        "price_change_pct": recommendation.get("price_change_pct"),
        "price_date": recommendation.get("price_date"),
        "trade_decision": recommendation.get("trade_decision"),
        "prediction_quality": quality_bundle.get("quality"),
        "prediction_summary": quality_bundle.get("summary"),
        "prediction_availability": quality_bundle.get("availability"),
        "deviation_cases": quality_bundle.get("deviation_cases") or [],
        "failure_analysis": failure_analysis,
        "agent_review": agent_review,
        "feature_snapshot": feature_snapshot,
        "factor_context": factor_context,
    }


def _summarize_quality(recommendations: list[dict]) -> dict:
    scores = [_to_float(item.get("quality_score")) for item in recommendations]
    scores = [score for score in scores if score is not None]
    return {
        "average_quality_score": round(sum(scores) / len(scores), 1) if scores else None,
        "usable_count": sum(1 for item in recommendations if item.get("quality_grade") in {"excellent", "good"}),
        "watch_count": sum(1 for item in recommendations if item.get("quality_grade") == "watch"),
        "risk_count": sum(1 for item in recommendations if item.get("quality_grade") == "risk"),
        "unknown_count": sum(1 for item in recommendations if item.get("quality_grade") == "unknown"),
    }


def _build_data_health(recommendations: list[dict], source: str, requested_count: int) -> dict:
    warnings = []
    if not recommendations:
        warnings.append("当前范围内没有可展示的决策摘要数据。")
    missing_news = sum(1 for item in recommendations if int(item.get("news_article_count") or 0) == 0)
    weak_quality = sum(1 for item in recommendations if item.get("quality_grade") in {"risk", "unknown"})
    if missing_news:
        warnings.append(f"{missing_news} 只股票缺少近窗新闻证据。")
    if weak_quality:
        warnings.append(f"{weak_quality} 只股票预测质量不足，已在首页降级为观察。")
    return {
        "source": source,
        "requested_count": requested_count,
        "returned_count": len(recommendations),
        "with_signal": sum(1 for item in recommendations if item.get("signal_date")),
        "with_prediction": sum(1 for item in recommendations if item.get("prediction_target_date")),
        "with_price": sum(1 for item in recommendations if item.get("latest_price") is not None),
        "missing_news_count": missing_news,
        "weak_quality_count": weak_quality,
        "warnings": warnings[:4],
    }


def _build_model_review_summary(selected_stock: Optional[dict]) -> dict:
    if not selected_stock:
        return {
            "headline": "暂无选中股票复盘。",
            "gate_status": "unknown",
            "verification_status": "unknown",
            "next_actions": [],
        }
    failure = selected_stock.get("failure_analysis") or {}
    review = selected_stock.get("agent_review") or {}
    gate = review.get("gate_result") or {}
    return {
        "headline": failure.get("headline") or review.get("headline"),
        "severity": failure.get("severity"),
        "gate_status": gate.get("status"),
        "verification_status": review.get("verification_status"),
        "next_actions": (failure.get("next_actions") or [])[:3],
        "blocked_actions": gate.get("blocked_actions") or [],
    }


def _build_optimization_plan(selected_stock: Optional[dict], quality_summary: dict, data_health: dict) -> list[dict]:
    items = []
    if data_health.get("missing_news_count"):
        items.append({
            "type": "data_coverage",
            "priority": "medium",
            "title": "补齐新闻证据覆盖",
            "detail": "部分股票近窗新闻缺失，推荐结论已降级；建议优先补齐新闻抓取和事件证据。",
        })
    if quality_summary.get("risk_count") or quality_summary.get("unknown_count"):
        items.append({
            "type": "prediction_quality",
            "priority": "high",
            "title": "优先复盘低质量预测",
            "detail": "存在预测质量风险或待评估股票，首页不应放大单次预测结论。",
        })
    if selected_stock:
        review = selected_stock.get("agent_review") or {}
        gate = review.get("gate_result") or {}
        items.append({
            "type": "agent_gate",
            "priority": "high" if gate.get("status") == "blocked" else "medium",
            "title": "执行 Agent 门禁复盘",
            "detail": gate.get("message") or "根据失败归因继续受控观察。",
        })
    if not items:
        items.append({
            "type": "monitoring",
            "priority": "low",
            "title": "继续累积样本",
            "detail": "当前摘要未触发高风险优化项，继续观察预测质量和因子覆盖。",
        })
    return items[:4]


def build_decision_summary(
    session: Session,
    *,
    symbol: Optional[str] = None,
    limit: int = 20,
    lookback_days: int = 60,
    pinned_only: bool = True,
    refresh: bool = False,
) -> dict:
    symbols, source = _load_symbols(session, symbol=symbol, limit=limit, pinned_only=pinned_only)
    meta = _load_meta(session, symbols)

    recommendations = []
    for sym in symbols[:limit]:
        try:
            recommendations.append(_build_recommendation(session, sym, meta.get(sym, {}), lookback_days))
        except Exception as exc:
            recommendations.append({
                "symbol": sym,
                "name": (meta.get(sym) or {}).get("name") or sym,
                "sector": (meta.get(sym) or {}).get("sector"),
                "dashboard_label": "观察",
                "composite_score": 0,
                "warnings": [f"决策摘要生成失败：{str(exc)[:120]}"],
                "trade_decision": build_trade_decision(symbol=sym),
            })

    recommendations.sort(key=lambda item: item.get("composite_score") or 0, reverse=True)
    for index, item in enumerate(recommendations, start=1):
        item["rank"] = index

    selected_source = None
    if symbol:
        selected_source = next((item for item in recommendations if item.get("symbol") == symbol.upper()), None)
    if selected_source is None and recommendations:
        selected_source = recommendations[0]

    selected_stock = _build_selected_stock(dict(selected_source)) if selected_source else None
    quality_summary = _summarize_quality(recommendations)
    data_health = _build_data_health(recommendations, source, len(symbols))
    model_review_summary = _build_model_review_summary(selected_stock)
    optimization_plan = _build_optimization_plan(selected_stock, quality_summary, data_health)

    for item in recommendations:
        item.pop("_quality_bundle", None)
        item.pop("_feature_snapshot", None)
        item.pop("_factor_context", None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "symbol": symbol.upper() if symbol else None,
            "limit": limit,
            "lookback_days": lookback_days,
            "pinned_only": pinned_only,
            "refresh": refresh,
        },
        "recommendations": recommendations,
        "selected_stock": selected_stock,
        "prediction_quality_summary": quality_summary,
        "model_review_summary": model_review_summary,
        "optimization_plan": optimization_plan,
        "data_health": data_health,
        "disclaimer": DISCLAIMER,
    }