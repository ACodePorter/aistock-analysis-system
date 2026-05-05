"""交易辅助建议构建器。

该模块只把现有预测、信号和风险字段整理为产品侧可解释结构，不承诺收益，
也不直接生成真实交易指令。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


DISCLAIMER = "本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。"


ACTION_LABELS = {
    "strong_buy": "强买入",
    "buy": "买入",
    "hold": "观望",
    "sell": "卖出",
    "strong_sell": "强卖出",
}


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


def _normalize_action(action: Any, score: Optional[float]) -> str:
    raw = getattr(action, "value", action)
    if isinstance(raw, str) and raw.lower() in ACTION_LABELS:
        return raw.lower()
    if score is None:
        return "hold"
    if score >= 75:
        return "strong_buy"
    if score >= 62:
        return "buy"
    if score >= 45:
        return "hold"
    if score >= 38:
        return "sell"
    return "strong_sell"


def _risk_level(risk_score: Optional[float]) -> str:
    if risk_score is None:
        return "medium"
    if risk_score >= 80:
        return "extreme"
    if risk_score >= 60:
        return "high"
    if risk_score >= 35:
        return "medium"
    return "low"


def _confidence(pred_confidence: Optional[float], score: Optional[float], model_accuracy: Optional[float]) -> float:
    parts = []
    if pred_confidence is not None:
        parts.append(pred_confidence if pred_confidence <= 1 else pred_confidence / 100)
    if score is not None:
        parts.append(min(max(abs(score - 50) / 50, 0), 1))
    if model_accuracy is not None:
        parts.append(model_accuracy / 100 if model_accuracy > 1 else model_accuracy)
    if not parts:
        return 0.5
    return round(min(max(sum(parts) / len(parts), 0), 1), 3)


def _position_pct(action: str, confidence: float, risk_level: str) -> dict:
    risk_cap = {"low": 0.18, "medium": 0.12, "high": 0.06, "extreme": 0.0}.get(risk_level, 0.08)
    if action in {"sell", "strong_sell"}:
        low, high = 0.0, 0.0
    elif action == "hold":
        low, high = 0.0, min(0.08, risk_cap)
    elif action == "buy":
        low, high = 0.03, min(risk_cap, 0.04 + confidence * 0.10)
    else:
        low, high = 0.05, min(risk_cap, 0.06 + confidence * 0.14)
    high = max(high, low)
    return {
        "min": round(low, 3),
        "max": round(high, 3),
        "label": f"{low * 100:.0f}% - {high * 100:.0f}%",
    }


def _derived_prices(current_price: Optional[float], expected_return: Optional[float], risk_score: Optional[float]) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if current_price is None or current_price <= 0:
        return None, None, None, None
    stop_loss_pct = 0.04
    if risk_score is not None:
        stop_loss_pct = 0.04 + min(max(risk_score, 0), 100) / 100 * 0.06
    stop_loss = current_price * (1 - stop_loss_pct)
    upside = expected_return if expected_return is not None and expected_return > 0 else 0.04
    take_profit = current_price * (1 + min(max(upside, 0.025), 0.16))
    downside = (stop_loss - current_price) / current_price
    risk_reward = upside / abs(downside) if downside else None
    return round(stop_loss, 2), round(take_profit, 2), round(downside, 4), round(risk_reward, 2) if risk_reward is not None else None


def _factor_value(factors: dict, *names: str) -> Optional[float]:
    for name in names:
        if name in factors:
            return _to_float(factors.get(name))
    return None


def _factor_evidence(value: Optional[float], label: str, bullish_when_high: bool = True) -> Optional[str]:
    if value is None:
        return None
    if value > 1:
        normalized = value / 100
    else:
        normalized = value
    if bullish_when_high:
        if normalized >= 0.65:
            return f"{label}偏强，提供正向支持"
        if normalized <= 0.35:
            return f"{label}偏弱，构成约束"
    else:
        if normalized >= 0.65:
            return f"{label}偏高，需要降低仓位"
        if normalized <= 0.35:
            return f"{label}较低，风险约束较轻"
    return f"{label}处于中性区间"


def _build_reasons(
    *,
    action: str,
    direction_prob_up: Optional[float],
    expected_return: Optional[float],
    risk_score: Optional[float],
    factors: dict,
    model_accuracy: Optional[float],
) -> list[dict]:
    reasons: list[dict] = []
    if direction_prob_up is not None:
        reasons.append({
            "type": "price_prediction",
            "label": "方向概率",
            "evidence": f"模型上涨概率 {direction_prob_up * 100:.1f}%",
            "weight": 0.28,
        })
    if expected_return is not None:
        reasons.append({
            "type": "price_prediction",
            "label": "预期收益",
            "evidence": f"当前周期预期收益 {expected_return * 100:+.2f}%",
            "weight": 0.24,
        })
    if risk_score is not None:
        reasons.append({
            "type": "risk",
            "label": "风险评分",
            "evidence": f"风险评分 {risk_score:.1f}/100，风险等级 {_risk_level(risk_score)}",
            "weight": 0.20,
        })

    factor_specs = [
        ("technical", "技术动量", _factor_value(factors, "momentum_score", "technical_score"), True, 0.10),
        ("news_sentiment", "新闻情绪", _factor_value(factors, "sentiment_score", "news_sentiment_3d"), True, 0.08),
        ("macro", "市场环境", _factor_value(factors, "regime_confidence", "macro_trend_strength"), True, 0.05),
        ("model_history", "历史命中", model_accuracy, True, 0.05),
    ]
    for reason_type, label, value, bullish_when_high, weight in factor_specs:
        evidence = _factor_evidence(value, label, bullish_when_high)
        if evidence:
            reasons.append({"type": reason_type, "label": label, "evidence": evidence, "weight": weight})

    if not reasons:
        reasons.append({
            "type": "risk",
            "label": "样本不足",
            "evidence": "暂无足够模型信号，默认保持观望",
            "weight": 1.0,
        })
    if action == "hold" and expected_return is not None and abs(expected_return) < 0.02:
        reasons.append({
            "type": "risk",
            "label": "收益风险不突出",
            "evidence": "预期收益不足以形成明确操作倾向",
            "weight": 0.10,
        })
    return reasons[:6]


def build_trade_decision(
    *,
    symbol: str,
    signal: Any = None,
    prediction: Any = None,
    current_price: Optional[float] = None,
    factors: Optional[dict] = None,
    model_accuracy: Optional[float] = None,
) -> dict:
    """从现有 QESignal/QEPrediction 构造统一交易辅助建议。"""
    factors = factors or {}
    score = _to_float(getattr(signal, "score", None))
    risk_score = _to_float(getattr(signal, "risk_score", None))
    action = _normalize_action(getattr(signal, "action", None), score)

    predicted_return = _to_float(getattr(prediction, "predicted_return", None))
    if predicted_return is None:
        predicted_return = _to_float(getattr(signal, "predicted_return", None))
    direction_prob_up = _to_float(getattr(prediction, "direction_prob_up", None))
    if direction_prob_up is None:
        direction_prob_up = _to_float(getattr(signal, "direction_prob_up", None))
    pred_confidence = _to_float(getattr(prediction, "confidence", None))
    confidence = _confidence(pred_confidence, score, model_accuracy)
    level = _risk_level(risk_score)

    stop_loss = _to_float(getattr(signal, "stop_loss", None))
    take_profit = _to_float(getattr(signal, "take_profit", None))
    derived_stop, derived_take, downside, risk_reward = _derived_prices(current_price, predicted_return, risk_score)
    stop_loss = round(stop_loss, 2) if stop_loss is not None else derived_stop
    take_profit = round(take_profit, 2) if take_profit is not None else derived_take

    position = _position_pct(action, confidence, level)
    horizon = getattr(prediction, "horizon", None) or getattr(signal, "holding_period", None) or "5d"
    if isinstance(horizon, int):
        horizon = f"{horizon}d"

    return {
        "stock_code": symbol,
        "signal": action,
        "signal_label": ACTION_LABELS.get(action, action),
        "confidence": confidence,
        "risk_level": level,
        "risk_score": round(risk_score, 2) if risk_score is not None else None,
        "expected_return": round(predicted_return, 4) if predicted_return is not None else None,
        "expected_downside": downside,
        "risk_reward_ratio": risk_reward,
        "suggested_position_pct": position,
        "stop_loss_price": stop_loss,
        "take_profit_price": take_profit,
        "invalidation_condition": "跌破止损位、模型置信度下降或新闻/宏观风险继续恶化时失效。",
        "applicable_horizon": str(horizon),
        "reasons": _build_reasons(
            action=action,
            direction_prob_up=direction_prob_up,
            expected_return=predicted_return,
            risk_score=risk_score,
            factors=factors,
            model_accuracy=model_accuracy,
        ),
        "source": "quant_engine_signal" if signal is not None else "fallback_hold",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
    }