"""Retail-friendly short-term decision aggregation service.

The service translates existing model signals, price history, fund flow and
company profile data into a plain-language, UI-ready contract. It does not
place orders and does not promise outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..core.models import FinancialMetrics, FundFlowDaily, PriceDaily, StockPoolMember, StockProfile, UserPosition, Watchlist
from ..prediction.services.factor_context_service import load_stock_factor_context
from ..prediction.services.trade_decision_service import build_trade_decision
from ..quant_engine.models import QEPrediction, QESignal


RETAIL_DISCLAIMER = "本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。"


@dataclass
class RetailInputs:
    symbol: str
    profile: Any = None
    prices: list[Any] | None = None
    latest_signal: Any = None
    latest_prediction: Any = None
    latest_fundflow: Any = None
    latest_financial: Any = None
    user_position: Any = None
    model_accuracy: Optional[float] = None
    factor_context: dict | None = None


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


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return None


def _percent_label(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "暂无"
    normalized = value * 100 if abs(value) <= 1 else value
    sign = "+" if normalized > 0 else ""
    return f"{sign}{normalized:.{digits}f}%"


def _money_label(value: Optional[float]) -> str:
    if value is None:
        return "暂无"
    abs_value = abs(value)
    sign = "净流入" if value > 0 else "净流出" if value < 0 else "基本持平"
    if abs_value >= 100_000_000:
        return f"{sign}{abs_value / 100_000_000:.2f}亿"
    if abs_value >= 10_000:
        return f"{sign}{abs_value / 10_000:.1f}万"
    return f"{sign}{abs_value:.0f}元"


def _risk_label(level: str) -> str:
    return {"low": "偏低", "medium": "中等", "high": "偏高", "extreme": "很高"}.get(level, "中等")


def _final_action_label(action: str) -> str:
    return {
        "can_buy": "可以小仓试买",
        "small_position_watch": "小仓观察",
        "wait": "暂不建议买入",
        "sell_reduce": "建议减仓或卖出",
        "avoid": "建议规避",
    }.get(action, "暂不建议买入")


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.72:
        return "较高"
    if confidence >= 0.55:
        return "中等"
    return "偏低"


def _latest_price(prices: list[Any]) -> Optional[Any]:
    return prices[0] if prices else None


def _price_stats(prices: list[Any]) -> dict[str, Optional[float]]:
    closes = [_to_float(row.close) for row in prices if _to_float(row.close) is not None]
    highs = [_to_float(row.high) for row in prices if _to_float(row.high) is not None]
    lows = [_to_float(row.low) for row in prices if _to_float(row.low) is not None]
    if not closes:
        return {"ma5": None, "ma20": None, "recent_high": None, "recent_low": None, "volatility": None}
    ordered_closes = list(reversed(closes))
    recent_returns: list[float] = []
    for prev, cur in zip(ordered_closes, ordered_closes[1:]):
        if prev:
            recent_returns.append((cur - prev) / prev)
    avg_abs_move = sum(abs(x) for x in recent_returns[-20:]) / min(len(recent_returns), 20) if recent_returns else 0.025
    return {
        "ma5": sum(closes[:5]) / min(len(closes), 5),
        "ma20": sum(closes[:20]) / min(len(closes), 20),
        "recent_high": max(highs[:20]) if highs else None,
        "recent_low": min(lows[:20]) if lows else None,
        "volatility": max(min(avg_abs_move, 0.09), 0.015),
    }


def _load_model_accuracy(session: Session, symbol: str) -> Optional[float]:
    verified = session.execute(
        select(QEPrediction)
        .where(and_(QEPrediction.symbol == symbol, QEPrediction.actual_direction.isnot(None)))
        .order_by(QEPrediction.predict_date.desc())
        .limit(40)
    ).scalars().all()
    usable = [row for row in verified if row.direction_prob_up is not None]
    if not usable:
        return None
    correct = sum(1 for row in usable if (row.direction_prob_up > 0.5) == (row.actual_direction == 1))
    return round(correct / len(usable) * 100, 1)


def _load_inputs(session: Session, symbol: str, *, include_context: bool = True) -> RetailInputs:
    profile = session.execute(select(StockProfile).where(StockProfile.symbol == symbol)).scalar_one_or_none()
    prices = session.execute(
        select(PriceDaily).where(PriceDaily.symbol == symbol).order_by(PriceDaily.trade_date.desc()).limit(60)
    ).scalars().all()
    latest_signal = session.execute(
        select(QESignal).where(QESignal.symbol == symbol).order_by(QESignal.signal_date.desc()).limit(1)
    ).scalar_one_or_none()
    latest_prediction = session.execute(
        select(QEPrediction).where(QEPrediction.symbol == symbol).order_by(QEPrediction.predict_date.desc()).limit(1)
    ).scalar_one_or_none()
    latest_fundflow = session.execute(
        select(FundFlowDaily).where(FundFlowDaily.symbol == symbol).order_by(FundFlowDaily.trade_date.desc()).limit(1)
    ).scalar_one_or_none()
    latest_financial = session.execute(
        select(FinancialMetrics).where(FinancialMetrics.symbol == symbol).order_by(FinancialMetrics.trade_date.desc()).limit(1)
    ).scalar_one_or_none()
    user_position = session.execute(
        select(UserPosition)
        .where(UserPosition.portfolio_id == "default", UserPosition.symbol == symbol, UserPosition.quantity > 0)
        .limit(1)
    ).scalar_one_or_none()
    factors = latest_signal.factors_json if latest_signal and isinstance(latest_signal.factors_json, dict) else {}
    factor_context = None
    if include_context:
        try:
            factor_context = load_stock_factor_context(session, symbol, factors=factors, window_days=7)
        except Exception:
            factor_context = None
    return RetailInputs(
        symbol=symbol,
        profile=profile,
        prices=list(prices),
        latest_signal=latest_signal,
        latest_prediction=latest_prediction,
        latest_fundflow=latest_fundflow,
        latest_financial=latest_financial,
        user_position=user_position,
        model_accuracy=_load_model_accuracy(session, symbol),
        factor_context=factor_context,
    )


def _build_price_plan(current_price: Optional[float], stats: dict[str, Optional[float]], trade_decision: dict, final_action: str) -> dict[str, Any]:
    if current_price is None or current_price <= 0:
        return {
            "suggestedBuyRange": None,
            "lowAbsorbPrice": None,
            "doNotChaseAbove": None,
            "stopLossPrice": None,
            "takeProfitPrice1": None,
            "takeProfitPrice2": None,
            "invalidationCondition": "缺少有效价格数据，暂不生成价位计划。",
        }

    volatility = stats.get("volatility") or 0.025
    recent_low = stats.get("recent_low")
    recent_high = stats.get("recent_high")
    ma5 = stats.get("ma5")
    ma20 = stats.get("ma20")

    stop_loss = _to_float(trade_decision.get("stop_loss_price"))
    if stop_loss is None:
        stop_loss = min(current_price * (1 - max(volatility * 2.1, 0.045)), recent_low * 0.985 if recent_low else current_price * 0.94)

    take_profit1 = _to_float(trade_decision.get("take_profit_price"))
    expected_return = _to_float(trade_decision.get("expected_return"))
    if take_profit1 is None:
        upside = min(max(expected_return or volatility * 2.4, 0.035), 0.14)
        take_profit1 = current_price * (1 + upside)
    take_profit2 = max(take_profit1 * 1.035, current_price * (1 + min(max((expected_return or 0.05) * 1.55, 0.055), 0.20)))

    chase_ceiling = min(
        current_price * (1 + max(volatility * 1.35, 0.025)),
        recent_high * 1.01 if recent_high else current_price * 1.045,
    )

    can_plan_buy = final_action in {"can_buy", "small_position_watch"}
    if can_plan_buy:
        lower_anchor = min(current_price * (1 - max(volatility * 0.85, 0.012)), ma20 or current_price, ma5 or current_price)
        upper_anchor = min(current_price * (1 + max(volatility * 0.45, 0.008)), chase_ceiling)
        buy_range = {"min": _round(lower_anchor), "max": _round(max(lower_anchor, upper_anchor)), "label": f"{lower_anchor:.2f} - {max(lower_anchor, upper_anchor):.2f}"}
        low_absorb = _round(lower_anchor)
    else:
        buy_range = None
        low_absorb = _round(min(current_price * 0.985, ma20 or current_price)) if final_action == "wait" else None

    return {
        "suggestedBuyRange": buy_range,
        "lowAbsorbPrice": low_absorb,
        "doNotChaseAbove": _round(chase_ceiling),
        "stopLossPrice": _round(stop_loss),
        "takeProfitPrice1": _round(take_profit1),
        "takeProfitPrice2": _round(take_profit2),
        "invalidationCondition": "跌破止损价、模型信心下降，或新闻/资金面继续转弱时，本次短线计划失效。",
    }


def _decide_final_action(trade_decision: dict, current_price: Optional[float], inputs: RetailInputs) -> str:
    signal = str(trade_decision.get("signal") or "hold")
    risk_level = str(trade_decision.get("risk_level") or "medium")
    confidence = _to_float(trade_decision.get("confidence")) or 0.0
    risk_score = _to_float(trade_decision.get("risk_score"))
    expected_return = _to_float(trade_decision.get("expected_return"))
    direction_prob = _to_float(getattr(inputs.latest_prediction, "direction_prob_up", None))

    if current_price is None:
        return "wait"
    if signal in {"sell", "strong_sell"}:
        return "sell_reduce"
    if risk_level == "extreme" or (risk_score is not None and risk_score >= 78):
        return "avoid"
    if risk_level == "high" or (risk_score is not None and risk_score >= 62):
        return "small_position_watch" if signal in {"strong_buy", "buy"} and confidence >= 0.62 else "wait"
    if signal in {"strong_buy", "buy"} and confidence >= 0.58 and (expected_return is None or expected_return > 0.015):
        return "can_buy"
    if direction_prob is not None and direction_prob >= 0.56 and (expected_return is None or expected_return > 0):
        return "small_position_watch"
    return "wait"


def _build_agent_views(inputs: RetailInputs, trade_decision: dict, final_action: str) -> dict[str, Any]:
    profile = inputs.profile
    financial = inputs.latest_financial
    fundflow = inputs.latest_fundflow
    prediction = inputs.latest_prediction
    factor_context = inputs.factor_context or {}
    macro = factor_context.get("macro") if isinstance(factor_context, dict) else {}
    news = factor_context.get("news") if isinstance(factor_context, dict) else {}

    main_net = _to_float(getattr(fundflow, "main_net", None))
    main_ratio = _to_float(getattr(fundflow, "main_ratio", None))
    roe = _to_float(getattr(financial, "roe", None))
    pe = _to_float(getattr(financial, "pe_ttm", None))
    predicted_return = _to_float(getattr(prediction, "predicted_return", None))
    direction_prob = _to_float(getattr(prediction, "direction_prob_up", None))
    risk_score = _to_float(trade_decision.get("risk_score"))

    company_points = []
    if profile and getattr(profile, "business_summary", None):
        company_points.append(str(profile.business_summary)[:90])
    if roe is not None:
        company_points.append(f"ROE约{roe:.1f}%，用于观察公司赚钱效率。")
    if pe is not None:
        company_points.append(f"PE(TTM)约{pe:.1f}倍，估值高低仍需和行业比较。")
    if not company_points:
        company_points.append("公司画像和财务样本不足，当前不把基本面作为主要买入理由。")

    news_points = []
    article_count = news.get("article_count") if isinstance(news, dict) else None
    sentiment_label = news.get("sentiment_label") if isinstance(news, dict) else None
    if article_count:
        news_points.append(f"近7日抓到{article_count}条相关新闻，情绪整体为{sentiment_label or '中性'}。")
    headlines = news.get("headlines") if isinstance(news, dict) else []
    for item in (headlines or [])[:2]:
        title = item.get("title") if isinstance(item, dict) else None
        if title:
            news_points.append(f"最新关注：{title[:42]}")
    if not news_points:
        news_points.append("近窗新闻证据不足，暂不把舆情作为强信号。")

    macro_points = []
    breadth_label = macro.get("breadth_label") if isinstance(macro, dict) else None
    breadth_ratio = _to_float(macro.get("breadth_ratio")) if isinstance(macro, dict) else None
    if breadth_label:
        macro_points.append(f"市场广度为{breadth_label}，上涨占比{_percent_label(breadth_ratio, 0)}。")
    else:
        macro_points.append("宏观/市场广度数据不足，按中性处理。")

    money_points = []
    if main_net is not None:
        money_points.append(f"资金行为显示主力{_money_label(main_net)}。")
    if main_ratio is not None:
        money_points.append(f"主力净占比约{main_ratio:.1f}%，只能作为短线情绪参考。")
    if not money_points:
        money_points.append("暂无可靠主力资金样本，不能判断资金是否持续流入。")

    technical_points = [reason.get("evidence") for reason in trade_decision.get("reasons", [])[:3] if isinstance(reason, dict) and reason.get("evidence")]
    if not technical_points:
        technical_points = ["技术和模型信号不足，默认以等待为主。"]

    forecast_points = []
    if direction_prob is not None:
        forecast_points.append(f"模型上涨概率约{direction_prob * 100:.1f}%。")
    if predicted_return is not None:
        forecast_points.append(f"短线预估收益空间为{_percent_label(predicted_return)}。")
    if inputs.model_accuracy is not None:
        forecast_points.append(f"近窗方向历史准确率约{inputs.model_accuracy:.1f}%，信号需结合风控。")
    if not forecast_points:
        forecast_points.append("预测样本不足，不能依赖单次模型输出。")

    risk_points = []
    if risk_score is not None:
        risk_points.append(f"风险评分{risk_score:.0f}/100，当前风险{_risk_label(str(trade_decision.get('risk_level') or 'medium'))}。")
    if final_action in {"avoid", "wait"}:
        risk_points.append("风险控制优先，因此不把买入作为首选动作。")
    else:
        risk_points.append("即使出现买入信号，也只适合按止损计划控制仓位。")

    return {
        "companyFundamental": {"title": "公司本身", "stance": "support" if len(company_points) > 1 else "neutral", "points": company_points[:3]},
        "macroPolicy": {"title": "政策/大盘", "stance": "neutral", "points": macro_points[:3]},
        "newsIntelligence": {"title": "新闻情绪", "stance": sentiment_label or "neutral", "points": news_points[:3]},
        "bigMoney": {"title": "大资金行为", "stance": "support" if (main_net or 0) > 0 else "risk" if (main_net or 0) < 0 else "neutral", "points": money_points[:3]},
        "technicalTiming": {"title": "技术买卖点", "stance": str(trade_decision.get("signal") or "hold"), "points": technical_points[:3]},
        "priceForecast": {"title": "短线价格预测", "stance": "support" if (predicted_return or 0) > 0 else "neutral", "points": forecast_points[:3]},
        "riskControl": {"title": "风险控制", "stance": str(trade_decision.get("risk_level") or "medium"), "points": risk_points[:3]},
    }


def _plain_conclusion(final_action: str, name: str, risk_level: str, confidence: float) -> str:
    label = _final_action_label(final_action)
    if final_action == "can_buy":
        return f"{name}短线条件较完整，可以按计划小仓试买，但必须预先设好止损。"
    if final_action == "small_position_watch":
        return f"{name}有一定短线线索，但风险或证据还不够扎实，更适合小仓观察。"
    if final_action == "sell_reduce":
        return f"{name}当前模型偏向减仓，已有持仓更应关注止损和反弹减仓点。"
    if final_action == "avoid":
        return f"{name}当前风险{_risk_label(risk_level)}，{label}优先于追求短线机会。"
    return f"{name}当前信心{_confidence_label(confidence)}，暂时等待更清晰的买点。"


def _build_retail_response(inputs: RetailInputs) -> dict[str, Any]:
    prices = inputs.prices or []
    latest_price = _latest_price(prices)
    current_price = _to_float(getattr(latest_price, "close", None))
    factors = inputs.latest_signal.factors_json if inputs.latest_signal and isinstance(inputs.latest_signal.factors_json, dict) else {}
    trade_decision = build_trade_decision(
        symbol=inputs.symbol,
        signal=inputs.latest_signal,
        prediction=inputs.latest_prediction,
        current_price=current_price,
        factors=factors,
        model_accuracy=inputs.model_accuracy,
    )
    final_action = _decide_final_action(trade_decision, current_price, inputs)
    stats = _price_stats(prices)
    price_plan = _build_price_plan(current_price, stats, trade_decision, final_action)
    risk_level = str(trade_decision.get("risk_level") or "medium")
    confidence = _to_float(trade_decision.get("confidence")) or 0.0
    profile = inputs.profile
    name = getattr(profile, "company_name", None) or inputs.symbol
    agent_views = _build_agent_views(inputs, trade_decision, final_action)
    primary_reason = agent_views["technicalTiming"]["points"][0] if agent_views["technicalTiming"]["points"] else "等待更多证据。"

    data_warnings: list[str] = []
    if current_price is None:
        data_warnings.append("缺少最新收盘价，价位计划已降级。")
    if inputs.latest_signal is None and inputs.latest_prediction is None:
        data_warnings.append("缺少最新量化信号和预测，默认按等待处理。")
    if inputs.latest_fundflow is None:
        data_warnings.append("缺少最新资金流数据，大资金判断仅作保守处理。")

    card = {
        "stockCode": inputs.symbol,
        "stockName": name,
        "finalAction": final_action,
        "finalActionLabel": _final_action_label(final_action),
        "plainConclusion": _plain_conclusion(final_action, name, risk_level, confidence),
        "oneSentenceReason": primary_reason,
        "currentPrice": _round(current_price),
        "latestPriceDate": _iso(getattr(latest_price, "trade_date", None)),
        "suggestedBuyRange": price_plan["suggestedBuyRange"],
        "lowAbsorbPrice": price_plan["lowAbsorbPrice"],
        "doNotChaseAbove": price_plan["doNotChaseAbove"],
        "stopLossPrice": price_plan["stopLossPrice"],
        "takeProfitPrice1": price_plan["takeProfitPrice1"],
        "takeProfitPrice2": price_plan["takeProfitPrice2"],
        "suggestedPositionPct": trade_decision.get("suggested_position_pct"),
        "applicableHorizon": trade_decision.get("applicable_horizon") or "1-5个交易日",
        "confidence": round(confidence, 3),
        "confidenceLabel": _confidence_label(confidence),
        "riskLevel": risk_level,
        "riskLabel": _risk_label(risk_level),
        "riskScore": trade_decision.get("risk_score"),
        "invalidationCondition": price_plan["invalidationCondition"],
        "dataWarnings": data_warnings,
        "disclaimer": RETAIL_DISCLAIMER,
    }
    return {
        "symbol": inputs.symbol,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "card": card,
        "agentViews": agent_views,
        "professionalDetails": {
            "tradeDecision": trade_decision,
            "priceStats": {key: _round(value, 4) for key, value in stats.items()},
            "fundflow": {
                "tradeDate": _iso(getattr(inputs.latest_fundflow, "trade_date", None)),
                "mainNet": _to_float(getattr(inputs.latest_fundflow, "main_net", None)),
                "mainRatio": _to_float(getattr(inputs.latest_fundflow, "main_ratio", None)),
            },
            "financial": {
                "tradeDate": _iso(getattr(inputs.latest_financial, "trade_date", None)),
                "peTtm": _to_float(getattr(inputs.latest_financial, "pe_ttm", None)),
                "pb": _to_float(getattr(inputs.latest_financial, "pb", None)),
                "roe": _to_float(getattr(inputs.latest_financial, "roe", None)),
            },
            "prediction": {
                "predictDate": _iso(getattr(inputs.latest_prediction, "predict_date", None)),
                "targetDate": _iso(getattr(inputs.latest_prediction, "target_date", None)),
                "directionProbUp": _to_float(getattr(inputs.latest_prediction, "direction_prob_up", None)),
                "predictedReturn": _to_float(getattr(inputs.latest_prediction, "predicted_return", None)),
                "confidence": _to_float(getattr(inputs.latest_prediction, "confidence", None)),
            },
            "factorContext": inputs.factor_context,
        },
        "disclaimer": RETAIL_DISCLAIMER,
    }


def build_stock_retail_decision(session: Session, symbol: str) -> dict[str, Any]:
    """Build the single-stock retail decision response."""
    normalized = symbol.upper()
    return _build_retail_response(_load_inputs(session, normalized, include_context=True))


def _load_action_symbols(session: Session, limit: int) -> tuple[list[str], str]:
    pinned_stmt = (
        select(Watchlist.symbol)
        .where(and_(Watchlist.status == "active", Watchlist.enabled.is_(True), Watchlist.pinned.is_(True)))
        .order_by(Watchlist.score.desc(), Watchlist.symbol.asc())
        .limit(limit)
    )
    symbols = [row[0] for row in session.execute(pinned_stmt).all()]
    if symbols:
        return symbols, "pinned-watchlist"

    pool_stmt = (
        select(StockPoolMember.symbol)
        .where(StockPoolMember.exit_date.is_(None))
        .order_by(StockPoolMember.last_seen_date.desc(), StockPoolMember.symbol.asc())
        .limit(limit)
    )
    symbols = [row[0] for row in session.execute(pool_stmt).all()]
    return symbols, "stock-pool"


def _candidate_from_response(response: dict[str, Any]) -> dict[str, Any]:
    card = response["card"]
    return {
        "symbol": card["stockCode"],
        "name": card["stockName"],
        "action": card["finalAction"],
        "actionLabel": card["finalActionLabel"],
        "currentPrice": card["currentPrice"],
        "suggestedBuyRange": card["suggestedBuyRange"],
        "doNotChaseAbove": card["doNotChaseAbove"],
        "stopLossPrice": card["stopLossPrice"],
        "takeProfitPrice1": card["takeProfitPrice1"],
        "riskLevel": card["riskLevel"],
        "riskLabel": card["riskLabel"],
        "confidence": card["confidence"],
        "oneSentenceReason": card["oneSentenceReason"],
        "plainConclusion": card["plainConclusion"],
    }


def build_tomorrow_retail_actions(session: Session, *, limit: int = 12) -> dict[str, Any]:
    """Build the dashboard retail action list response."""
    symbols, source = _load_action_symbols(session, limit)
    responses: list[dict[str, Any]] = []
    for symbol in symbols[:limit]:
        try:
            responses.append(_build_retail_response(_load_inputs(session, symbol.upper(), include_context=False)))
        except Exception:
            continue

    candidates = [_candidate_from_response(item) for item in responses]
    buy = [item for item in candidates if item["action"] == "can_buy"]
    watch = [item for item in candidates if item["action"] in {"small_position_watch", "wait"}]
    sell = [item for item in candidates if item["action"] == "sell_reduce"]
    avoid = [item for item in candidates if item["action"] == "avoid"]

    if buy:
        strategy = "明日优先看低吸计划，不追高；买入候选也要严格按止损执行。"
    elif watch:
        strategy = "明日以观察和等待回落为主，只有出现计划内价位才考虑小仓。"
    else:
        strategy = "明日风险控制优先，暂不主动扩大战线。"

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "marketSummary": "当前清单基于自选/股票池的最新模型、价格、资金和风险数据生成。",
        "tomorrowStrategy": strategy,
        "buyCandidates": sorted(buy, key=lambda x: x.get("confidence") or 0, reverse=True),
        "watchCandidates": sorted(watch, key=lambda x: x.get("confidence") or 0, reverse=True),
        "sellCandidates": sorted(sell, key=lambda x: x.get("confidence") or 0, reverse=True),
        "avoidCandidates": sorted(avoid, key=lambda x: x.get("confidence") or 0, reverse=True),
        "dataHealth": {
            "requestedCount": len(symbols[:limit]),
            "returnedCount": len(candidates),
            "buyCount": len(buy),
            "watchCount": len(watch),
            "sellCount": len(sell),
            "avoidCount": len(avoid),
            "warnings": [] if candidates else ["暂无可生成明日操作清单的股票样本。"],
        },
        "disclaimer": RETAIL_DISCLAIMER,
    }