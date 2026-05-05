"""
新闻因子（News Factors）

基于新闻情绪、频次、事件标记生成量化因子。
输入 DataFrame 需包含新闻聚合列（由 FeaturePipeline 合并）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import register_factor


# ========== 新闻情绪因子 ==========

@register_factor(name="news_sentiment_1d", category="news",
                  description="当日新闻情绪得分（均值）")
def compute_news_sentiment_1d(df: pd.DataFrame) -> pd.Series:
    """直接使用新闻聚合列 avg_sentiment"""
    if "avg_sentiment" in df.columns:
        return df["avg_sentiment"].fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="news_sentiment_3d", category="news",
                  description="3日滚动新闻情绪", params={"window": 3})
def compute_news_sentiment_3d(df: pd.DataFrame, window: int = 3) -> pd.Series:
    if "avg_sentiment" in df.columns:
        return df["avg_sentiment"].rolling(window=window, min_periods=1).mean().fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="news_sentiment_7d", category="news",
                  description="7日滚动新闻情绪", params={"window": 7})
def compute_news_sentiment_7d(df: pd.DataFrame, window: int = 7) -> pd.Series:
    if "avg_sentiment" in df.columns:
        return df["avg_sentiment"].rolling(window=window, min_periods=1).mean().fillna(0)
    return pd.Series(0.0, index=df.index)


# ========== 新闻频次因子 ==========

@register_factor(name="news_volume_1d", category="news",
                  description="当日新闻数量")
def compute_news_volume_1d(df: pd.DataFrame) -> pd.Series:
    if "news_count" in df.columns:
        return df["news_count"].fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="news_volume_5d", category="news",
                  description="5日累计新闻数量", params={"window": 5})
def compute_news_volume_5d(df: pd.DataFrame, window: int = 5) -> pd.Series:
    if "news_count" in df.columns:
        return df["news_count"].rolling(window=window, min_periods=1).sum().fillna(0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="news_volume_spike", category="news",
                  description="新闻量异常突增倍数（相对20日均值）", params={"window": 20})
def compute_news_volume_spike(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """当日新闻量 / 20日均值，>2 视为异常"""
    if "news_count" not in df.columns:
        return pd.Series(1.0, index=df.index)
    avg = df["news_count"].rolling(window=window, min_periods=1).mean()
    return df["news_count"] / avg.replace(0, np.nan).fillna(1)


# ========== 情绪比例因子 ==========

@register_factor(name="news_pos_ratio", category="news",
                  description="正面新闻占比")
def compute_news_pos_ratio(df: pd.DataFrame) -> pd.Series:
    if "pos_count" in df.columns and "news_count" in df.columns:
        total = df["news_count"].replace(0, np.nan)
        return (df["pos_count"] / total).fillna(0.5)
    return pd.Series(0.5, index=df.index)


@register_factor(name="news_neg_ratio", category="news",
                  description="负面新闻占比")
def compute_news_neg_ratio(df: pd.DataFrame) -> pd.Series:
    if "neg_count" in df.columns and "news_count" in df.columns:
        total = df["news_count"].replace(0, np.nan)
        return (df["neg_count"] / total).fillna(0.0)
    return pd.Series(0.0, index=df.index)


@register_factor(name="news_sentiment_momentum", category="news",
                  description="新闻情绪动量（3日-7日均值差）")
def compute_news_sentiment_momentum(df: pd.DataFrame) -> pd.Series:
    """短期情绪 vs 长期情绪的差值，反映情绪趋势变化"""
    if "avg_sentiment" not in df.columns:
        return pd.Series(0.0, index=df.index)
    short = df["avg_sentiment"].rolling(window=3, min_periods=1).mean()
    long = df["avg_sentiment"].rolling(window=7, min_periods=1).mean()
    return (short - long).fillna(0)


# ========== 事件标记因子 ==========

@register_factor(name="has_major_event", category="news",
                  description="是否存在重大事件（基于新闻量突增+强情绪）", data_type="int")
def compute_has_major_event(df: pd.DataFrame) -> pd.Series:
    """重大事件定义：新闻量 > 20日均值×2 且 |情绪| > 0.3"""
    if "news_count" not in df.columns or "avg_sentiment" not in df.columns:
        return pd.Series(0, index=df.index)
    avg_count = df["news_count"].rolling(window=20, min_periods=1).mean()
    volume_spike = df["news_count"] > (avg_count * 2)
    strong_sentiment = df["avg_sentiment"].abs() > 0.3
    return (volume_spike & strong_sentiment).astype(int)
