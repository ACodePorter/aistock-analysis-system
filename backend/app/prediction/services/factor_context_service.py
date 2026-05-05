"""新闻、宏观与量化因子解释上下文。

当前版本只读现有表与已有量化因子，不新增表结构，也不改变模型训练输入。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ...core.models import NewsArticle, PriceDaily
from ...quant_engine.data_layer.macro_data import load_market_breadth


FACTOR_LABELS = {
    "direction_prob_score": "方向概率",
    "expected_return_score": "预期收益",
    "risk_penalty_score": "风险惩罚",
    "momentum_score": "技术动量",
    "fund_flow_score": "资金流",
    "sentiment_score": "新闻情绪",
    "technical_score": "技术面",
    "volume_score": "量能",
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


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _sentiment_label(score: Optional[float]) -> str:
    if score is None:
        return "未知"
    if score >= 0.25:
        return "偏正面"
    if score <= -0.25:
        return "偏负面"
    return "中性"


def _factor_label(value: Optional[float], high_positive: bool = True) -> str:
    if value is None:
        return "未知"
    normalized = value / 100 if value > 1 else value
    if high_positive:
        if normalized >= 0.65:
            return "正向"
        if normalized <= 0.35:
            return "偏弱"
    else:
        if normalized >= 0.65:
            return "压力"
        if normalized <= 0.35:
            return "低压"
    return "中性"


def build_news_context(symbol: str, articles: list[Any], window_days: int = 7) -> dict:
    scores = [_to_float(getattr(a, "sentiment_score", None)) for a in articles]
    scores = [s for s in scores if s is not None]
    avg_sentiment = round(sum(scores) / len(scores), 3) if scores else None
    sentiment_counts = Counter((getattr(a, "sentiment_type", None) or "unknown") for a in articles)
    category_counts = Counter((getattr(a, "category", None) or "未分类") for a in articles)
    keyword_counts: Counter[str] = Counter()
    headlines = []

    for article in articles[:5]:
        keywords = getattr(article, "keywords", None) or []
        if isinstance(keywords, list):
            keyword_counts.update(str(k) for k in keywords[:6] if k)
        headlines.append({
            "title": getattr(article, "title", "") or "",
            "published_at": _iso(getattr(article, "published_at", None)),
            "sentiment_type": getattr(article, "sentiment_type", None),
            "sentiment_score": _to_float(getattr(article, "sentiment_score", None)),
            "category": getattr(article, "category", None),
        })

    latest_at = max((getattr(a, "published_at", None) for a in articles if getattr(a, "published_at", None)), default=None)
    return {
        "symbol": symbol,
        "window_days": window_days,
        "article_count": len(articles),
        "avg_sentiment": avg_sentiment,
        "sentiment_label": _sentiment_label(avg_sentiment),
        "positive_count": int(sentiment_counts.get("positive", 0)),
        "negative_count": int(sentiment_counts.get("negative", 0)),
        "neutral_count": int(sentiment_counts.get("neutral", 0)),
        "latest_published_at": _iso(latest_at),
        "top_categories": [{"category": k, "count": v} for k, v in category_counts.most_common(5)],
        "top_keywords": [{"keyword": k, "count": v} for k, v in keyword_counts.most_common(8)],
        "headlines": headlines,
    }


def build_macro_context(market_breadth: Optional[dict], trade_date: Optional[date]) -> dict:
    market_breadth = market_breadth or {}
    breadth_ratio = _to_float(market_breadth.get("breadth_ratio"))
    avg_pct_chg = _to_float(market_breadth.get("avg_pct_chg"))
    if breadth_ratio is None:
        label = "未知"
    elif breadth_ratio >= 0.58:
        label = "市场广度偏强"
    elif breadth_ratio <= 0.42:
        label = "市场广度偏弱"
    else:
        label = "市场广度中性"
    return {
        "trade_date": trade_date.isoformat() if trade_date else None,
        "breadth_label": label,
        "breadth_ratio": round(breadth_ratio, 3) if breadth_ratio is not None else None,
        "avg_pct_chg": round(avg_pct_chg, 3) if avg_pct_chg is not None else None,
        "up_count": int(market_breadth.get("up_count") or 0),
        "down_count": int(market_breadth.get("down_count") or 0),
        "flat_count": int(market_breadth.get("flat_count") or 0),
        "total": int(market_breadth.get("total") or 0),
    }


def build_quant_factor_context(factors: Optional[dict]) -> list[dict]:
    items = []
    for key, raw in (factors or {}).items():
        value = _to_float(raw)
        if value is None:
            continue
        high_positive = key != "risk_penalty_score"
        items.append({
            "key": key,
            "label": FACTOR_LABELS.get(key, key),
            "value": round(value, 4),
            "normalized": round(value / 100 if value > 1 else value, 4),
            "impact": _factor_label(value, high_positive=high_positive),
        })
    items.sort(key=lambda item: abs(float(item["normalized"]) - 0.5), reverse=True)
    return items[:8]


def build_factor_context(
    symbol: str,
    *,
    news: dict,
    macro: dict,
    quant_factors: list[dict],
) -> dict:
    summary = []
    warnings = []
    if news.get("article_count", 0) > 0:
        summary.append(f"近{news.get('window_days')}日新闻 {news['article_count']} 条，情绪{news.get('sentiment_label')}。")
    else:
        warnings.append("近窗暂无关联新闻，新闻因子解释可信度较低。")
    if macro.get("total", 0) > 0:
        summary.append(f"{macro.get('trade_date') or '最近交易日'} {macro.get('breadth_label')}，上涨家数占比 {((macro.get('breadth_ratio') or 0) * 100):.1f}%。")
    else:
        warnings.append("暂无市场广度数据，宏观/市场环境解释暂不完整。")
    strong_factors = [f for f in quant_factors if f.get("impact") in {"正向", "压力", "偏弱"}]
    if strong_factors:
        summary.append("主要量化因子：" + "、".join(f"{f['label']}={f['impact']}" for f in strong_factors[:3]) + "。")
    return {
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "news": news,
        "macro": macro,
        "quant_factors": quant_factors,
        "summary": summary,
        "warnings": warnings,
        "disclaimer": "因子解释仅用于辅助理解模型输出，不构成投资建议。",
    }


def load_stock_factor_context(
    session: Session,
    symbol: str,
    *,
    factors: Optional[dict] = None,
    window_days: int = 7,
) -> dict:
    end_date = date.today()
    start_date = end_date - timedelta(days=window_days)
    symbol_filter = NewsArticle.related_stocks.op("@>")(f'["{symbol}"]')
    articles = list(session.execute(
        select(NewsArticle)
        .where(
            and_(
                symbol_filter,
                NewsArticle.is_duplicate == False,  # noqa: E712
                func.date(NewsArticle.published_at) >= start_date,
            )
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(50)
    ).scalars().all())

    latest_price_date = session.execute(
        select(PriceDaily.trade_date)
        .order_by(PriceDaily.trade_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_price_date = _to_date(latest_price_date)
    market_breadth = load_market_breadth(session, latest_price_date) if latest_price_date else None
    return build_factor_context(
        symbol,
        news=build_news_context(symbol, articles, window_days=window_days),
        macro=build_macro_context(market_breadth, latest_price_date),
        quant_factors=build_quant_factor_context(factors),
    )