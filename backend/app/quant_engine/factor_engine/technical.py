"""
技术因子（Technical Factors）

包含：MA / EMA / RSI / MACD / Bollinger Bands / ATR / KDJ 等
所有因子通过 @register_factor 注册到全局因子库。

要求输入 DataFrame 包含列：close, high, low, vol（至少 close）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import register_factor


# ========== 均线类 ==========

@register_factor(name="ma_5", category="technical", description="5日简单移动均线", params={"window": 5})
def compute_ma(df: pd.DataFrame, window: int = 5) -> pd.Series:
    return df["close"].rolling(window=window, min_periods=1).mean()


@register_factor(name="ma_10", category="technical", description="10日简单移动均线", params={"window": 10})
def compute_ma_10(df: pd.DataFrame, window: int = 10) -> pd.Series:
    return df["close"].rolling(window=window, min_periods=1).mean()


@register_factor(name="ma_20", category="technical", description="20日简单移动均线", params={"window": 20})
def compute_ma_20(df: pd.DataFrame, window: int = 20) -> pd.Series:
    return df["close"].rolling(window=window, min_periods=1).mean()


@register_factor(name="ma_60", category="technical", description="60日简单移动均线", params={"window": 60})
def compute_ma_60(df: pd.DataFrame, window: int = 60) -> pd.Series:
    return df["close"].rolling(window=window, min_periods=1).mean()


@register_factor(name="ema_12", category="technical", description="12日指数移动均线", params={"span": 12})
def compute_ema_12(df: pd.DataFrame, span: int = 12) -> pd.Series:
    return df["close"].ewm(span=span, adjust=False).mean()


@register_factor(name="ema_26", category="technical", description="26日指数移动均线", params={"span": 26})
def compute_ema_26(df: pd.DataFrame, span: int = 26) -> pd.Series:
    return df["close"].ewm(span=span, adjust=False).mean()


# ========== RSI ==========

def _compute_rsi(series: pd.Series, period: int) -> pd.Series:
    """RSI 核心计算"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


@register_factor(name="rsi_6", category="technical", description="6日RSI", params={"period": 6})
def compute_rsi_6(df: pd.DataFrame, period: int = 6) -> pd.Series:
    return _compute_rsi(df["close"], period)


@register_factor(name="rsi_14", category="technical", description="14日RSI", params={"period": 14})
def compute_rsi_14(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _compute_rsi(df["close"], period)


# ========== MACD ==========

@register_factor(name="macd_dif", category="technical", description="MACD DIF线",
                  params={"fast": 12, "slow": 26})
def compute_macd_dif(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


@register_factor(name="macd_dea", category="technical", description="MACD DEA线（信号线）",
                  params={"fast": 12, "slow": 26, "signal": 9})
def compute_macd_dea(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    dif = compute_macd_dif(df, fast, slow)
    return dif.ewm(span=signal, adjust=False).mean()


@register_factor(name="macd_hist", category="technical", description="MACD柱状图",
                  params={"fast": 12, "slow": 26, "signal": 9})
def compute_macd_hist(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    dif = compute_macd_dif(df, fast, slow)
    dea = dif.ewm(span=signal, adjust=False).mean()
    return 2 * (dif - dea)


# ========== 布林带 ==========

@register_factor(name="bb_upper", category="technical", description="布林带上轨",
                  params={"window": 20, "num_std": 2})
def compute_bb_upper(df: pd.DataFrame, window: int = 20, num_std: int = 2) -> pd.Series:
    ma = df["close"].rolling(window=window, min_periods=1).mean()
    std = df["close"].rolling(window=window, min_periods=1).std()
    return ma + num_std * std


@register_factor(name="bb_lower", category="technical", description="布林带下轨",
                  params={"window": 20, "num_std": 2})
def compute_bb_lower(df: pd.DataFrame, window: int = 20, num_std: int = 2) -> pd.Series:
    ma = df["close"].rolling(window=window, min_periods=1).mean()
    std = df["close"].rolling(window=window, min_periods=1).std()
    return ma - num_std * std


@register_factor(name="bb_width", category="technical", description="布林带宽度（标准化）",
                  params={"window": 20, "num_std": 2})
def compute_bb_width(df: pd.DataFrame, window: int = 20, num_std: int = 2) -> pd.Series:
    ma = df["close"].rolling(window=window, min_periods=1).mean()
    std = df["close"].rolling(window=window, min_periods=1).std()
    return (2 * num_std * std) / ma.replace(0, np.nan)


@register_factor(name="bb_pctb", category="technical", description="布林带%B指标",
                  params={"window": 20, "num_std": 2})
def compute_bb_pctb(df: pd.DataFrame, window: int = 20, num_std: int = 2) -> pd.Series:
    """(%B) = (Price - Lower) / (Upper - Lower)"""
    ma = df["close"].rolling(window=window, min_periods=1).mean()
    std = df["close"].rolling(window=window, min_periods=1).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    band_width = upper - lower
    return (df["close"] - lower) / band_width.replace(0, np.nan)


# ========== ATR ==========

@register_factor(name="atr_14", category="technical", description="14日平均真实波幅", params={"period": 14})
def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low - close_prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


# ========== 成交量因子 ==========

@register_factor(name="vol_ratio_5", category="technical", description="5日量比", params={"window": 5})
def compute_vol_ratio(df: pd.DataFrame, window: int = 5) -> pd.Series:
    avg_vol = df["vol"].rolling(window=window, min_periods=1).mean()
    return df["vol"] / avg_vol.replace(0, np.nan)


@register_factor(name="vol_ratio_20", category="technical", description="20日量比", params={"window": 20})
def compute_vol_ratio_20(df: pd.DataFrame, window: int = 20) -> pd.Series:
    avg_vol = df["vol"].rolling(window=window, min_periods=1).mean()
    return df["vol"] / avg_vol.replace(0, np.nan)


# ========== 收益率与波动 ==========

@register_factor(name="ret_1d", category="technical", description="1日收益率")
def compute_ret_1d(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change()


@register_factor(name="ret_5d", category="technical", description="5日累计收益率")
def compute_ret_5d(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(5)


@register_factor(name="ret_20d", category="technical", description="20日累计收益率")
def compute_ret_20d(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(20)


@register_factor(name="volatility_20d", category="technical", description="20日收益率波动率",
                  params={"window": 20})
def compute_volatility(df: pd.DataFrame, window: int = 20) -> pd.Series:
    daily_ret = df["close"].pct_change()
    return daily_ret.rolling(window=window, min_periods=5).std() * np.sqrt(252)


# ========== K线形态因子 ==========

@register_factor(name="candle_body", category="technical", description="K线实体（close-open）/open")
def compute_candle_body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]) / df["open"].replace(0, np.nan)


@register_factor(name="upper_shadow", category="technical", description="上影线比例")
def compute_upper_shadow(df: pd.DataFrame) -> pd.Series:
    body_top = pd.concat([df["open"], df["close"]], axis=1).max(axis=1)
    return (df["high"] - body_top) / (df["high"] - df["low"]).replace(0, np.nan)


@register_factor(name="lower_shadow", category="technical", description="下影线比例")
def compute_lower_shadow(df: pd.DataFrame) -> pd.Series:
    body_bottom = pd.concat([df["open"], df["close"]], axis=1).min(axis=1)
    return (body_bottom - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)


@register_factor(name="amplitude", category="technical", description="振幅 (high-low)/close")
def compute_amplitude(df: pd.DataFrame) -> pd.Series:
    return (df["high"] - df["low"]) / df["close"].replace(0, np.nan)


# ========== 价格位置 ==========

@register_factor(name="price_position_20d", category="technical",
                  description="价格在20日高低区间中的位置", params={"window": 20})
def compute_price_position(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """0 = 20日最低点, 1 = 20日最高点"""
    high_max = df["high"].rolling(window=window, min_periods=1).max()
    low_min = df["low"].rolling(window=window, min_periods=1).min()
    rng = high_max - low_min
    return (df["close"] - low_min) / rng.replace(0, np.nan)


# ========== 尺度无关因子（Scale-Invariant） ==========

@register_factor(name="atr_pct", category="technical",
                  description="ATR占价格比例（波动率指标，尺度无关）", params={"period": 14})
def compute_atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR / close，消除价格量纲影响"""
    atr = compute_atr(df, period)
    return atr / df["close"].replace(0, np.nan)


@register_factor(name="macd_norm", category="technical",
                  description="MACD柱状图标准化（除以价格）", params={"fast": 12, "slow": 26, "signal": 9})
def compute_macd_norm(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """MACD hist / close，消除价格量纲"""
    hist = compute_macd_hist(df, fast, slow, signal)
    return hist / df["close"].replace(0, np.nan)


@register_factor(name="ret_60d", category="technical", description="60日累计收益率")
def compute_ret_60d(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(60)


@register_factor(name="downside_vol_20d", category="technical",
                  description="20日下行波动率（仅负收益率标准差）", params={"window": 20})
def compute_downside_vol(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """仅使用负收益率计算波动率，衡量下行风险"""
    daily_ret = df["close"].pct_change()
    neg_ret = daily_ret.where(daily_ret < 0, 0)
    return neg_ret.rolling(window=window, min_periods=5).std() * np.sqrt(252)


@register_factor(name="max_drawdown_60d", category="technical",
                  description="60日最大回撤", params={"window": 60})
def compute_max_drawdown_60d(df: pd.DataFrame, window: int = 60) -> pd.Series:
    """滚动60日最大回撤，值为负数（如-0.15表示15%回撤）"""
    close = df["close"]
    result = pd.Series(np.nan, index=close.index)
    for i in range(window, len(close)):
        window_data = close.iloc[i - window:i + 1]
        running_max = window_data.cummax()
        drawdown = (window_data - running_max) / running_max.replace(0, np.nan)
        result.iloc[i] = drawdown.min()
    return result


@register_factor(name="ma_5_diff", category="technical", description="价格相对MA5偏离度")
def compute_ma_5_diff(df: pd.DataFrame) -> pd.Series:
    """(close - MA5) / MA5"""
    ma = df["close"].rolling(window=5, min_periods=1).mean()
    return (df["close"] - ma) / ma.replace(0, np.nan)


@register_factor(name="ma_10_diff", category="technical", description="价格相对MA10偏离度")
def compute_ma_10_diff(df: pd.DataFrame) -> pd.Series:
    ma = df["close"].rolling(window=10, min_periods=1).mean()
    return (df["close"] - ma) / ma.replace(0, np.nan)


@register_factor(name="ma_20_diff", category="technical", description="价格相对MA20偏离度")
def compute_ma_20_diff(df: pd.DataFrame) -> pd.Series:
    ma = df["close"].rolling(window=20, min_periods=1).mean()
    return (df["close"] - ma) / ma.replace(0, np.nan)


@register_factor(name="ma_60_diff", category="technical", description="价格相对MA60偏离度")
def compute_ma_60_diff(df: pd.DataFrame) -> pd.Series:
    ma = df["close"].rolling(window=60, min_periods=1).mean()
    return (df["close"] - ma) / ma.replace(0, np.nan)


@register_factor(name="ema_12_diff", category="technical", description="价格相对EMA12偏离度")
def compute_ema_12_diff(df: pd.DataFrame) -> pd.Series:
    ema = df["close"].ewm(span=12, adjust=False).mean()
    return (df["close"] - ema) / ema.replace(0, np.nan)


@register_factor(name="ema_26_diff", category="technical", description="价格相对EMA26偏离度")
def compute_ema_26_diff(df: pd.DataFrame) -> pd.Series:
    ema = df["close"].ewm(span=26, adjust=False).mean()
    return (df["close"] - ema) / ema.replace(0, np.nan)


@register_factor(name="vol_stability_20d", category="technical",
                  description="20日成交量稳定性（量比标准差）", params={"window": 20})
def compute_vol_stability(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """成交量波动性：vol_ratio 的滚动标准差"""
    avg_vol = df["vol"].rolling(window=window, min_periods=5).mean()
    vol_ratio = df["vol"] / avg_vol.replace(0, np.nan)
    return vol_ratio.rolling(window=window, min_periods=5).std()
