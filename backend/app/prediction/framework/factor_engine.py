"""
综合因子工程引擎

四大因子来源：
1. 技术指标因子（MA/EMA/MACD/RSI/BOLL/ATR/ADX/OBV/CCI/KDJ/Williams %R 等）
2. 市场因子（大盘指数收益、指数偏离、市场波动率）
3. 新闻/情绪因子（情绪均值、情绪动量、新闻量异动、正负面比例）
4. 宏观因子（指数趋势强度、市场宽度）

衍生特征自动生成：
- 滞后项（lag 1~5）
- 滑动窗口统计（mean / std / skew / kurt / min / max）
- 关键因子的交叉比率

所有因子均为 scale-free（比率/差值/标准化），避免目标泄露。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ===================================================================
# 因子分类定义
# ===================================================================

@dataclass
class FactorGroup:
    category: str
    names: List[str] = field(default_factory=list)


# ===================================================================
# 1. 技术指标因子
# ===================================================================

def compute_technical_factors(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """计算全套技术指标因子（约 55 个）"""
    df = df.copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    vol = df["vol"].astype(float) if "vol" in df.columns else pd.Series(1.0, index=df.index)
    opn = df["open"].astype(float) if "open" in df.columns else close

    factors: List[str] = []

    # --- 多周期收益率 ---
    for p in (1, 2, 3, 5, 10, 20, 60):
        col = f"ret_{p}d"
        df[col] = close.pct_change(p)
        factors.append(col)

    # --- 均线偏离率 ---
    for w in (5, 10, 20, 60, 120):
        ma = close.rolling(w, min_periods=w).mean()
        col = f"ma{w}_bias"
        df[col] = (close - ma) / (ma + 1e-9)
        factors.append(col)

    # --- EMA 偏离 ---
    for span in (5, 12, 26, 50):
        ema = close.ewm(span=span, adjust=False).mean()
        col = f"ema{span}_bias"
        df[col] = (close - ema) / (ema + 1e-9)
        factors.append(col)

    # --- MACD ---
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_dif = ema12 - ema26
    macd_dea = macd_dif.ewm(span=9, adjust=False).mean()
    macd_hist = macd_dif - macd_dea
    df["macd_dif_norm"] = macd_dif / (close + 1e-9)
    df["macd_dea_norm"] = macd_dea / (close + 1e-9)
    df["macd_hist_norm"] = macd_hist / (close + 1e-9)
    factors.extend(["macd_dif_norm", "macd_dea_norm", "macd_hist_norm"])

    # --- RSI ---
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss_s = (-delta).where(delta < 0, 0.0)
    for period in (6, 14, 24):
        avg_gain = gain.rolling(period, min_periods=period).mean()
        avg_loss = loss_s.rolling(period, min_periods=period).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        col = f"rsi_{period}"
        df[col] = 100.0 - 100.0 / (1.0 + rs)
        factors.append(col)

    # --- 布林带 ---
    bb_ma = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std()
    df["bb_width"] = 2.0 * bb_std / (bb_ma + 1e-9)
    df["bb_position"] = (close - (bb_ma - 2 * bb_std)) / (4 * bb_std + 1e-9)
    factors.extend(["bb_width", "bb_position"])

    # --- ATR ---
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=14).mean()
    df["atr_pct"] = atr14 / (close + 1e-9)
    factors.append("atr_pct")

    # --- ADX（平均趋向指数）---
    plus_dm = (high - high.shift(1)).clip(lower=0)
    minus_dm = (low.shift(1) - low).clip(lower=0)
    mask = plus_dm > minus_dm
    plus_dm = plus_dm.where(mask, 0)
    minus_dm = minus_dm.where(~mask, 0)
    smooth_tr = tr.rolling(14, min_periods=14).sum()
    plus_di = 100.0 * plus_dm.rolling(14, min_periods=14).sum() / (smooth_tr + 1e-9)
    minus_di = 100.0 * minus_dm.rolling(14, min_periods=14).sum() / (smooth_tr + 1e-9)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    df["adx"] = dx.rolling(14, min_periods=14).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    factors.extend(["adx", "plus_di", "minus_di"])

    # --- CCI ---
    tp = (high + low + close) / 3.0
    tp_ma = tp.rolling(20, min_periods=20).mean()
    tp_md = tp.rolling(20, min_periods=20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci"] = (tp - tp_ma) / (0.015 * tp_md + 1e-9)
    factors.append("cci")

    # --- KDJ ---
    low_n = low.rolling(9, min_periods=9).min()
    high_n = high.rolling(9, min_periods=9).max()
    rsv = 100.0 * (close - low_n) / (high_n - low_n + 1e-9)
    df["kdj_k"] = rsv.ewm(com=2, adjust=False).mean()
    df["kdj_d"] = df["kdj_k"].ewm(com=2, adjust=False).mean()
    df["kdj_j"] = 3.0 * df["kdj_k"] - 2.0 * df["kdj_d"]
    factors.extend(["kdj_k", "kdj_d", "kdj_j"])

    # --- Williams %R ---
    df["williams_r"] = -100.0 * (high_n - close) / (high_n - low_n + 1e-9)
    factors.append("williams_r")

    # --- OBV 变化率（scale-free） ---
    obv_sign = np.sign(close.diff())
    obv = (vol * obv_sign).cumsum()
    obv_ma = obv.rolling(20, min_periods=20).mean()
    df["obv_bias"] = (obv - obv_ma) / (obv_ma.abs() + 1e-9)
    factors.append("obv_bias")

    # --- 波动率（多周期） ---
    for w in (5, 10, 20, 60):
        col = f"volatility_{w}d"
        df[col] = df["ret_1d"].rolling(w, min_periods=w).std()
        factors.append(col)

    # --- 下行波动率 ---
    neg_ret = df["ret_1d"].where(df["ret_1d"] < 0, 0)
    df["downside_vol_20d"] = neg_ret.rolling(20, min_periods=20).std()
    factors.append("downside_vol_20d")

    # --- 最大回撤 ---
    roll_max = close.rolling(60, min_periods=20).max()
    df["max_drawdown_60d"] = (close - roll_max) / (roll_max + 1e-9)
    factors.append("max_drawdown_60d")

    # --- 成交量因子 ---
    for w in (5, 10, 20):
        vol_ma = vol.rolling(w, min_periods=w).mean()
        col = f"vol_ratio_{w}"
        df[col] = vol / (vol_ma + 1e-9)
        factors.append(col)

    vol_ma20 = vol.rolling(20, min_periods=20).mean()
    vol_std20 = vol.rolling(20, min_periods=20).std()
    df["vol_zscore"] = (vol - vol_ma20) / (vol_std20 + 1e-9)
    df["vol_trend"] = (vol.rolling(5, min_periods=5).mean() - vol_ma20) / (vol_ma20 + 1e-9)
    df["vol_stability"] = vol_std20 / (vol_ma20 + 1e-9)
    factors.extend(["vol_zscore", "vol_trend", "vol_stability"])

    # --- K线形态 ---
    df["candle_body"] = (close - opn) / (close + 1e-9)
    df["amplitude"] = (high - low) / (close + 1e-9)
    max_co = pd.concat([close, opn], axis=1).max(axis=1)
    min_co = pd.concat([close, opn], axis=1).min(axis=1)
    df["upper_shadow"] = (high - max_co) / (close + 1e-9)
    df["lower_shadow"] = (min_co - low) / (close + 1e-9)
    factors.extend(["candle_body", "amplitude", "upper_shadow", "lower_shadow"])

    # --- 动量差 ---
    df["momentum_5_10"] = df["ret_5d"] - df["ret_10d"]
    df["momentum_10_20"] = df["ret_10d"] - df["ret_20d"]
    df["momentum_5_20"] = df["ret_5d"] - df["ret_20d"]
    factors.extend(["momentum_5_10", "momentum_10_20", "momentum_5_20"])

    # --- 价格位置 ---
    roll_high20 = high.rolling(20, min_periods=20).max()
    roll_low20 = low.rolling(20, min_periods=20).min()
    df["price_position_20d"] = (close - roll_low20) / (roll_high20 - roll_low20 + 1e-9)
    roll_high60 = high.rolling(60, min_periods=20).max()
    roll_low60 = low.rolling(60, min_periods=20).min()
    df["price_position_60d"] = (close - roll_low60) / (roll_high60 - roll_low60 + 1e-9)
    factors.extend(["price_position_20d", "price_position_60d"])

    return df, factors


# ===================================================================
# 2. 市场因子（需要 macro_index_close 列）
# ===================================================================

def compute_market_factors(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """计算大盘/市场相关因子"""
    factors: List[str] = []

    idx_col = None
    for c in ("macro_index_close", "index_close", "sh_index_close"):
        if c in df.columns:
            idx_col = c
            break

    if idx_col is None:
        return df, factors

    idx = df[idx_col].astype(float)

    # 指数收益率
    for p in (1, 5, 10, 20):
        col = f"market_ret_{p}d"
        df[col] = idx.pct_change(p)
        factors.append(col)

    # 指数偏离
    for w in (20, 60):
        ma = idx.rolling(w, min_periods=w).mean()
        col = f"market_ma{w}_bias"
        df[col] = (idx - ma) / (ma + 1e-9)
        factors.append(col)

    # 指数波动率
    idx_ret = idx.pct_change()
    df["market_vol_20d"] = idx_ret.rolling(20, min_periods=20).std()
    factors.append("market_vol_20d")

    # 趋势强度（短均线 vs 长均线）
    ma5 = idx.rolling(5, min_periods=5).mean()
    ma20 = idx.rolling(20, min_periods=20).mean()
    df["market_trend_strength"] = (ma5 - ma20) / (ma20 + 1e-9)
    factors.append("market_trend_strength")

    # 个股相对大盘超额收益
    if "ret_1d" in df.columns:
        df["excess_ret_1d"] = df["ret_1d"] - df.get("market_ret_1d", 0)
        df["excess_ret_5d"] = df.get("ret_5d", 0) - df.get("market_ret_5d", 0)
        factors.extend(["excess_ret_1d", "excess_ret_5d"])

    # 市场宽度
    if "macro_breadth_ratio" in df.columns:
        df["breadth_ratio"] = df["macro_breadth_ratio"].astype(float)
        factors.append("breadth_ratio")

    return df, factors


# ===================================================================
# 3. 新闻/情绪因子
# ===================================================================

def compute_sentiment_factors(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """计算新闻情绪因子（需要 news 相关列）"""
    factors: List[str] = []

    # 情绪均值（多窗口）
    sent_col = None
    for c in ("avg_sentiment", "sentiment_score", "news_sentiment"):
        if c in df.columns:
            sent_col = c
            break

    if sent_col:
        sent = df[sent_col].astype(float).fillna(0)
        for w in (1, 3, 5, 7, 14):
            col = f"sentiment_{w}d"
            df[col] = sent.rolling(w, min_periods=1).mean()
            factors.append(col)

        # 情绪动量
        df["sentiment_momentum_3_7"] = df.get("sentiment_3d", 0) - df.get("sentiment_7d", 0)
        df["sentiment_accel"] = sent.diff().rolling(3, min_periods=1).mean()
        factors.extend(["sentiment_momentum_3_7", "sentiment_accel"])

        # 情绪波动
        df["sentiment_vol_7d"] = sent.rolling(7, min_periods=3).std().fillna(0)
        factors.append("sentiment_vol_7d")

    # 新闻数量
    count_col = None
    for c in ("news_count", "news_volume"):
        if c in df.columns:
            count_col = c
            break

    if count_col:
        nc = df[count_col].astype(float).fillna(0)
        df["news_vol_1d"] = nc
        nc_ma = nc.rolling(20, min_periods=5).mean()
        df["news_vol_spike"] = nc / (nc_ma + 1e-9)
        df["news_vol_5d"] = nc.rolling(5, min_periods=1).sum()
        factors.extend(["news_vol_1d", "news_vol_spike", "news_vol_5d"])

    # 正负面比例
    if "pos_count" in df.columns and "neg_count" in df.columns:
        total = df.get(count_col, df["pos_count"] + df["neg_count"]).astype(float) + 1e-9
        df["news_pos_ratio"] = df["pos_count"].astype(float) / total
        df["news_neg_ratio"] = df["neg_count"].astype(float) / total
        df["news_pn_ratio"] = (df["pos_count"].astype(float) + 1) / (df["neg_count"].astype(float) + 1)
        factors.extend(["news_pos_ratio", "news_neg_ratio", "news_pn_ratio"])

    return df, factors


# ===================================================================
# 4. 宏观因子
# ===================================================================

def compute_macro_factors(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """计算宏观经济因子"""
    factors: List[str] = []

    # 利率（如有）
    for col in ("shibor_1w", "shibor_1m", "treasury_yield_10y"):
        if col in df.columns:
            v = df[col].astype(float)
            diff_col = f"{col}_chg"
            df[diff_col] = v.diff()
            factors.extend([col, diff_col])

    # CPI / PPI（如有）
    for col in ("cpi_yoy", "ppi_yoy"):
        if col in df.columns:
            factors.append(col)

    # PMI（如有）
    if "pmi" in df.columns:
        df["pmi_above_50"] = (df["pmi"].astype(float) > 50).astype(float)
        factors.extend(["pmi", "pmi_above_50"])

    return df, factors


# ===================================================================
# 5. 衍生特征自动生成
# ===================================================================

def compute_derived_features(
    df: pd.DataFrame,
    base_factors: List[str],
    max_lag: int = 5,
    rolling_windows: Tuple[int, ...] = (3, 5, 10),
    top_n_for_interaction: int = 8,
) -> Tuple[pd.DataFrame, List[str]]:
    """基于已有因子自动生成衍生特征

    生成策略：
    1. 滞后项：对全部 base_factors 生成 lag 1~max_lag
    2. 滑动窗口统计：对关键因子生成 rolling mean/std/skew/min/max
    3. 因子交叉比率：对 top_n_for_interaction 个关键因子做两两比率
    """
    derived: List[str] = []

    # ---------- 滞后项 ----------
    for col in base_factors:
        if col not in df.columns:
            continue
        for lag in range(1, max_lag + 1):
            lag_col = f"{col}_lag{lag}"
            df[lag_col] = df[col].shift(lag)
            derived.append(lag_col)

    # ---------- 滑动窗口统计 ----------
    # 只对核心因子做，避免特征爆炸
    core_factors = [c for c in ["ret_1d", "ret_5d", "vol_ratio_5", "rsi_14",
                                "macd_hist_norm", "bb_position", "atr_pct",
                                "volatility_20d", "adx", "cci"] if c in df.columns]

    for col in core_factors:
        series = df[col]
        for w in rolling_windows:
            prefix = f"{col}_w{w}"
            df[f"{prefix}_mean"] = series.rolling(w, min_periods=max(1, w // 2)).mean()
            df[f"{prefix}_std"] = series.rolling(w, min_periods=max(1, w // 2)).std()
            derived.extend([f"{prefix}_mean", f"{prefix}_std"])

            if w >= 5:
                df[f"{prefix}_skew"] = series.rolling(w, min_periods=w).skew()
                df[f"{prefix}_kurt"] = series.rolling(w, min_periods=w).kurt()
                derived.extend([f"{prefix}_skew", f"{prefix}_kurt"])

    # ---------- 因子交叉比率 ----------
    interaction_factors = [c for c in base_factors[:top_n_for_interaction] if c in df.columns]
    for i in range(len(interaction_factors)):
        for j in range(i + 1, len(interaction_factors)):
            a, b = interaction_factors[i], interaction_factors[j]
            cross_col = f"x_{a}__{b}"
            df[cross_col] = df[a] * df[b]
            derived.append(cross_col)
            if len(derived) > 200:
                break
        if len(derived) > 200:
            break

    return df, derived


# ===================================================================
# 综合因子引擎
# ===================================================================

class FactorEngine:
    """综合因子工程引擎

    用法：
        engine = FactorEngine()
        df, all_factors = engine.compute(df, enable_derived=True)

    配合 FeatureSelector 使用：
        df, all_factors = engine.compute(df)
        selector = FeatureSelector(method='auto', top_n=40)
        X_selected, selected_names = selector.fit_transform(X, y, all_factors)
    """

    def __init__(
        self,
        enable_technical: bool = True,
        enable_market: bool = True,
        enable_sentiment: bool = True,
        enable_macro: bool = True,
        enable_event: bool = True,
        enable_derived: bool = True,
        max_lag: int = 3,
        rolling_windows: Tuple[int, ...] = (3, 5, 10),
    ):
        self.enable_technical = enable_technical
        self.enable_market = enable_market
        self.enable_sentiment = enable_sentiment
        self.enable_macro = enable_macro
        self.enable_event = enable_event
        self.enable_derived = enable_derived
        self.max_lag = max_lag
        self.rolling_windows = rolling_windows

    def compute(
        self,
        df: pd.DataFrame,
        news_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        event_df: Optional[pd.DataFrame] = None,
    ) -> Tuple[pd.DataFrame, List[str], Dict[str, FactorGroup]]:
        """计算全部因子

        Args:
            df:       OHLCV DataFrame（必须包含 trade_date, close）
            news_df:  新闻数据（trade_date + 情绪列），可选
            macro_df: 宏观数据（trade_date + 宏观列），可选
            event_df: 事件因子数据（trade_date + event_* 列），可选

        Returns:
            df:       增加了因子列的 DataFrame
            all_factors: 所有因子列名列表
            groups:   按类别分组的因子信息
        """
        df = df.sort_values("trade_date").copy()
        all_factors: List[str] = []
        groups: Dict[str, FactorGroup] = {}

        # 合并外部数据
        if news_df is not None and not news_df.empty:
            news_cols_before = set(df.columns)
            df = df.merge(news_df, on="trade_date", how="left")
            for c in df.columns:
                if c not in news_cols_before and c != "trade_date":
                    df[c] = df[c].fillna(0)

        if macro_df is not None and not macro_df.empty:
            macro_cols_before = set(df.columns)
            df = df.merge(macro_df, on="trade_date", how="left")
            for c in df.columns:
                if c not in macro_cols_before and c != "trade_date":
                    df[c] = df[c].ffill().fillna(0)

        if event_df is not None and not event_df.empty:
            event_cols_before = set(df.columns)
            merge_cols = [c for c in event_df.columns if c != "symbol"]
            if "symbol" in event_df.columns and "symbol" in df.columns:
                df = df.merge(event_df, on=["trade_date", "symbol"], how="left", suffixes=("", "_evt"))
            elif "trade_date" in event_df.columns:
                df = df.merge(event_df[merge_cols], on="trade_date", how="left", suffixes=("", "_evt"))
            for c in df.columns:
                if c not in event_cols_before and c != "trade_date":
                    df[c] = df[c].fillna(0)

        # 1. 技术指标
        if self.enable_technical:
            df, tech_factors = compute_technical_factors(df)
            all_factors.extend(tech_factors)
            groups["technical"] = FactorGroup("technical", tech_factors)
            logger.info("技术因子: %d 个", len(tech_factors))

        # 2. 市场因子
        if self.enable_market:
            df, mkt_factors = compute_market_factors(df)
            all_factors.extend(mkt_factors)
            groups["market"] = FactorGroup("market", mkt_factors)
            logger.info("市场因子: %d 个", len(mkt_factors))

        # 3. 情绪因子
        if self.enable_sentiment:
            df, sent_factors = compute_sentiment_factors(df)
            all_factors.extend(sent_factors)
            groups["sentiment"] = FactorGroup("sentiment", sent_factors)
            logger.info("情绪因子: %d 个", len(sent_factors))

        # 4. 宏观因子
        if self.enable_macro:
            df, macro_factors = compute_macro_factors(df)
            all_factors.extend(macro_factors)
            groups["macro"] = FactorGroup("macro", macro_factors)
            logger.info("宏观因子: %d 个", len(macro_factors))

        # 5. 事件驱动因子
        if self.enable_event:
            from .event_alpha import compute_event_factors
            df, event_factors = compute_event_factors(df)
            all_factors.extend(event_factors)
            groups["event"] = FactorGroup("event", event_factors)
            logger.info("事件因子: %d 个", len(event_factors))

        # 6. 衍生特征
        if self.enable_derived and all_factors:
            df, derived_factors = compute_derived_features(
                df, all_factors,
                max_lag=self.max_lag,
                rolling_windows=self.rolling_windows,
            )
            all_factors.extend(derived_factors)
            groups["derived"] = FactorGroup("derived", derived_factors)
            logger.info("衍生因子: %d 个", len(derived_factors))

        # 过滤掉不存在的列
        all_factors = [c for c in all_factors if c in df.columns]

        logger.info("因子工程完成: 总计 %d 个因子", len(all_factors))
        return df, all_factors, groups
