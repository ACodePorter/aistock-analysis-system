"""
数据层：宏观数据加载

加载指数行情（上证/创业板）、宏观指标等。
利用 akshare 获取指数数据，缓存至本地。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 常用 A 股指数代码映射（akshare 格式）
INDEX_CODES = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
    "沪深300": "sh000300",
    "中证500": "sh000905",
}


def load_index_daily(
    index_name: str = "上证指数",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """加载指数日线行情

    Args:
        index_name: 指数名称（参见 INDEX_CODES）
        start_date: 起始日期，格式 YYYYMMDD
        end_date:   截止日期，格式 YYYYMMDD

    Returns:
        DataFrame: date, open, high, low, close, volume, pct_chg
    """
    code = INDEX_CODES.get(index_name)
    if not code:
        logger.error("未知指数名称: %s，可选: %s", index_name, list(INDEX_CODES.keys()))
        return pd.DataFrame()

    try:
        import akshare as ak
        # akshare 获取 A 股指数日线（每日行情）
        df = ak.stock_zh_index_daily(symbol=code)
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={"date": "trade_date"})
        df["trade_date"] = pd.to_datetime(df["trade_date"])

        if start_date:
            df = df[df["trade_date"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["trade_date"] <= pd.to_datetime(end_date)]

        # 计算涨跌幅
        if "close" in df.columns and "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100

        return df.reset_index(drop=True)

    except Exception as e:
        logger.error("加载指数数据失败: index=%s, error=%s", index_name, e)
        return pd.DataFrame()


def load_market_breadth(
    session,
    trade_date: date,
) -> dict:
    """计算市场广度指标（涨跌家数比）

    从 prices_daily 聚合当日涨/跌/平数量。
    """
    from sqlalchemy import select, func, case
    from ...core.models import PriceDaily

    stmt = (
        select(
            func.count(PriceDaily.id).label("total"),
            func.sum(case((PriceDaily.pct_chg > 0, 1), else_=0)).label("up_count"),
            func.sum(case((PriceDaily.pct_chg < 0, 1), else_=0)).label("down_count"),
            func.sum(case((PriceDaily.pct_chg == 0, 1), else_=0)).label("flat_count"),
            func.avg(PriceDaily.pct_chg).label("avg_pct_chg"),
        )
        .where(PriceDaily.trade_date == trade_date)
    )
    row = session.execute(stmt).fetchone()
    if not row or not row.total:
        return {"total": 0, "up_count": 0, "down_count": 0, "flat_count": 0, "avg_pct_chg": 0.0, "breadth_ratio": 0.5}

    total = row.total or 1
    up = row.up_count or 0
    down = row.down_count or 0
    return {
        "total": total,
        "up_count": up,
        "down_count": down,
        "flat_count": row.flat_count or 0,
        "avg_pct_chg": float(row.avg_pct_chg or 0),
        "breadth_ratio": up / total if total > 0 else 0.5,
    }
