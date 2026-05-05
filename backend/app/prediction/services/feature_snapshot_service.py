"""预测时点特征快照兼容层。

当前版本只生成可序列化 JSON 契约，不新增表结构；后续迁移到持久化 feature_snapshots
时可沿用该响应结构。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.models import PriceDaily
from ...quant_engine.models import QEPrediction, QESignal
from .factor_context_service import load_stock_factor_context


DISCLAIMER = "特征快照用于复盘模型当时可见的信息，不构成投资建议。"


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
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_action(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _snapshot_id(symbol: str, payload: dict) -> str:
    raw = json.dumps({"symbol": symbol, **payload}, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"fs_{symbol.replace('.', '_')}_{digest}"


def _coverage_flag(label: str, available: bool, detail: str) -> dict:
    return {"label": label, "available": available, "detail": detail}


def build_feature_snapshot(
    symbol: str,
    *,
    prediction: Any = None,
    signal: Any = None,
    latest_price: Any = None,
    factor_context: Optional[dict] = None,
    factors: Optional[dict] = None,
    model_metrics: Optional[dict] = None,
) -> dict:
    """把预测、信号、价格和因子解释整理成单次可复盘快照。"""
    factors = factors or {}
    factor_context = factor_context or {}
    price_trade_date = getattr(latest_price, "trade_date", None)
    signal_date = getattr(signal, "signal_date", None)
    predict_date = getattr(prediction, "predict_date", None)
    target_date = getattr(prediction, "target_date", None)
    as_of_date = predict_date or signal_date or price_trade_date

    news = factor_context.get("news") or {}
    macro = factor_context.get("macro") or {}
    quant_factors = factor_context.get("quant_factors") or []
    has_news = int(news.get("article_count") or 0) > 0
    has_macro = int(macro.get("total") or 0) > 0
    has_quant = bool(quant_factors or factors)
    has_prediction = prediction is not None
    has_signal = signal is not None
    has_price = latest_price is not None and _to_float(getattr(latest_price, "close", None)) is not None

    coverage = [
        _coverage_flag("价格", has_price, _iso(price_trade_date) or "暂无最新价格"),
        _coverage_flag("预测", has_prediction, _iso(predict_date) or "暂无量化预测"),
        _coverage_flag("交易信号", has_signal, _iso(signal_date) or "暂无交易信号"),
        _coverage_flag("新闻因子", has_news, f"近窗 {news.get('article_count', 0)} 条关联新闻"),
        _coverage_flag("市场环境", has_macro, macro.get("breadth_label") or "暂无市场广度"),
        _coverage_flag("量化因子", has_quant, f"{len(quant_factors) if quant_factors else len(factors)} 个因子"),
    ]
    completeness_score = round(sum(1 for item in coverage if item["available"]) / len(coverage) * 100, 1)
    warnings = []
    if completeness_score < 60:
        warnings.append("快照覆盖率偏低，后续复盘需谨慎解读。")
    if not has_news:
        warnings.append("缺少近窗关联新闻，无法完整解释事件驱动影响。")
    if not has_prediction:
        warnings.append("缺少最新预测记录，快照只能用于信号解释。")

    lineage_payload = {
        "as_of_date": _iso(as_of_date),
        "predict_date": _iso(predict_date),
        "target_date": _iso(target_date),
        "signal_date": _iso(signal_date),
        "price_trade_date": _iso(price_trade_date),
    }
    snapshot = {
        "snapshot_id": _snapshot_id(symbol, lineage_payload),
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": _iso(as_of_date),
        "source": "latest_prediction_signal_context",
        "prediction": {
            "predict_date": _iso(predict_date),
            "target_date": _iso(target_date),
            "horizon": getattr(prediction, "horizon", None),
            "direction_prob_up": _to_float(getattr(prediction, "direction_prob_up", None)),
            "predicted_return": _to_float(getattr(prediction, "predicted_return", None)),
            "confidence": _to_float(getattr(prediction, "confidence", None)),
        } if prediction is not None else None,
        "signal": {
            "signal_date": _iso(signal_date),
            "action": _as_action(getattr(signal, "action", None)),
            "score": _to_float(getattr(signal, "score", None)),
            "risk_score": _to_float(getattr(signal, "risk_score", None)),
            "rank": getattr(signal, "rank", None),
        } if signal is not None else None,
        "price": {
            "trade_date": _iso(price_trade_date),
            "close": _to_float(getattr(latest_price, "close", None)),
            "pct_chg": _to_float(getattr(latest_price, "pct_chg", None)),
            "vol": _to_float(getattr(latest_price, "vol", None)),
            "amount": _to_float(getattr(latest_price, "amount", None)),
        } if latest_price is not None else None,
        "factor_context": factor_context or None,
        "factor_counts": {
            "news_articles": int(news.get("article_count") or 0),
            "market_breadth_total": int(macro.get("total") or 0),
            "quant_factors": len(quant_factors) if quant_factors else len(factors),
        },
        "model_metrics": model_metrics or {},
        "coverage": coverage,
        "completeness_score": completeness_score,
        "lineage": lineage_payload,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }
    return snapshot


def load_stock_feature_snapshot(
    session: Session,
    symbol: str,
    *,
    prediction: Any = None,
    signal: Any = None,
    latest_price: Any = None,
    factors: Optional[dict] = None,
    factor_context: Optional[dict] = None,
    model_metrics: Optional[dict] = None,
    window_days: int = 7,
) -> dict:
    if signal is None:
        signal = session.execute(
            select(QESignal)
            .where(QESignal.symbol == symbol)
            .order_by(QESignal.signal_date.desc())
            .limit(1)
        ).scalar_one_or_none()
    if prediction is None:
        prediction = session.execute(
            select(QEPrediction)
            .where(QEPrediction.symbol == symbol)
            .order_by(QEPrediction.predict_date.desc())
            .limit(1)
        ).scalar_one_or_none()
    if latest_price is None:
        latest_price = session.execute(
            select(PriceDaily)
            .where(PriceDaily.symbol == symbol)
            .order_by(PriceDaily.trade_date.desc())
            .limit(1)
        ).scalar_one_or_none()
    if factors is None:
        factors = getattr(signal, "factors_json", None) if signal is not None else {}
        if isinstance(factors, str):
            try:
                factors = json.loads(factors)
            except json.JSONDecodeError:
                factors = {}
    if factor_context is None:
        factor_context = load_stock_factor_context(session, symbol, factors=factors or {}, window_days=window_days)
    return build_feature_snapshot(
        symbol,
        prediction=prediction,
        signal=signal,
        latest_price=latest_price,
        factors=factors or {},
        factor_context=factor_context,
        model_metrics=model_metrics,
    )