"""
行为因子（Behavioral Factors）

基于换手率、资金流向等市场微观行为构建因子。
输入 DataFrame 需包含 vol, amount, main_net 等列（由 FeaturePipeline 合并）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import register_factor


# ========== 换手率相关 ==========

@register_factor(name="turnover_rate", category="behavioral",
                  description="换手率近似（成交量/流通股，此处使用成交额/收盘价归一化）")
def compute_turnover_rate(df: pd.DataFrame) -> pd.Series:
    """简化换手率：amount / (close * vol) 归一化，实际项目中可对接流通市值"""
    if "amount" in df.columns and "close" in df.columns:
        # 使用 vol / 20日均量作为近似换手率变化
        if "vol" in df.columns:
            avg_vol = df["vol"].rolling(window=20, min_periods=1).mean()
            return (df["vol"] / avg_vol.replace(0, np.nan)).fillna(1)
    return pd.Series(1.0, index=df.index)


@register_factor(name="turnover_change_5d", category="behavioral",
                  description="5日换手率变化率")
def compute_turnover_change(df: pd.DataFrame) -> pd.Series:
    if "vol" not in df.columns:
        return pd.Series(0.0, index=df.index)
    vol_5d = df["vol"].rolling(window=5, min_periods=1).mean()
    vol_20d = df["vol"].rolling(window=20, min_periods=1).mean()
    return ((vol_5d - vol_20d) / vol_20d.replace(0, np.nan)).fillna(0)


# ========== 资金流因子 ==========

@register_factor(name="fund_main_net_norm", category="behavioral",
                  description="主力净流入（标准化：/成交额）")
def compute_fund_main_net_norm(df: pd.DataFrame) -> pd.Series:
    if "main_net" in df.columns and "amount" in df.columns:
        return (df["main_net"] / df["amount"].replace(0, np.nan)).fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="fund_main_net_5d", category="behavioral",
                  description="5日主力净流入累计", params={"window": 5})
def compute_fund_main_net_5d(df: pd.DataFrame, window: int = 5) -> pd.Series:
    if "main_net" in df.columns:
        return df["main_net"].rolling(window=window, min_periods=1).sum().fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="fund_super_net_norm", category="behavioral",
                  description="超大单净流入（标准化）")
def compute_fund_super_net_norm(df: pd.DataFrame) -> pd.Series:
    if "super_net" in df.columns and "amount" in df.columns:
        return (df["super_net"] / df["amount"].replace(0, np.nan)).fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="fund_flow_momentum", category="behavioral",
                  description="资金流动量（3日净流入趋势 vs 10日）")
def compute_fund_flow_momentum(df: pd.DataFrame) -> pd.Series:
    if "main_net" not in df.columns:
        return pd.Series(0.0, index=df.index)
    short = df["main_net"].rolling(window=3, min_periods=1).mean()
    long = df["main_net"].rolling(window=10, min_periods=1).mean()
    denominator = long.abs().replace(0, np.nan)
    return ((short - long) / denominator).fillna(0)


# ========== 量价配合因子 ==========

@register_factor(name="vol_price_corr_10d", category="behavioral",
                  description="10日量价相关系数", params={"window": 10})
def compute_vol_price_corr(df: pd.DataFrame, window: int = 10) -> pd.Series:
    """成交量与价格变动的相关性：高相关 = 量价齐升/齐跌（趋势延续）"""
    if "vol" not in df.columns:
        return pd.Series(0.0, index=df.index)
    ret = df["close"].pct_change()
    return ret.rolling(window=window, min_periods=5).corr(df["vol"]).fillna(0)


@register_factor(name="price_vol_divergence", category="behavioral",
                  description="量价背离指标（价涨量缩或价跌量增）")
def compute_price_vol_divergence(df: pd.DataFrame) -> pd.Series:
    """正值 = 背离（价涨量缩或价跌量增），可能预示反转"""
    if "vol" not in df.columns:
        return pd.Series(0.0, index=df.index)
    price_trend = df["close"].pct_change(5).fillna(0)
    vol_trend = df["vol"].pct_change(5).fillna(0)
    # 价涨量缩 → 正背离；价跌量增 → 负背离
    return (price_trend.clip(lower=0) * (-vol_trend.clip(upper=0))
            + price_trend.clip(upper=0) * vol_trend.clip(lower=0))
