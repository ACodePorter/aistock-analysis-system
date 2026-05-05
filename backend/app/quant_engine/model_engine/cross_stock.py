"""
跨股票关联建模（Cross-Stock Learning）

实现：
- 行业 embedding（同行业股票共享特征）
- 相似股票影响分析
- 板块联动建模

使用 StockProfile 中的行业信息构建行业分组特征。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ...core.models import StockProfile, PriceDaily

logger = logging.getLogger(__name__)


class CrossStockAnalyzer:
    """跨股票关联分析器"""

    def __init__(self, session: Session):
        self.session = session

    def get_industry_peers(self, symbol: str, limit: int = 20) -> list[str]:
        """获取同行业股票列表"""
        # 查找当前股票的行业
        profile = self.session.execute(
            select(StockProfile.industry).where(StockProfile.symbol == symbol)
        ).scalar_one_or_none()

        if not profile:
            return []

        # 查找同行业的其他股票
        peers = self.session.execute(
            select(StockProfile.symbol)
            .where(
                and_(
                    StockProfile.industry == profile,
                    StockProfile.symbol != symbol,
                    StockProfile.is_valid == True,  # noqa: E712
                )
            )
            .limit(limit)
        ).scalars().all()

        return list(peers)

    def compute_industry_features(
        self,
        symbol: str,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算行业关联特征

        为目标股票的每日数据添加行业维度特征：
        - 行业平均涨跌幅
        - 行业内排名百分位
        - 行业动量
        """
        peers = self.get_industry_peers(symbol)
        if not peers:
            df["industry_avg_ret"] = 0.0
            df["industry_rank_pct"] = 0.5
            df["industry_momentum_5d"] = 0.0
            return df

        # 加载同行业股票的行情
        from ..data_layer.market_data import load_multi_stock_prices
        trade_dates = df["trade_date"].tolist()
        if not trade_dates:
            return df

        min_date = min(trade_dates).date() if hasattr(min(trade_dates), 'date') else min(trade_dates)
        max_date = max(trade_dates).date() if hasattr(max(trade_dates), 'date') else max(trade_dates)

        all_symbols = peers + [symbol]
        peer_df = load_multi_stock_prices(self.session, all_symbols, min_date, max_date)
        if peer_df.empty:
            df["industry_avg_ret"] = 0.0
            df["industry_rank_pct"] = 0.5
            df["industry_momentum_5d"] = 0.0
            return df

        # 计算每日行业平均涨跌幅
        daily_ret = peer_df.pivot_table(
            values="pct_chg", index="trade_date", columns="symbol", aggfunc="first"
        )

        # 行业均值（排除自身）
        peer_cols = [c for c in daily_ret.columns if c != symbol]
        if peer_cols:
            industry_avg = daily_ret[peer_cols].mean(axis=1)
        else:
            industry_avg = pd.Series(0.0, index=daily_ret.index)

        # 行业内排名百分位
        rank_pct = daily_ret.rank(axis=1, pct=True)
        symbol_rank = rank_pct.get(symbol, pd.Series(0.5, index=daily_ret.index))

        # 合并到主 DataFrame
        industry_feat = pd.DataFrame({
            "trade_date": industry_avg.index,
            "industry_avg_ret": industry_avg.values,
            "industry_rank_pct": symbol_rank.values if not symbol_rank.empty else 0.5,
        })
        industry_feat["trade_date"] = pd.to_datetime(industry_feat["trade_date"])

        # 行业动量（5日）
        industry_feat["industry_momentum_5d"] = industry_feat["industry_avg_ret"].rolling(5, min_periods=1).sum()

        df = df.merge(industry_feat, on="trade_date", how="left")
        df["industry_avg_ret"] = df["industry_avg_ret"].fillna(0)
        df["industry_rank_pct"] = df["industry_rank_pct"].fillna(0.5)
        df["industry_momentum_5d"] = df["industry_momentum_5d"].fillna(0)

        return df

    def compute_sector_correlation(
        self,
        symbol: str,
        window: int = 20,
    ) -> float:
        """计算股票与行业平均收益率的相关系数"""
        peers = self.get_industry_peers(symbol, limit=10)
        if not peers:
            return 0.0

        from datetime import date, timedelta
        from ..data_layer.market_data import load_price_daily, load_multi_stock_prices

        end = date.today()
        start = end - timedelta(days=window * 2)

        stock_df = load_price_daily(self.session, symbol, start, end)
        peer_df = load_multi_stock_prices(self.session, peers, start, end)

        if stock_df.empty or peer_df.empty:
            return 0.0

        stock_ret = stock_df.set_index("trade_date")["pct_chg"]
        peer_avg = peer_df.groupby("trade_date")["pct_chg"].mean()

        combined = pd.DataFrame({"stock": stock_ret, "industry": peer_avg}).dropna()
        if len(combined) < 5:
            return 0.0

        return float(combined["stock"].corr(combined["industry"]))
