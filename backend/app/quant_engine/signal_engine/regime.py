"""
市场环境检测（Market Regime Detection）

通过宏观指数趋势和波动率判断当前市场环境：
- 牛市（bull）: 指数在MA60上方且MA20>MA60，波动率低
- 熊市（bear）: 指数在MA60下方且MA20<MA60，波动率高
- 震荡（sideways）: 无明确趋势

用途：
- 信号生成时根据市场环境调整阈值和权重
- 风险评分动态调整
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"


# 兼容别名：后续会新增同名类 MarketRegime
LegacyMarketRegime = MarketRegime


class RegimeState(str, Enum):
    """五阶段市场状态（规则驱动）"""

    ICE_POINT = "ice_point"
    RECOVERY = "recovery"
    MAIN_UPTREND = "main_uptrend"
    DIVERGENCE = "divergence"
    DECLINE = "decline"


@dataclass
class RegimeResult:
    """市场环境检测结果"""
    regime: LegacyMarketRegime
    confidence: float           # 0-1, 判断置信度
    index_trend: float          # >0 上行, <0 下行
    market_volatility: float    # 市场波动率
    breadth: float              # 市场宽度（上涨比例）
    details: dict


# 不同市场环境下的信号阈值调整
REGIME_ADJUSTMENTS = {
    LegacyMarketRegime.BULL: {
        "score_bias": 5,         # 综合评分正偏移
        "risk_discount": 0.85,   # 风险折扣
        "buy_threshold": -3,     # 买入阈值降低
        "sell_threshold": -5,    # 卖出阈值降低（更不容易卖出）
    },
    LegacyMarketRegime.BEAR: {
        "score_bias": -5,
        "risk_discount": 1.15,   # 风险溢价
        "buy_threshold": 5,      # 买入阈值提高
        "sell_threshold": 3,     # 卖出阈值提高（更容易卖出）
    },
    LegacyMarketRegime.SIDEWAYS: {
        "score_bias": 0,
        "risk_discount": 1.0,
        "buy_threshold": 0,
        "sell_threshold": 0,
    },
}


class RegimeDetector:
    """市场环境检测器

    用法：
        detector = RegimeDetector()
        result = detector.detect(index_df)
        adjustments = detector.get_adjustments(result.regime)
    """

    def detect(
        self,
        index_df: pd.DataFrame,
        lookback: int = 120,
    ) -> RegimeResult:
        """检测当前市场环境

        Args:
            index_df: 指数日线数据，需包含 close 列
            lookback: 回溯天数

        Returns:
            RegimeResult
        """
        if index_df is None or index_df.empty or "close" not in index_df.columns:
            return RegimeResult(
                regime=LegacyMarketRegime.SIDEWAYS,
                confidence=0.3,
                index_trend=0,
                market_volatility=0.2,
                breadth=0.5,
                details={"reason": "insufficient_data"},
            )

        close = index_df["close"].tail(lookback).astype(float)
        if len(close) < 60:
            return RegimeResult(
                regime=LegacyMarketRegime.SIDEWAYS,
                confidence=0.3,
                index_trend=0,
                market_volatility=0.2,
                breadth=0.5,
                details={"reason": "insufficient_data"},
            )

        # 均线趋势
        ma_20 = close.rolling(20).mean()
        ma_60 = close.rolling(60).mean()

        current_close = close.iloc[-1]
        current_ma20 = ma_20.iloc[-1]
        current_ma60 = ma_60.iloc[-1]

        # 趋势指标：MA20 相对 MA60 的偏离度
        if current_ma60 > 0:
            trend = (current_ma20 - current_ma60) / current_ma60
        else:
            trend = 0.0

        # 价格在 MA60 上方/下方
        price_above_ma60 = current_close > current_ma60

        # 波动率
        daily_ret = close.pct_change().dropna()
        volatility = float(daily_ret.std() * np.sqrt(252))

        # 近20日涨幅
        ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1)) if len(close) >= 20 else 0

        # 市场宽度（简化：使用近期涨跌天数比）
        up_days = (daily_ret.tail(20) > 0).sum()
        breadth = float(up_days / 20) if len(daily_ret) >= 20 else 0.5

        # 综合判断
        bull_score = 0
        bear_score = 0

        # 趋势信号
        if trend > 0.02:
            bull_score += 2
        elif trend < -0.02:
            bear_score += 2
        elif trend > 0:
            bull_score += 1
        else:
            bear_score += 1

        # 价格位置
        if price_above_ma60:
            bull_score += 1
        else:
            bear_score += 1

        # 波动率
        if volatility < 0.20:
            bull_score += 1
        elif volatility > 0.35:
            bear_score += 1

        # 近期收益
        if ret_20d > 0.03:
            bull_score += 1
        elif ret_20d < -0.03:
            bear_score += 1

        # 市场宽度
        if breadth > 0.55:
            bull_score += 1
        elif breadth < 0.45:
            bear_score += 1

        # 判定
        total_signals = bull_score + bear_score
        if total_signals == 0:
            total_signals = 1

        if bull_score >= 4 and bull_score > bear_score * 1.5:
            regime = LegacyMarketRegime.BULL
            confidence = min(bull_score / total_signals, 0.9)
        elif bear_score >= 4 and bear_score > bull_score * 1.5:
            regime = LegacyMarketRegime.BEAR
            confidence = min(bear_score / total_signals, 0.9)
        else:
            regime = LegacyMarketRegime.SIDEWAYS
            confidence = 1.0 - abs(bull_score - bear_score) / total_signals

        logger.info(
            "市场环境检测: regime=%s, confidence=%.2f, trend=%.4f, vol=%.3f, breadth=%.2f",
            regime.value, confidence, trend, volatility, breadth,
        )

        return RegimeResult(
            regime=regime,
            confidence=round(confidence, 3),
            index_trend=round(trend, 4),
            market_volatility=round(volatility, 4),
            breadth=round(breadth, 3),
            details={
                "bull_score": bull_score,
                "bear_score": bear_score,
                "ma20": round(current_ma20, 2),
                "ma60": round(current_ma60, 2),
                "ret_20d": round(ret_20d, 4),
            },
        )

    @staticmethod
    def get_adjustments(regime: LegacyMarketRegime) -> dict:
        """获取市场环境对应的信号调整参数"""
        return REGIME_ADJUSTMENTS.get(regime, REGIME_ADJUSTMENTS[LegacyMarketRegime.SIDEWAYS])


REGIME_STATE_ADJUSTMENTS = {
    RegimeState.ICE_POINT: {
        "score_bias": 2,
        "risk_discount": 0.95,
        "buy_threshold": -1,
        "sell_threshold": 1,
    },
    RegimeState.RECOVERY: {
        "score_bias": 3,
        "risk_discount": 0.9,
        "buy_threshold": -2,
        "sell_threshold": -1,
    },
    RegimeState.MAIN_UPTREND: {
        "score_bias": 5,
        "risk_discount": 0.85,
        "buy_threshold": -3,
        "sell_threshold": -4,
    },
    RegimeState.DIVERGENCE: {
        "score_bias": -1,
        "risk_discount": 1.05,
        "buy_threshold": 2,
        "sell_threshold": 1,
    },
    RegimeState.DECLINE: {
        "score_bias": -5,
        "risk_discount": 1.15,
        "buy_threshold": 5,
        "sell_threshold": 3,
    },
}


class MarketRegime:
    """五阶段市场状态检测器（规则驱动）。"""

    def __init__(self) -> None:
        self._detector = RegimeDetector()

    def detect(self, index_df: pd.DataFrame, lookback: int = 120) -> dict:
        """检测五阶段市场状态。"""
        base = self._detector.detect(index_df=index_df, lookback=lookback)
        state = self._map_state(base)
        return {
            "state": state,
            "confidence": base.confidence,
            "details": {
                **base.details,
                "legacy_regime": base.regime.value,
                "state": state.value,
            },
            "adjustments": self.get_adjustments(state),
        }

    @staticmethod
    def get_adjustments(state: RegimeState) -> dict:
        """获取五阶段状态对应的信号调整参数。"""
        return REGIME_STATE_ADJUSTMENTS.get(state, REGIME_STATE_ADJUSTMENTS[RegimeState.DIVERGENCE])

    @staticmethod
    def _map_state(base: RegimeResult) -> RegimeState:
        """将旧三态结果映射到五态（纯规则，不使用 ML）。"""
        ret_20d = float(base.details.get("ret_20d", 0.0))

        if base.regime == LegacyMarketRegime.BULL:
            if ret_20d > 0.03 and base.breadth < 0.50:
                return RegimeState.DIVERGENCE
            if base.index_trend > 0.02 and base.breadth >= 0.55:
                return RegimeState.MAIN_UPTREND
            return RegimeState.RECOVERY

        if base.regime == LegacyMarketRegime.BEAR:
            if base.market_volatility > 0.30 and base.breadth < 0.45:
                return RegimeState.DECLINE
            if base.index_trend > -0.01 and ret_20d > -0.03:
                return RegimeState.ICE_POINT
            return RegimeState.DECLINE

        if base.index_trend >= 0 and ret_20d >= 0:
            return RegimeState.RECOVERY
        if base.index_trend < -0.01:
            return RegimeState.DECLINE
        return RegimeState.DIVERGENCE
