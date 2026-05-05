"""Trade playbook aggregation service.

This module turns existing prediction, signal, price, fund-flow and context data
into a structured short-term trading playbook for retail users. It never places
orders and never promises outcomes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from .retail_decision_service import (
    RETAIL_DISCLAIMER,
    RetailInputs,
    _build_agent_views,
    _build_price_plan,
    _iso,
    _load_action_symbols,
    _load_inputs,
    _price_stats,
    _round,
    _to_float,
)
from ..prediction.services.trade_decision_service import build_trade_decision


ACTION_LABELS = {
    "executable_now": "立即可执行",
    "wait_for_pullback": "等回调低吸",
    "wait_for_breakout": "等突破确认",
    "hold_watch": "持有观察",
    "reduce": "建议减仓",
    "sell": "建议卖出",
    "avoid": "建议规避",
}


def _next_trade_date(value: Optional[date]) -> str:
    base = value or date.today()
    candidate = base + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _target_horizon(raw: Any) -> str:
    value = str(raw or "D3").upper().replace(" ", "")
    if value in {"1D", "D1"}:
        return "D1"
    if value in {"2D", "D2"}:
        return "D2"
    if value in {"3D", "D3"}:
        return "D3"
    return "D5"


def _confidence_label(score: float) -> str:
    if score >= 72:
        return "high"
    if score >= 52:
        return "medium"
    return "low"


def _risk_summary(level: str, score: Optional[float]) -> str:
    label = {"low": "偏低", "medium": "中等", "high": "偏高", "extreme": "很高"}.get(level, "中等")
    if score is None:
        return f"当前风险{label}，缺少完整风险评分，仓位需要保守。"
    return f"当前风险{label}，风险评分约{score:.0f}/100，必须按计划价位和仓位执行。"


def _position_max_pct(trade_decision: dict[str, Any], risk_level: str, category: str) -> int:
    if category in {"avoid", "sell"}:
        return 0
    position = trade_decision.get("suggested_position_pct") or {}
    high = _to_float(position.get("max")) if isinstance(position, dict) else None
    if high is None:
        high = {"low": 0.2, "medium": 0.14, "high": 0.08, "extreme": 0.0}.get(risk_level, 0.1)
    return int(round(max(0.0, min(high, 0.3)) * 100))


def _decide_action_category(
    trade_decision: dict[str, Any],
    price_plan: dict[str, Any],
    current_price: Optional[float],
    stats: dict[str, Optional[float]],
) -> str:
    signal = str(trade_decision.get("signal") or "hold")
    risk_level = str(trade_decision.get("risk_level") or "medium")
    confidence = _to_float(trade_decision.get("confidence")) or 0.0
    risk_score = _to_float(trade_decision.get("risk_score"))
    expected_return = _to_float(trade_decision.get("expected_return"))
    do_not_chase = _to_float(price_plan.get("doNotChaseAbove"))
    buy_range = price_plan.get("suggestedBuyRange") or {}
    buy_min = _to_float(buy_range.get("min")) if isinstance(buy_range, dict) else None
    buy_max = _to_float(buy_range.get("max")) if isinstance(buy_range, dict) else None
    recent_high = stats.get("recent_high")

    if current_price is None:
        return "hold_watch"
    if risk_level == "extreme" or (risk_score is not None and risk_score >= 82):
        return "avoid"
    if signal == "strong_sell":
        return "sell"
    if signal == "sell":
        return "reduce"
    if risk_level == "high" and signal not in {"strong_buy", "buy"}:
        return "avoid"
    if buy_min is not None and buy_max is not None and buy_min <= current_price <= buy_max and confidence >= 0.55:
        return "executable_now"
    if expected_return is not None and expected_return > 0 and recent_high and current_price >= recent_high * 0.985:
        return "wait_for_breakout"
    if expected_return is not None and expected_return > 0 and do_not_chase is not None and current_price <= do_not_chase:
        return "wait_for_pullback"
    if signal in {"strong_buy", "buy"}:
        return "wait_for_pullback"
    return "hold_watch"


def _round_range(value: Optional[dict[str, Any]]) -> Optional[list[float]]:
    if not isinstance(value, dict):
        return None
    low = _to_float(value.get("min"))
    high = _to_float(value.get("max"))
    if low is None or high is None:
        return None
    return [_round(low) or 0.0, _round(high) or 0.0]


def _fmt_price(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "计划价"


def _plain_summary(category: str, price_plan: dict[str, Any]) -> str:
    buy_range = _round_range(price_plan.get("suggestedBuyRange"))
    chase = _to_float(price_plan.get("doNotChaseAbove"))
    breakout = _round(chase * 1.01, 2) if chase is not None else None
    stop = _to_float(price_plan.get("stopLossPrice"))
    target = _to_float(price_plan.get("takeProfitPrice1"))
    if category == "executable_now" and buy_range:
        return f"当前落在计划区间 {buy_range[0]:.2f} - {buy_range[1]:.2f}，只适合小仓试探，跌破 {_fmt_price(stop)} 必须取消或止损。"
    if category == "wait_for_pullback" and buy_range:
        return f"当前不追高，若回调到 {buy_range[0]:.2f} - {buy_range[1]:.2f} 且未放量下跌，可小仓试探。"
    if category == "wait_for_breakout":
        return f"先等突破确认，若放量站上 {_fmt_price(breakout)} 再考虑跟随；高于 {_fmt_price(chase)} 不盲目追。"
    if category == "reduce":
        return f"已有持仓优先减仓观察，反弹接近 {_fmt_price(target)} 可分批处理，跌破 {_fmt_price(stop)} 需严格止损。"
    if category == "sell":
        return f"短线信号偏弱，已有持仓优先卖出或退出计划，不新增买入。"
    if category == "avoid":
        return "当前风险或证据不足，不做新增买入计划；只有风险评分下降、资金和价格重新转强后再评估。"
    return f"以持有观察或等待为主，只有出现计划内价位和确认条件才行动，跌破 {_fmt_price(stop)} 则计划失效。"


def _impact_from_stance(stance: Any) -> str:
    value = str(stance or "neutral").lower()
    if value in {"support", "positive", "buy", "strong_buy", "low"}:
        return "positive"
    if value in {"risk", "negative", "sell", "strong_sell", "high", "extreme"}:
        return "negative"
    return "neutral"


def _reason_type(key: str) -> str:
    return {
        "priceForecast": "price_prediction",
        "technicalTiming": "technical",
        "newsIntelligence": "news",
        "macroPolicy": "macro_policy",
        "companyFundamental": "company_fundamental",
        "bigMoney": "big_money",
        "riskControl": "risk",
    }.get(key, "risk")


def _reasons_from_agent_views(agent_views: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    order = ["priceForecast", "technicalTiming", "bigMoney", "newsIntelligence", "macroPolicy", "companyFundamental", "riskControl"]
    for key in order:
        view = agent_views.get(key)
        if not isinstance(view, dict):
            continue
        points = [point for point in (view.get("points") or []) if point]
        if not points:
            continue
        reasons.append({
            "type": _reason_type(key),
            "title": view.get("title") or key,
            "plainText": points[0],
            "impact": _impact_from_stance(view.get("stance")),
        })
    return reasons[:7]


def _build_plans(
    category: str,
    price_plan: dict[str, Any],
    trade_decision: dict[str, Any],
    risk_level: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    buy_range = _round_range(price_plan.get("suggestedBuyRange"))
    do_not_chase = _to_float(price_plan.get("doNotChaseAbove"))
    breakout = _round(do_not_chase * 1.01, 2) if do_not_chase is not None else None
    stop = _to_float(price_plan.get("stopLossPrice"))
    take1 = _to_float(price_plan.get("takeProfitPrice1"))
    take2 = _to_float(price_plan.get("takeProfitPrice2"))
    max_position = _position_max_pct(trade_decision, risk_level, category)

    buy_conditions = []
    if category == "executable_now" and buy_range:
        buy_conditions.append(f"价格仍在 {buy_range[0]:.2f} - {buy_range[1]:.2f} 计划区间内。")
    elif buy_range:
        buy_conditions.append(f"回调到 {buy_range[0]:.2f} - {buy_range[1]:.2f}，且不是放量长阴下跌。")
    if breakout is not None:
        buy_conditions.append(f"若没有回调，需放量突破 {breakout:.2f} 后再考虑跟随。")
    buy_conditions.append("单笔仓位不超过计划上限，先小仓验证。")

    cancel_buy_conditions = []
    if do_not_chase is not None:
        cancel_buy_conditions.append(f"高开或快速拉升超过 {do_not_chase:.2f}，取消追高买入。")
    if stop is not None:
        cancel_buy_conditions.append(f"跌破 {stop:.2f} 或放量跌破支撑，取消本次买入计划。")
    cancel_buy_conditions.append("新闻、资金或模型信心明显转弱时不执行。")

    if category in {"avoid", "sell"}:
        buy_conditions = ["当前不新增买入，等待风险下降后重新生成计划。"]
        cancel_buy_conditions = ["只要风险等级仍为高位或信号偏弱，就不执行买入。"]

    sell_conditions = []
    if take1 is not None:
        sell_conditions.append(f"触及第一目标 {take1:.2f} 时先考虑分批止盈或上移止损。")
    if take2 is not None:
        sell_conditions.append(f"强势延续到第二目标 {take2:.2f} 附近，不恋战。")
    if stop is not None:
        sell_conditions.append(f"跌破止损 {stop:.2f}，本次短线计划失效。")
    sell_conditions.append("若放量冲高回落或资金持续流出，优先降低仓位。")

    risk_control = [
        f"最大仓位不超过 {max_position}%。",
        f"跌破 {_fmt_price(stop)} 必须取消计划或止损。",
        f"高于 {_fmt_price(do_not_chase)} 不追高。",
        "所有条件只作为模型辅助计划，不代表真实下单。",
    ]
    invalidation = [
        price_plan.get("invalidationCondition") or "价格跌破止损或模型信心下降时计划失效。",
        "出现重大负面新闻、市场系统性风险或关键数据缺失时计划失效。",
    ]

    return (
        {
            "idealBuyRange": buy_range,
            "breakoutBuyAbove": breakout,
            "doNotChaseAbove": _round(do_not_chase),
            "maxPositionPct": max_position,
            "buyConditions": buy_conditions[:4],
            "cancelBuyConditions": cancel_buy_conditions[:4],
        },
        {
            "takeProfitPrice1": _round(take1),
            "takeProfitPrice2": _round(take2),
            "stopLossPrice": _round(stop),
            "reduceBelow": _round(stop * 1.01, 2) if stop is not None else None,
            "sellConditions": sell_conditions[:5],
        },
        risk_control,
        invalidation,
    )


def _build_scenario_plan(category: str, buy_plan: dict[str, Any], sell_plan: dict[str, Any]) -> dict[str, str]:
    buy_range = buy_plan.get("idealBuyRange")
    breakout = buy_plan.get("breakoutBuyAbove")
    chase = buy_plan.get("doNotChaseAbove")
    stop = sell_plan.get("stopLossPrice")
    take1 = sell_plan.get("takeProfitPrice1")
    if category in {"avoid", "sell"}:
        return {
            "ifGapUp": "高开也不追，优先观察是否冲高回落。",
            "ifGapDown": "低开说明风险释放仍未结束，不急于接。",
            "ifPullback": "回调不等于买点，需等风险评分和资金行为改善。",
            "ifBreakout": "突破也只先观察，等连续确认后再重新生成计划。",
            "ifBreakdown": "跌破支撑时继续规避或卖出，不做补仓。",
            "ifSideways": "横盘时等待新信号，不主动扩大仓位。",
        }
    return {
        "ifGapUp": f"若高开超过 {_fmt_price(chase)}，不追；若未超过且回落不破计划区，可继续观察。",
        "ifGapDown": f"若低开但不跌破 {_fmt_price(stop)}，等待企稳；跌破则取消计划。",
        "ifPullback": f"若回调到 {buy_range[0]:.2f} - {buy_range[1]:.2f} 且量能温和，可小仓试探。" if buy_range else "若回调但无计划区间，先等待后端重新生成价位。",
        "ifBreakout": f"若放量突破 {_fmt_price(breakout)}，可按小仓跟随计划执行。",
        "ifBreakdown": f"若跌破 {_fmt_price(stop)}，本次交易剧本失效。",
        "ifSideways": f"若横盘不破止损也不到目标 {_fmt_price(take1)}，以观察为主，不频繁加仓。",
    }


def _build_position_context(inputs: RetailInputs, current_price: Optional[float], sell_plan: dict[str, Any]) -> Optional[dict[str, Any]]:
    position = getattr(inputs, "user_position", None)
    if not position or not getattr(position, "quantity", 0):
        return None
    quantity = int(position.quantity or 0)
    avg_cost = _to_float(getattr(position, "avg_cost", None))
    total_cost = _to_float(getattr(position, "total_cost", None))
    stop_loss = _to_float(sell_plan.get("stopLossPrice"))
    take_profit1 = _to_float(sell_plan.get("takeProfitPrice1"))
    take_profit2 = _to_float(sell_plan.get("takeProfitPrice2"))
    market_value = current_price * quantity if current_price is not None else None
    unrealized = market_value - total_cost if market_value is not None and total_cost is not None else None
    unrealized_pct = unrealized / total_cost * 100 if unrealized is not None and total_cost else None
    cost_to_stop_pct = (stop_loss - avg_cost) / avg_cost * 100 if stop_loss is not None and avg_cost else None
    price_to_stop_pct = (stop_loss - current_price) / current_price * 100 if stop_loss is not None and current_price else None
    price_to_target1_pct = (take_profit1 - current_price) / current_price * 100 if take_profit1 is not None and current_price else None
    holding_days = None
    first_entry = getattr(position, "first_entry_date", None)
    if isinstance(first_entry, date):
        holding_days = max(0, (date.today() - first_entry).days)
    return {
        "isHolding": True,
        "quantity": quantity,
        "avgCost": _round(avg_cost),
        "totalCost": _round(total_cost, 2),
        "marketValue": _round(market_value, 2),
        "unrealizedPnl": _round(unrealized, 2),
        "unrealizedPnlPct": _round(unrealized_pct, 2),
        "realizedPnl": _round(_to_float(getattr(position, "realized_pnl", None)), 2),
        "firstEntryDate": _iso(first_entry),
        "lastTradeDate": _iso(getattr(position, "last_trade_date", None)),
        "holdingDays": holding_days,
        "costToStopPct": _round(cost_to_stop_pct, 2),
        "priceToStopPct": _round(price_to_stop_pct, 2),
        "priceToTarget1Pct": _round(price_to_target1_pct, 2),
        "takeProfitPrice2": _round(take_profit2),
    }


def _build_holding_plan(category: str, buy_plan: dict[str, Any], sell_plan: dict[str, Any], position_context: Optional[dict[str, Any]] = None) -> dict[str, str]:
    buy_range = buy_plan.get("idealBuyRange")
    stop = sell_plan.get("stopLossPrice")
    take1 = sell_plan.get("takeProfitPrice1")
    if position_context and position_context.get("isHolding"):
        avg_cost = position_context.get("avgCost")
        pnl_pct = position_context.get("unrealizedPnlPct")
        cost_text = f"成本 {_fmt_price(avg_cost)}" if avg_cost is not None else "已有成本"
        pnl_text = f"当前浮盈亏 {pnl_pct:+.2f}%" if isinstance(pnl_pct, (int, float)) else "当前浮盈亏待更新"
        if category in {"reduce", "sell", "avoid"}:
            return {
                "ifNotHolding": "未持有不新开仓，等待下一轮重新评估。",
                "ifAlreadyHolding": f"已持有按{cost_text}管理，{pnl_text}；优先减仓或退出，跌破 {_fmt_price(stop)} 不补仓。",
            }
        return {
            "ifNotHolding": f"未持有只在计划买入区 {buy_range[0]:.2f} - {buy_range[1]:.2f} 或突破确认后小仓执行。" if buy_range else "未持有先等待计划价位出现。",
            "ifAlreadyHolding": f"已持有按{cost_text}管理，{pnl_text}；触及 {_fmt_price(take1)} 先分批止盈，跌破 {_fmt_price(stop)} 执行风控，未回到计划区不随意加仓。",
        }
    if category in {"reduce", "sell"}:
        return {
            "ifNotHolding": "未持有就不新开仓，等待下一次更清晰的买点。",
            "ifAlreadyHolding": f"已持有优先降低仓位；反弹接近 {_fmt_price(take1)} 分批处理，跌破 {_fmt_price(stop)} 退出计划。",
        }
    if category == "avoid":
        return {
            "ifNotHolding": "未持有就继续跳过，不因为短线波动临时追入。",
            "ifAlreadyHolding": f"已持有也要从严控制，跌破 {_fmt_price(stop)} 不补仓。",
        }
    return {
        "ifNotHolding": f"未持有只在计划买入区 {buy_range[0]:.2f} - {buy_range[1]:.2f} 或突破确认后小仓执行。" if buy_range else "未持有先等待计划价位出现。",
        "ifAlreadyHolding": f"已持有可继续观察，触及 {_fmt_price(take1)} 先分批处理，跌破 {_fmt_price(stop)} 则执行风控。",
    }


def _model_track_record(inputs: RetailInputs) -> dict[str, Any]:
    accuracy = inputs.model_accuracy
    sample_count = 40 if accuracy is not None else 0
    if accuracy is None:
        summary = "暂无足够历史方向样本，本次计划需要更保守。"
    elif accuracy >= 60:
        summary = f"近窗方向准确率约 {accuracy:.1f}%，模型方向有一定参考价值。"
    else:
        summary = f"近窗方向准确率约 {accuracy:.1f}%，模型方向不稳定，不能重仓依赖。"
    return {
        "sampleCount": sample_count,
        "plainSummary": summary,
        "directionAccuracy": accuracy,
        "mape": None,
        "intervalHitRate": None,
    }


def _build_trade_playbook(inputs: RetailInputs) -> dict[str, Any]:
    prices = inputs.prices or []
    latest_price = prices[0] if prices else None
    current_price = _to_float(getattr(latest_price, "close", None))
    latest_date = getattr(latest_price, "trade_date", None)
    factors = inputs.latest_signal.factors_json if inputs.latest_signal and isinstance(inputs.latest_signal.factors_json, dict) else {}
    trade_decision = build_trade_decision(
        symbol=inputs.symbol,
        signal=inputs.latest_signal,
        prediction=inputs.latest_prediction,
        current_price=current_price,
        factors=factors,
        model_accuracy=inputs.model_accuracy,
    )
    stats = _price_stats(prices)
    provisional_plan = _build_price_plan(current_price, stats, trade_decision, "can_buy")
    category = _decide_action_category(trade_decision, provisional_plan, current_price, stats)
    price_plan = _build_price_plan(current_price, stats, trade_decision, "can_buy" if category in {"executable_now", "wait_for_pullback", "wait_for_breakout"} else "wait")
    risk_level = str(trade_decision.get("risk_level") or "medium")
    risk_score = _to_float(trade_decision.get("risk_score"))
    confidence_raw = _to_float(trade_decision.get("confidence")) or 0.0
    confidence_score = round(confidence_raw * 100 if confidence_raw <= 1 else confidence_raw, 1)
    agent_views = _build_agent_views(inputs, trade_decision, category)
    reasons = _reasons_from_agent_views(agent_views)
    buy_plan, sell_plan, risk_control, invalidation = _build_plans(category, price_plan, trade_decision, risk_level)
    position_context = _build_position_context(inputs, current_price, sell_plan)
    if position_context:
        risk_control = [
            *risk_control[:3],
            f"已有持仓成本 {_fmt_price(position_context.get('avgCost'))}，先按止损/目标处理存量仓位，再考虑新增。",
            *risk_control[3:],
        ][:5]
    expected_return = _to_float(trade_decision.get("expected_return"))
    downside = _to_float(trade_decision.get("expected_downside"))
    profile = inputs.profile
    stock_name = getattr(profile, "company_name", None) or inputs.symbol

    warnings: list[str] = []
    if current_price is None:
        warnings.append("partial_data: 缺少最新价格，价位计划已降级。")
    if inputs.latest_signal is None:
        warnings.append("partial_data: 缺少最新交易信号。")
    if inputs.latest_prediction is None:
        warnings.append("partial_data: 缺少最新价格预测。")
    if inputs.latest_fundflow is None:
        warnings.append("partial_data: 缺少最新资金流样本。")

    playbook = {
        "stockCode": inputs.symbol,
        "stockName": stock_name,
        "asOfDate": _iso(latest_date) or date.today().isoformat(),
        "targetTradeDate": _next_trade_date(latest_date if isinstance(latest_date, date) else None),
        "targetHorizon": _target_horizon(getattr(inputs.latest_prediction, "horizon", None) or trade_decision.get("applicable_horizon")),
        "currentPrice": _round(current_price),
        "actionCategory": category,
        "actionLabel": ACTION_LABELS[category],
        "plainSummary": _plain_summary(category, price_plan),
        "buyPlan": buy_plan,
        "sellPlan": sell_plan,
        "scenarioPlan": _build_scenario_plan(category, buy_plan, sell_plan),
        "holdingPlan": _build_holding_plan(category, buy_plan, sell_plan, position_context),
        "positionContext": position_context or {"isHolding": False},
        "confidence": _confidence_label(confidence_score),
        "confidenceScore": confidence_score,
        "riskLevel": risk_level,
        "riskSummary": _risk_summary(risk_level, risk_score),
        "riskControl": risk_control,
        "reasons": reasons,
        "expectedReturnRange": [round(expected_return * 100 * 0.65, 2), round(expected_return * 100 * 1.35, 2)] if expected_return is not None else None,
        "downsideRiskPct": round(abs(downside) * 100, 2) if downside is not None else None,
        "riskRewardRatio": trade_decision.get("risk_reward_ratio"),
        "invalidationConditions": invalidation,
        "modelTrackRecord": _model_track_record(inputs),
        "dataWarnings": warnings,
        "disclaimer": RETAIL_DISCLAIMER,
    }
    return playbook


def _agent_views_for_response(inputs: RetailInputs, playbook: dict[str, Any]) -> dict[str, Any]:
    factors = inputs.latest_signal.factors_json if inputs.latest_signal and isinstance(inputs.latest_signal.factors_json, dict) else {}
    trade_decision = build_trade_decision(
        symbol=inputs.symbol,
        signal=inputs.latest_signal,
        prediction=inputs.latest_prediction,
        current_price=playbook.get("currentPrice"),
        factors=factors,
        model_accuracy=inputs.model_accuracy,
    )
    raw_views = _build_agent_views(inputs, trade_decision, playbook.get("actionCategory") or "hold_watch")
    return {
        "macroPolicy": raw_views.get("macroPolicy"),
        "companyFundamental": raw_views.get("companyFundamental"),
        "newsSentiment": raw_views.get("newsIntelligence"),
        "technicalTiming": raw_views.get("technicalTiming"),
        "priceForecast": raw_views.get("priceForecast"),
        "capitalFlow": raw_views.get("bigMoney"),
        "bigMoney": raw_views.get("bigMoney"),
        "riskControl": raw_views.get("riskControl"),
    }


def _professional_details(inputs: RetailInputs, playbook: dict[str, Any]) -> dict[str, Any]:
    latest_price = (inputs.prices or [None])[0]
    return {
        "prediction": {
            "predictDate": _iso(getattr(inputs.latest_prediction, "predict_date", None)),
            "targetDate": _iso(getattr(inputs.latest_prediction, "target_date", None)),
            "directionProbUp": _to_float(getattr(inputs.latest_prediction, "direction_prob_up", None)),
            "predictedReturn": _to_float(getattr(inputs.latest_prediction, "predicted_return", None)),
            "confidence": _to_float(getattr(inputs.latest_prediction, "confidence", None)),
        },
        "technicalIndicators": {
            "signalDate": _iso(getattr(inputs.latest_signal, "signal_date", None)),
            "action": getattr(inputs.latest_signal, "action", None),
            "score": _to_float(getattr(inputs.latest_signal, "score", None)),
            "riskScore": _to_float(getattr(inputs.latest_signal, "risk_score", None)),
            "priceStats": _price_stats(inputs.prices or []),
        },
        "news": (inputs.factor_context or {}).get("news") if isinstance(inputs.factor_context, dict) else None,
        "capitalFlow": {
            "tradeDate": _iso(getattr(inputs.latest_fundflow, "trade_date", None)),
            "mainNet": _to_float(getattr(inputs.latest_fundflow, "main_net", None)),
            "mainRatio": _to_float(getattr(inputs.latest_fundflow, "main_ratio", None)),
        },
        "positionContext": playbook.get("positionContext"),
        "historicalEvaluation": playbook.get("modelTrackRecord"),
        "latestPrice": {
            "tradeDate": _iso(getattr(latest_price, "trade_date", None)),
            "open": _to_float(getattr(latest_price, "open", None)),
            "high": _to_float(getattr(latest_price, "high", None)),
            "low": _to_float(getattr(latest_price, "low", None)),
            "close": _to_float(getattr(latest_price, "close", None)),
        },
    }


def build_stock_trade_playbook(session: Session, symbol: str) -> dict[str, Any]:
    """Build the single-stock trade playbook response."""
    inputs = _load_inputs(session, symbol.upper(), include_context=True)
    playbook = _build_trade_playbook(inputs)
    return {
        "playbook": playbook,
        "agentViews": _agent_views_for_response(inputs, playbook),
        "professionalDetails": _professional_details(inputs, playbook),
    }


def _plan_review_from_playbook(playbook: dict[str, Any]) -> dict[str, Any]:
    buy_range = (playbook.get("buyPlan") or {}).get("idealBuyRange")
    sell_plan = playbook.get("sellPlan") or {}
    current_price = _to_float(playbook.get("currentPrice"))
    planned_stop = _to_float(sell_plan.get("stopLossPrice"))
    take1 = _to_float(sell_plan.get("takeProfitPrice1"))
    take2 = _to_float(sell_plan.get("takeProfitPrice2"))
    buy_low = _to_float(buy_range[0]) if isinstance(buy_range, list) and buy_range else None
    buy_high = _to_float(buy_range[1]) if isinstance(buy_range, list) and len(buy_range) > 1 else None
    buy_triggered = current_price is not None and buy_low is not None and buy_high is not None and buy_low <= current_price <= buy_high
    stop_triggered = current_price is not None and planned_stop is not None and current_price <= planned_stop
    take1_triggered = current_price is not None and take1 is not None and current_price >= take1
    take2_triggered = current_price is not None and take2 is not None and current_price >= take2
    if current_price is None:
        result = "invalid_data"
        review = "缺少实际价格，无法复盘计划触发情况。"
    elif take1_triggered or take2_triggered:
        result = "effective"
        review = "计划目标价已触发，说明目标区间有阶段性参考价值。"
    elif stop_triggered:
        result = "failed"
        review = "计划触发止损或失效条件，后续应降低仓位和提高确认要求。"
    elif buy_triggered:
        result = "partially_effective"
        review = "计划买入区被触发，但仍需观察是否到达目标价。"
    else:
        result = "not_triggered"
        review = "计划尚未触发，不能把未成交计划当成失败。"
    return {
        "id": f"review_{playbook.get('stockCode')}_{playbook.get('targetTradeDate')}",
        "stockCode": playbook.get("stockCode"),
        "stockName": playbook.get("stockName"),
        "planDate": playbook.get("asOfDate"),
        "targetTradeDate": playbook.get("targetTradeDate"),
        "originalActionCategory": playbook.get("actionCategory"),
        "plannedBuyRange": buy_range,
        "plannedStopLoss": _round(planned_stop),
        "plannedTakeProfit1": _round(take1),
        "plannedTakeProfit2": _round(take2),
        "actualOpen": current_price,
        "actualHigh": current_price,
        "actualLow": current_price,
        "actualClose": current_price,
        "buyTriggered": buy_triggered,
        "stopLossTriggered": stop_triggered,
        "takeProfit1Triggered": take1_triggered,
        "takeProfit2Triggered": take2_triggered,
        "planResult": result,
        "plainReview": review,
        "lessons": [
            "只复盘计划内触发，不把盘中情绪当作交易理由。",
            "未触发的计划继续等待，不临时追高。",
            "触发止损说明风控有效，下一次要降低仓位或提高确认条件。",
        ],
    }


def _market_summary(playbooks: list[dict[str, Any]]) -> dict[str, Any]:
    if not playbooks:
        return {
            "marketTone": "neutral",
            "plainSummary": "当前没有足够股票样本生成明日交易剧本。",
            "suggestedOverallAction": "wait",
            "suggestedPositionSummary": "空仓或轻仓等待，先补齐数据。",
        }
    risk_count = sum(1 for item in playbooks if item.get("riskLevel") in {"high", "extreme"})
    active_count = sum(1 for item in playbooks if item.get("actionCategory") in {"executable_now", "wait_for_pullback", "wait_for_breakout"})
    if risk_count >= max(1, len(playbooks) // 2):
        return {
            "marketTone": "negative",
            "plainSummary": "明日整体以风险控制为主，高风险样本偏多，不适合追高扩仓。",
            "suggestedOverallAction": "defensive",
            "suggestedPositionSummary": "建议轻仓 10%-30%，只执行计划内低吸或突破确认。",
        }
    if active_count:
        return {
            "marketTone": "mixed",
            "plainSummary": "明日可关注少数计划内机会，但必须按买入区、突破价和止损线执行。",
            "suggestedOverallAction": "selective",
            "suggestedPositionSummary": "建议轻仓到中低仓位 20%-40%，不要满仓押单一方向。",
        }
    return {
        "marketTone": "neutral",
        "plainSummary": "明日以观察和等待为主，只有出现计划内价位才考虑小仓。",
        "suggestedOverallAction": "wait",
        "suggestedPositionSummary": "建议轻仓 10%-20%，保留机动性。",
    }


def build_tomorrow_playbook(session: Session, *, limit: int = 12) -> dict[str, Any]:
    """Build the dashboard tomorrow playbook response."""
    symbols, _source = _load_action_symbols(session, limit)
    playbooks: list[dict[str, Any]] = []
    warnings: list[str] = []
    for symbol in symbols[:limit]:
        try:
            playbooks.append(_build_trade_playbook(_load_inputs(session, symbol.upper(), include_context=False)))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{symbol} 交易剧本生成失败：{str(exc)[:80]}")

    groups = {
        "executableNow": [item for item in playbooks if item.get("actionCategory") == "executable_now"],
        "waitForPullback": [item for item in playbooks if item.get("actionCategory") == "wait_for_pullback"],
        "waitForBreakout": [item for item in playbooks if item.get("actionCategory") == "wait_for_breakout"],
        "holdWatch": [item for item in playbooks if item.get("actionCategory") == "hold_watch"],
        "reduceOrSell": [item for item in playbooks if item.get("actionCategory") in {"reduce", "sell"}],
        "avoid": [item for item in playbooks if item.get("actionCategory") == "avoid"],
    }
    top_focus = sorted(
        playbooks,
        key=lambda item: (item.get("actionCategory") == "executable_now", item.get("confidenceScore") or 0),
        reverse=True,
    )[:5]
    reviews = [_plan_review_from_playbook(item) for item in playbooks[:6]]
    successful = [item for item in reviews if item["planResult"] in {"effective", "partially_effective"}]
    failed = [item for item in reviews if item["planResult"] == "failed"]
    review_summary = {
        "plainSummary": f"最近计划回放中，{len(successful)} 个计划有效或部分有效，{len(failed)} 个触发失败/止损，{sum(1 for item in reviews if item['planResult'] == 'not_triggered')} 个尚未触发。",
        "successfulPlans": [f"{item['stockName']}：{item['plainReview']}" for item in successful[:3]],
        "failedPlans": [f"{item['stockName']}：{item['plainReview']}" for item in failed[:3]],
        "lessons": [
            "只执行计划内价位，未触发就继续等待。",
            "触发止损说明计划失效，不用补仓摊低成本。",
            "复盘重点看买点、目标价、止损是否按条件触发。",
        ],
    }
    first_date = playbooks[0].get("asOfDate") if playbooks else date.today().isoformat()
    first_target = playbooks[0].get("targetTradeDate") if playbooks else _next_trade_date(date.today())
    return {
        "asOfDate": first_date,
        "targetTradeDate": first_target,
        "marketSummary": _market_summary(playbooks),
        **groups,
        "topFocus": top_focus,
        "riskWarnings": warnings + (["当前没有满足立即买入条件的股票。系统仍给出等回调低吸和等突破确认的备选计划。"] if not groups["executableNow"] else []),
        "yesterdayReviewSummary": review_summary,
        "reviews": reviews,
        "disclaimer": RETAIL_DISCLAIMER,
    }