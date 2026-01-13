
"""
信号计算模块（signals）

概述
----
本模块提供用于技术面分析的常用指标计算与简单交易信号打分逻辑。主要功能包括：
- 计算相对强弱指数（RSI）
- 计算移动平均收敛/发散指标（MACD）
- 基于短/长均线、RSI、MACD 生成信号分数并给出交易建议（BUY/HOLD/TRIM）

导出函数
--------
rsi(series: pandas.Series, period: int = 14) -> pandas.Series
    计算相对强弱指标 RSI（值域 0~100）。
    - 输入：收盘价序列（索引会被保留）
    - 采用指数加权平均（EWMA）计算平均上涨/下跌幅度以得到平滑的 RS。
    - 对除以零做了数值稳定处理（添加极小值）。
    - 返回与输入对齐的 Series，早期窗口会包含 NaN。

macd(series: pandas.Series, fast=12, slow=26, signal=9) -> (macd_line, signal_line, hist)
    计算 MACD 指标（MACD 线、信号线、柱体）。
    - 采用给定 span 的 EMA 进行平滑：macd_line = EMA(fast) - EMA(slow)。
    - signal_line 为 macd_line 的 EMA，hist 为两者差值。
    - 返回三个与输入索引对齐的 pandas.Series 或相似结构。

compute_signals(df: pandas.DataFrame, short=10, long=30) -> pandas.DataFrame
    在输入 DataFrame 基础上计算并追加常用技术指标和信号打分：
    - 计算短/长期简单移动均线 ma_s / ma_l（窗口 short/long）。
    - 计算 rsi（固定 period=14）和 macd（默认 12,26,9），并将结果写入列 macd, macd_sig, macd_hist。
    - score 由以下部分构成：
        * 均线金叉 +20 / 死叉 -20（发生当日检测）
        * RSI 偏离 50 的评分（使用 clip 限制在 [-15,15]）
        * MACD 金叉发生时 +10
    - 根据 score 生成 action 列：
        * score >= 15 -> "BUY"
        * score <= -15 -> "TRIM"
        * 其他 -> "HOLD"
    - 要求输入至少包含列 ['trade_date', 'close']，会根据 trade_date 升序排序并返回拷贝，不修改原对象。

注意事项
--------
- 所有基于窗口/EMA 的指标在起始若干行会包含 NaN；在实际使用前应考虑填充或丢弃这些行。
- compute_signals 假定 trade_date 唯一且可排序；若为字符串或时间类型，应确保能正确排序。
- 评分阈值与分项权重为经验值，可根据策略回测调整。
- 数值稳定性：RSI 计算中对除数添加极小值以避免零除错误。
- 返回的 DataFrame 会包含原始列并新增：ma_s, ma_l, rsi, macd, macd_sig, macd_hist, signal_score, action。

示例（简要）
------------
假设 df 包含 trade_date 与 close：
    df2 = compute_signals(df, short=10, long=30)
    观察 df2[['trade_date','close','ma_s','ma_l','rsi','macd_hist','signal_score','action']]


"""

import numpy as np
import pandas as pd

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    计算相对强弱指标 RSI

    Args:
        series: 收盘价序列
        period: 计算周期（默认14）

    Returns:
        与输入索引对齐的 RSI 数列（0~100）
    """
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    roll_down = pd.Series(down, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    """
    计算 MACD 指标（MACD线、信号线、柱体）

    Args:
        series: 收盘价序列
        fast: 快速 EMA 周期（默认12）
        slow: 慢速 EMA 周期（默认26）
        signal: 信号线 EMA 周期（默认9）

    Returns:
        (macd_line, signal_line, hist)
    """
    e1 = series.ewm(span=fast, adjust=False).mean()
    e2 = series.ewm(span=slow, adjust=False).mean()
    macd_line = e1 - e2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def compute_signals(df: pd.DataFrame, short=10, long=30) -> pd.DataFrame:
    """
    计算基础交易信号与综合打分

    流程：
    - 计算短/长均线（默认10/30），RSI(14)，MACD(12,26,9)。
    - 依据均线金叉/死叉、RSI 偏离、MACD 金叉等给予加减分。
    - 根据 score 给出 BUY/HOLD/TRIM 建议。

    Args:
        df: 必须包含列 ['trade_date','close']，可包含 'vol'
        short: 短均线窗口（默认10）
        long: 长均线窗口（默认30）

    Returns:
        在输入 DataFrame 基础上增加以下列：
        - ma_s, ma_l, rsi, macd, macd_sig, macd_hist, signal_score, action
    """
    df = df.sort_values("trade_date").copy()
    df["ma_s"] = df["close"].rolling(short).mean()
    df["ma_l"] = df["close"].rolling(long).mean()
    df["rsi"] = rsi(df["close"], 14)
    macd_line, signal_line, hist = macd(df["close"])
    df["macd"] = macd_line
    df["macd_sig"] = signal_line
    df["macd_hist"] = hist

    score = np.zeros(len(df))
    cross_up = (df["ma_s"] > df["ma_l"]) & (df["ma_s"].shift(1) <= df["ma_l"].shift(1))
    cross_dn = (df["ma_s"] < df["ma_l"]) & (df["ma_s"].shift(1) >= df["ma_l"].shift(1))
    score = score + np.where(cross_up, 20, 0) - np.where(cross_dn, 20, 0)
    score += np.clip(50 - (df["rsi"] - 50).abs(), -15, 15)
    score += np.where((df["macd"] > df["macd_sig"]) & (df["macd"].shift(1) <= df["macd_sig"].shift(1)), 10, 0)

    df["signal_score"] = score
    df["action"] = np.where(
        df["signal_score"] >= 15, "BUY",
        np.where(df["signal_score"] <= -15, "TRIM", "HOLD")
    )
    return df
