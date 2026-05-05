"""
事件信号桥接模块 - 规则驱动的事件→交易信号转换

将事件元数据（事件类型、信源等级、情感分数）转换为交易信号。
基于规则映射，无 LLM、无外部依赖、无数据库操作。
"""

from datetime import date
from typing import Dict, Any, Optional
from enum import Enum

from app.analysis.signal_validator import TradingSignal, SignalType, SignalStrength
from app.core.constants import SOURCE_LEVEL_WEIGHTS, EventTypeEnum


class EventSignalBridge:
    """事件到交易信号的规则映射桥接"""
    
    def __init__(self, custom_rules: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        初始化规则引擎
        
        Args:
            custom_rules: 自定义规则表（可选），格式为 {event_type: {source_level: {direction, confidence_base}}}
        """
        self.source_level_weights = SOURCE_LEVEL_WEIGHTS
        self.sentiment_multiplier = 0.3  # 情感系数
        self.neutral_threshold = 0.2     # 中性情感阈值 [-0.2, 0.2]
        
        # 初始化规则表
        if custom_rules:
            self.rules = custom_rules
        else:
            self.rules = self._build_default_rules()
    
    def _build_default_rules(self) -> Dict[str, Dict[str, str]]:
        """
        构建默认规则表
        
        规则逻辑：
        - 利好事件 (earnings, buyback, contract, product_launch, strategic_partnership, merger)：
          - L1 + positive → BUY (base_confidence=1.0)
          - L2/L3 + positive → BUY (base_confidence=0.7/0.9)
          - L4 + positive → BUY (base_confidence=0.5)
        - 利空事件 (penalty, litigation, asset_sale, risk_alert)：
          - 任何信源 + negative → SELL
        - 中性事件 → HOLD（无论情感分数）
        - 其他事件结合情感分数判断
        """
        return {
            # 利好事件
            EventTypeEnum.EARNINGS.value: {
                "L1": {"direction": "buy", "type": "bullish"},
                "L2": {"direction": "buy", "type": "bullish"},
                "L3": {"direction": "buy", "type": "bullish"},
                "L4": {"direction": "buy", "type": "bullish"},
            },
            EventTypeEnum.BUYBACK.value: {
                "L1": {"direction": "buy", "type": "bullish"},
                "L2": {"direction": "buy", "type": "bullish"},
                "L3": {"direction": "buy", "type": "bullish"},
                "L4": {"direction": "buy", "type": "bullish"},
            },
            EventTypeEnum.CONTRACT.value: {
                "L1": {"direction": "buy", "type": "bullish"},
                "L2": {"direction": "buy", "type": "bullish"},
                "L3": {"direction": "buy", "type": "bullish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.PRODUCT_LAUNCH.value: {
                "L1": {"direction": "buy", "type": "bullish"},
                "L2": {"direction": "buy", "type": "bullish"},
                "L3": {"direction": "buy", "type": "bullish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.STRATEGIC_PARTNERSHIP.value: {
                "L1": {"direction": "buy", "type": "bullish"},
                "L2": {"direction": "buy", "type": "bullish"},
                "L3": {"direction": "buy", "type": "bullish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.MERGER.value: {
                "L1": {"direction": "buy", "type": "bullish"},
                "L2": {"direction": "buy", "type": "bullish"},
                "L3": {"direction": "buy", "type": "bullish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            
            # 利空事件
            EventTypeEnum.PENALTY.value: {
                "L1": {"direction": "sell", "type": "bearish"},
                "L2": {"direction": "sell", "type": "bearish"},
                "L3": {"direction": "sell", "type": "bearish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.LITIGATION.value: {
                "L1": {"direction": "sell", "type": "bearish"},
                "L2": {"direction": "sell", "type": "bearish"},
                "L3": {"direction": "sell", "type": "bearish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.ASSET_SALE.value: {
                "L1": {"direction": "sell", "type": "bearish"},
                "L2": {"direction": "sell", "type": "bearish"},
                "L3": {"direction": "sell", "type": "bearish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.RISK_ALERT.value: {
                "L1": {"direction": "sell", "type": "bearish"},
                "L2": {"direction": "sell", "type": "bearish"},
                "L3": {"direction": "sell", "type": "bearish"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            
            # 中性/复杂事件（结合情感分数）
            EventTypeEnum.ANNOUNCEMENT.value: {
                "L1": {"direction": "neutral", "type": "context_dependent"},
                "L2": {"direction": "neutral", "type": "context_dependent"},
                "L3": {"direction": "neutral", "type": "context_dependent"},
                "L4": {"direction": "neutral", "type": "context_dependent"},
            },
            EventTypeEnum.EARNINGS_ADJUSTMENT.value: {
                "L1": {"direction": "neutral", "type": "context_dependent"},
                "L2": {"direction": "neutral", "type": "context_dependent"},
                "L3": {"direction": "neutral", "type": "context_dependent"},
                "L4": {"direction": "neutral", "type": "context_dependent"},
            },
            EventTypeEnum.POLICY_IMPACT.value: {
                "L1": {"direction": "neutral", "type": "context_dependent"},
                "L2": {"direction": "neutral", "type": "context_dependent"},
                "L3": {"direction": "neutral", "type": "context_dependent"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.DEBT_ISSUANCE.value: {
                "L1": {"direction": "neutral", "type": "context_dependent"},
                "L2": {"direction": "neutral", "type": "context_dependent"},
                "L3": {"direction": "neutral", "type": "context_dependent"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
            EventTypeEnum.EQUITY_ISSUANCE.value: {
                "L1": {"direction": "neutral", "type": "context_dependent"},
                "L2": {"direction": "neutral", "type": "context_dependent"},
                "L3": {"direction": "neutral", "type": "context_dependent"},
                "L4": {"direction": "hold", "type": "neutral"},
            },
        }
    
    def generate_signal(
        self,
        symbol: str,
        event_type: str,
        source_level: str,
        sentiment_score: float,
        event_date: date,
    ) -> TradingSignal:
        """
        根据事件元数据生成交易信号
        
        Args:
            symbol: 股票代码
            event_type: 事件类型（来自 EventTypeEnum）
            source_level: 信源等级（L1/L2/L3/L4）
            sentiment_score: 情感分数 [-1.0, 1.0]，其中 -1=极负, 0=中性, +1=极正
            event_date: 事件日期
            
        Returns:
            TradingSignal 对象
            
        Raises:
            ValueError: 参数验证失败
        """
        # 参数验证
        self._validate_inputs(event_type, source_level, sentiment_score)
        
        # 获取基础方向
        base_direction = self._get_base_direction(event_type, source_level, sentiment_score)
        
        # 计算置信度与强度
        confidence = self._calculate_confidence(source_level, sentiment_score, base_direction)
        signal_strength = self._get_signal_strength(confidence)
        
        # 计算信号分数 (0-100)
        score = int(confidence * 100)
        
        # 构建因子记录
        factors = {
            "event_type": event_type,
            "source_level": source_level,
            "sentiment_score": sentiment_score,
            "base_direction": base_direction,
            "source_weight": self.source_level_weights.get(source_level, 0.5),
            "confidence": confidence,
        }
        
        # 构建交易信号
        signal = TradingSignal(
            symbol=symbol,
            signal_type=self._direction_to_signal_type(base_direction),
            signal_date=event_date,
            strength=signal_strength,
            score=score,
            confidence=confidence,
            source=f"event_bridge_{event_type}",
            factors=factors,
        )
        
        return signal
    
    def _validate_inputs(self, event_type: str, source_level: str, sentiment_score: float) -> None:
        """验证输入参数"""
        # 验证事件类型
        valid_event_types = {e.value for e in EventTypeEnum}
        if event_type not in valid_event_types:
            raise ValueError(f"Invalid event_type: {event_type}. Must be one of {valid_event_types}")
        
        # 验证信源等级
        valid_levels = {"L1", "L2", "L3", "L4"}
        if source_level not in valid_levels:
            raise ValueError(f"Invalid source_level: {source_level}. Must be one of {valid_levels}")
        
        # 验证情感分数范围
        if not -1.0 <= sentiment_score <= 1.0:
            raise ValueError(f"Invalid sentiment_score: {sentiment_score}. Must be in [-1.0, 1.0]")
    
    def _get_base_direction(self, event_type: str, source_level: str, sentiment_score: float) -> str:
        """
        确定基础方向（buy/sell/hold）
        
        逻辑：
        1. 中性情感 [-0.2, 0.2] → hold（无论事件类型）
        2. 查表获取基础方向
        3. 对于 context_dependent 事件，基于情感分数调整
        """
        # 中性情感强制 HOLD
        if abs(sentiment_score) < self.neutral_threshold:
            return "hold"
        
        # 从规则表查询
        rule = self.rules.get(event_type, {}).get(source_level)
        
        if not rule:
            # 未定义的事件类型，按情感分数返回
            return "buy" if sentiment_score > 0 else "sell"
        
        direction = rule.get("direction", "hold")
        rule_type = rule.get("type", "")
        
        # 对于 context_dependent 事件，根据情感分数调整
        if direction == "neutral":
            if sentiment_score > 0:
                return "buy"
            elif sentiment_score < 0:
                return "sell"
            else:
                return "hold"
        
        # 检查情感与方向是否一致
        if direction == "buy" and sentiment_score < 0:
            # 利好事件但情感为负 → 降级为 hold
            return "hold"
        elif direction == "sell" and sentiment_score > 0:
            # 利空事件但情感为正 → 降级为 hold
            return "hold"
        
        return direction
    
    def _calculate_confidence(self, source_level: str, sentiment_score: float, direction: str) -> float:
        """
        计算置信度
        
        公式：
        - base_confidence = SOURCE_LEVEL_WEIGHTS[source_level]
        - sentiment_factor = 1 + abs(sentiment_score) * sentiment_multiplier
        - confidence = min(base_confidence * sentiment_factor, 1.0)
        """
        base_confidence = self.source_level_weights.get(source_level, 0.5)
        
        # 情感极端化提升置信度
        sentiment_factor = 1 + abs(sentiment_score) * self.sentiment_multiplier
        
        # 最终置信度上限 1.0
        confidence = min(base_confidence * sentiment_factor, 1.0)
        
        # 中性情感降低置信度
        if abs(sentiment_score) < self.neutral_threshold:
            confidence = min(confidence, 0.5)
        
        return confidence
    
    def _get_signal_strength(self, confidence: float) -> SignalStrength:
        """根据置信度确定信号强度"""
        if confidence >= 0.8:
            return SignalStrength.STRONG
        elif confidence >= 0.5:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK
    
    def _direction_to_signal_type(self, direction: str) -> SignalType:
        """将方向字符串转换为 SignalType 枚举"""
        direction_map = {
            "buy": SignalType.BUY,
            "sell": SignalType.SELL,
            "hold": SignalType.HOLD,
        }
        return direction_map.get(direction, SignalType.HOLD)
