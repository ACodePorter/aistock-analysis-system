"""
数据层：行情数据加载

从 PostgreSQL（PriceDaily / FundFlowDaily）加载历史行情，
返回 pandas DataFrame 供特征工程和模型训练使用。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ...core.models import PriceDaily, FundFlowDaily, Watchlist

logger = logging.getLogger(__name__)


def load_price_daily(
    session: Session,
    symbol: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """加载单只股票日线行情

    返回 DataFrame，列：trade_date, open, high, low, close, pct_chg, vol, amount
    按 trade_date 升序排列。
    """
    conditions = [PriceDaily.symbol == symbol]
    if start_date:
        conditions.append(PriceDaily.trade_date >= start_date)
    if end_date:
        conditions.append(PriceDaily.trade_date <= end_date)

    stmt = (
        select(
            PriceDaily.trade_date,
            PriceDaily.open,
            PriceDaily.high,
            PriceDaily.low,
            PriceDaily.close,
            PriceDaily.pct_chg,
            PriceDaily.vol,
            PriceDaily.amount,
        )
        .where(and_(*conditions))
        .order_by(PriceDaily.trade_date.asc())
    )
    rows = session.execute(stmt).fetchall()
    if not rows:
        logger.warning("无行情数据: symbol=%s, start=%s, end=%s", symbol, start_date, end_date)
        return pd.DataFrame(columns=["trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount"])

    df = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount"])
    # 确保数值类型
    for col in ["open", "high", "low", "close", "pct_chg", "vol", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def load_fund_flow(
    session: Session,
    symbol: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """加载单只股票资金流向数据"""
    conditions = [FundFlowDaily.symbol == symbol]
    if start_date:
        conditions.append(FundFlowDaily.trade_date >= start_date)
    if end_date:
        conditions.append(FundFlowDaily.trade_date <= end_date)

    stmt = (
        select(
            FundFlowDaily.trade_date,
            FundFlowDaily.main_net,
            FundFlowDaily.main_ratio,
            FundFlowDaily.super_net,
            FundFlowDaily.large_net,
            FundFlowDaily.medium_net,
            FundFlowDaily.small_net,
        )
        .where(and_(*conditions))
        .order_by(FundFlowDaily.trade_date.asc())
    )
    rows = session.execute(stmt).fetchall()
    cols = ["trade_date", "main_net", "main_ratio", "super_net", "large_net", "medium_net", "small_net"]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows, columns=cols)
    for col in cols[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def load_multi_stock_prices(
    session: Session,
    symbols: list[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """批量加载多只股票日线行情（供跨股票分析使用）"""
    conditions = [PriceDaily.symbol.in_(symbols)]
    if start_date:
        conditions.append(PriceDaily.trade_date >= start_date)
    if end_date:
        conditions.append(PriceDaily.trade_date <= end_date)

    stmt = (
        select(
            PriceDaily.symbol,
            PriceDaily.trade_date,
            PriceDaily.open,
            PriceDaily.high,
            PriceDaily.low,
            PriceDaily.close,
            PriceDaily.pct_chg,
            PriceDaily.vol,
            PriceDaily.amount,
        )
        .where(and_(*conditions))
        .order_by(PriceDaily.symbol, PriceDaily.trade_date.asc())
    )
    rows = session.execute(stmt).fetchall()
    cols = ["symbol", "trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount"]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows, columns=cols)
    for col in cols[2:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def get_watchlist_symbols(session: Session, pinned_only: bool = False) -> list[str]:
    """获取观察列表中的活跃股票代码"""
    conditions = [Watchlist.status == "active"]
    if pinned_only:
        conditions.append(Watchlist.pinned == True)  # noqa: E712
    stmt = select(Watchlist.symbol).where(and_(*conditions))
    rows = session.execute(stmt).scalars().all()
    return list(rows)
