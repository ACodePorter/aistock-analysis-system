"""
数据层：新闻数据加载

复用 NewsArticle 表，聚合新闻情绪、频次等供因子系统使用。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select, and_, func, cast, Date as SADate
from sqlalchemy.orm import Session

from ...core.models import NewsArticle

logger = logging.getLogger(__name__)


def load_news_sentiment(
    session: Session,
    symbol: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """加载单股票新闻情绪聚合数据（按日）

    返回 DataFrame：trade_date, news_count, avg_sentiment, pos_count, neg_count, neutral_count
    """
    # NewsArticle.related_stocks 是 JSONB 数组，使用 @> 操作符匹配
    symbol_filter = NewsArticle.related_stocks.op("@>")(f'["{symbol}"]')

    conditions = [symbol_filter]
    if start_date:
        conditions.append(func.date(NewsArticle.published_at) >= start_date)
    if end_date:
        conditions.append(func.date(NewsArticle.published_at) <= end_date)

    # 按日聚合
    pub_date = func.date(NewsArticle.published_at).label("trade_date")
    stmt = (
        select(
            pub_date,
            func.count(NewsArticle.id).label("news_count"),
            func.avg(NewsArticle.sentiment_score).label("avg_sentiment"),
            func.sum(
                func.cast(NewsArticle.sentiment_type == "positive", SADate).is_(None).op("::int")(0)
            ).label("_placeholder"),
        )
        .where(and_(*conditions))
        .group_by(pub_date)
        .order_by(pub_date)
    )

    # 使用更简洁的原始查询处理条件计数
    from sqlalchemy import case, literal_column
    stmt = (
        select(
            pub_date,
            func.count(NewsArticle.id).label("news_count"),
            func.avg(NewsArticle.sentiment_score).label("avg_sentiment"),
            func.sum(case((NewsArticle.sentiment_type == "positive", 1), else_=0)).label("pos_count"),
            func.sum(case((NewsArticle.sentiment_type == "negative", 1), else_=0)).label("neg_count"),
            func.sum(case((NewsArticle.sentiment_type == "neutral", 1), else_=0)).label("neutral_count"),
        )
        .where(and_(*conditions))
        .group_by(pub_date)
        .order_by(pub_date)
    )

    rows = session.execute(stmt).fetchall()
    cols = ["trade_date", "news_count", "avg_sentiment", "pos_count", "neg_count", "neutral_count"]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows, columns=cols)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for col in cols[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def load_news_events(
    session: Session,
    symbol: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """加载与股票关联的新闻事件明细（供事件驱动分析使用）"""
    symbol_filter = NewsArticle.related_stocks.op("@>")(f'["{symbol}"]')
    conditions = [symbol_filter, NewsArticle.is_duplicate == False]  # noqa: E712
    if start_date:
        conditions.append(func.date(NewsArticle.published_at) >= start_date)
    if end_date:
        conditions.append(func.date(NewsArticle.published_at) <= end_date)

    stmt = (
        select(
            NewsArticle.id,
            NewsArticle.title,
            NewsArticle.published_at,
            NewsArticle.sentiment_type,
            NewsArticle.sentiment_score,
            NewsArticle.category,
            NewsArticle.keywords,
        )
        .where(and_(*conditions))
        .order_by(NewsArticle.published_at.desc())
    )
    rows = session.execute(stmt).fetchall()
    cols = ["article_id", "title", "published_at", "sentiment_type", "sentiment_score", "category", "keywords"]
    if not rows:
        return pd.DataFrame(columns=cols)

    return pd.DataFrame(rows, columns=cols)
