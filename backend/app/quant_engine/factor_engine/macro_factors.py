"""
宏观因子（Macro Factors）

基于指数行情、市场广度等生成的宏观环境因子。
输入 DataFrame 需包含 macro_ 前缀列（由 FeaturePipeline 合并）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import register_factor


@register_factor(name="macro_index_ret_1d", category="macro",
                  description="上证指数1日收益率")
def compute_macro_index_ret_1d(df: pd.DataFrame) -> pd.Series:
    if "macro_index_close" in df.columns:
        return df["macro_index_close"].pct_change().fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="macro_index_ret_5d", category="macro",
                  description="上证指数5日累计收益率")
def compute_macro_index_ret_5d(df: pd.DataFrame) -> pd.Series:
    if "macro_index_close" in df.columns:
        return df["macro_index_close"].pct_change(5).fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="macro_index_ma20_diff", category="macro",
                  description="上证指数偏离20日均线幅度")
def compute_macro_index_ma20_diff(df: pd.DataFrame) -> pd.Series:
    if "macro_index_close" not in df.columns:
        return pd.Series(0.0, index=df.index)
    close = df["macro_index_close"]
    ma20 = close.rolling(window=20, min_periods=1).mean()
    return ((close - ma20) / ma20.replace(0, np.nan)).fillna(0)


@register_factor(name="macro_breadth_ratio", category="macro",
                  description="市场广度（涨家占比）")
def compute_macro_breadth(df: pd.DataFrame) -> pd.Series:
    if "macro_breadth_ratio" in df.columns:
        return df["macro_breadth_ratio"].fillna(0.5)
    return pd.Series(0.5, index=df.index)


@register_factor(name="macro_volatility_20d", category="macro",
                  description="上证指数20日波动率")
def compute_macro_volatility(df: pd.DataFrame) -> pd.Series:
    if "macro_index_close" not in df.columns:
        return pd.Series(0.0, index=df.index)
    ret = df["macro_index_close"].pct_change()
    return (ret.rolling(window=20, min_periods=5).std() * np.sqrt(252)).fillna(0)


@register_factor(name="macro_trend_strength", category="macro",
                  description="上证指数趋势强度（5日/20日均线偏离）")
def compute_macro_trend_strength(df: pd.DataFrame) -> pd.Series:
    if "macro_index_close" not in df.columns:
        return pd.Series(0.0, index=df.index)
    close = df["macro_index_close"]
    ma5 = close.rolling(window=5, min_periods=1).mean()
    ma20 = close.rolling(window=20, min_periods=1).mean()
    return ((ma5 - ma20) / ma20.replace(0, np.nan)).fillna(0)
