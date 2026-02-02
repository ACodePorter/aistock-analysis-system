"""
信号验证模块

提供交易信号的验证功能：
- 多周期确认
- 成交量确认
- 信号有效性追踪
- 历史信号绩效统计
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class SignalStrength(str, Enum):
    """信号强度"""
    STRONG = "strong"       # 强信号
    MODERATE = "moderate"   # 中等
    WEAK = "weak"           # 弱信号


class ValidationResult(str, Enum):
    """验证结果"""
    CONFIRMED = "confirmed"     # 已确认
    PENDING = "pending"         # 等待确认
    REJECTED = "rejected"       # 已否定
    EXPIRED = "expired"         # 已过期


@dataclass
class TradingSignal:
    """交易信号"""
    symbol: str
    signal_type: SignalType
    signal_date: date
    
    # 信号强度
    strength: SignalStrength = SignalStrength.MODERATE
    score: float = 50.0                  # 0-100
    confidence: float = 0.5              # 0-1
    
    # 价格信息
    trigger_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    
    # 来源
    source: str = "analysis"             # 信号来源
    factors: Optional[Dict] = None       # 触发因素
    
    # 多周期确认
    confirm_daily: bool = False
    confirm_weekly: bool = False
    confirm_monthly: bool = False
    
    # 成交量确认
    volume_confirm: bool = False
    
    # 验证状态
    validation_result: ValidationResult = ValidationResult.PENDING
    actual_return: Optional[float] = None
    validation_date: Optional[date] = None
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['signal_type'] = self.signal_type.value
        d['strength'] = self.strength.value
        d['validation_result'] = self.validation_result.value
        d['signal_date'] = self.signal_date.isoformat()
        if d['validation_date']:
            d['validation_date'] = d['validation_date'].isoformat()
        return d


class MultiTimeframeValidator:
    """多周期验证器"""
    
    def __init__(self):
        # 周期权重
        self.weights = {
            'daily': 0.4,
            'weekly': 0.35,
            'monthly': 0.25,
        }
    
    def validate_signal(self, symbol: str, signal_type: SignalType,
                       daily_data: pd.DataFrame,
                       weekly_data: pd.DataFrame = None,
                       monthly_data: pd.DataFrame = None) -> Tuple[bool, Dict]:
        """多周期验证信号
        
        Args:
            symbol: 股票代码
            signal_type: 信号类型
            daily_data: 日线数据
            weekly_data: 周线数据
            monthly_data: 月线数据
        
        Returns:
            (是否确认, 详情)
        """
        results = {
            'daily': self._check_timeframe(daily_data, signal_type),
            'weekly': self._check_timeframe(weekly_data, signal_type) if weekly_data is not None else None,
            'monthly': self._check_timeframe(monthly_data, signal_type) if monthly_data is not None else None,
        }
        
        # 计算加权得分
        total_weight = 0
        total_score = 0
        
        for tf, result in results.items():
            if result is not None:
                weight = self.weights.get(tf, 0.3)
                total_weight += weight
                total_score += weight * (1 if result['confirmed'] else 0)
        
        confirmation_score = total_score / total_weight if total_weight > 0 else 0
        
        return confirmation_score >= 0.6, {
            'confirmation_score': confirmation_score,
            'timeframe_results': results,
        }
    
    def _check_timeframe(self, data: pd.DataFrame, signal_type: SignalType) -> Optional[Dict]:
        """检查单周期信号"""
        if data is None or data.empty or len(data) < 5:
            return None
        
        # 计算指标
        close = data['close'].iloc[-1]
        ma5 = data['close'].tail(5).mean()
        ma20 = data['close'].tail(20).mean() if len(data) >= 20 else ma5
        
        # 趋势判断
        trend_up = ma5 > ma20
        price_above_ma = close > ma5
        
        # RSI
        if len(data) >= 14:
            delta = data['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.inf)
            rsi = 100 - (100 / (1 + rs.iloc[-1]))
        else:
            rsi = 50
        
        # 信号确认逻辑
        if signal_type == SignalType.BUY:
            confirmed = trend_up and price_above_ma and rsi < 70
        elif signal_type == SignalType.SELL:
            confirmed = not trend_up and not price_above_ma and rsi > 30
        else:
            confirmed = True
        
        return {
            'confirmed': confirmed,
            'trend_up': trend_up,
            'price_above_ma': price_above_ma,
            'rsi': rsi,
        }


class VolumeValidator:
    """成交量验证器"""
    
    def validate_with_volume(self, data: pd.DataFrame, signal_type: SignalType,
                            volume_multiplier: float = 1.5) -> Tuple[bool, Dict]:
        """使用成交量验证信号
        
        Args:
            data: 行情数据
            signal_type: 信号类型
            volume_multiplier: 成交量倍数阈值
        
        Returns:
            (是否确认, 详情)
        """
        if data.empty or 'volume' not in data.columns or len(data) < 20:
            return False, {'error': '数据不足'}
        
        current_volume = data['volume'].iloc[-1]
        avg_volume = data['volume'].tail(20).mean()
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        # 买入信号需要放量
        if signal_type == SignalType.BUY:
            confirmed = volume_ratio >= volume_multiplier
            
        # 卖出信号可以不需要放量
        elif signal_type == SignalType.SELL:
            confirmed = True  # 卖出不强制要求放量
            
        else:
            confirmed = True
        
        return confirmed, {
            'current_volume': current_volume,
            'avg_volume': avg_volume,
            'volume_ratio': volume_ratio,
            'threshold': volume_multiplier,
        }


class SignalTracker:
    """信号追踪器"""
    
    def __init__(self, validation_days: int = 5):
        """
        Args:
            validation_days: 信号有效期（天）
        """
        self.validation_days = validation_days
        self.signals: Dict[str, List[TradingSignal]] = {}  # symbol -> signals
    
    def add_signal(self, signal: TradingSignal):
        """添加信号"""
        if signal.symbol not in self.signals:
            self.signals[signal.symbol] = []
        
        self.signals[signal.symbol].append(signal)
        
        # 清理过期信号
        self._cleanup_expired(signal.symbol)
    
    def _cleanup_expired(self, symbol: str):
        """清理过期信号"""
        if symbol not in self.signals:
            return
        
        cutoff = date.today() - timedelta(days=self.validation_days * 2)
        self.signals[symbol] = [
            s for s in self.signals[symbol]
            if s.signal_date >= cutoff
        ]
    
    def validate_signals(self, symbol: str, current_price: float,
                        current_date: date = None) -> List[TradingSignal]:
        """验证信号结果
        
        Args:
            symbol: 股票代码
            current_price: 当前价格
            current_date: 当前日期
        
        Returns:
            更新后的信号列表
        """
        current_date = current_date or date.today()
        
        if symbol not in self.signals:
            return []
        
        for signal in self.signals[symbol]:
            if signal.validation_result != ValidationResult.PENDING:
                continue
            
            # 检查是否过期
            days_elapsed = (current_date - signal.signal_date).days
            if days_elapsed > self.validation_days:
                signal.validation_result = ValidationResult.EXPIRED
                signal.validation_date = current_date
                continue
            
            # 计算收益
            if signal.trigger_price and signal.trigger_price > 0:
                if signal.signal_type == SignalType.BUY:
                    signal.actual_return = (current_price - signal.trigger_price) / signal.trigger_price * 100
                else:
                    signal.actual_return = (signal.trigger_price - current_price) / signal.trigger_price * 100
                
                # 判断成功与否
                if signal.actual_return > 2:  # 盈利超过2%
                    signal.validation_result = ValidationResult.CONFIRMED
                elif signal.actual_return < -5:  # 亏损超过5%
                    signal.validation_result = ValidationResult.REJECTED
                
                signal.validation_date = current_date
        
        return self.signals[symbol]
    
    def get_signal_statistics(self, symbol: str = None) -> Dict:
        """获取信号统计
        
        Args:
            symbol: 股票代码（可选，不传则统计全部）
        
        Returns:
            统计信息
        """
        signals_to_analyze = []
        
        if symbol:
            signals_to_analyze = self.signals.get(symbol, [])
        else:
            for sym_signals in self.signals.values():
                signals_to_analyze.extend(sym_signals)
        
        if not signals_to_analyze:
            return {
                'total': 0,
                'confirmed': 0,
                'rejected': 0,
                'pending': 0,
                'expired': 0,
                'success_rate': 0,
                'avg_return': 0,
            }
        
        # 统计各状态
        status_counts = {
            ValidationResult.CONFIRMED: 0,
            ValidationResult.REJECTED: 0,
            ValidationResult.PENDING: 0,
            ValidationResult.EXPIRED: 0,
        }
        
        returns = []
        
        for signal in signals_to_analyze:
            status_counts[signal.validation_result] += 1
            if signal.actual_return is not None:
                returns.append(signal.actual_return)
        
        total = len(signals_to_analyze)
        validated = status_counts[ValidationResult.CONFIRMED] + status_counts[ValidationResult.REJECTED]
        
        return {
            'total': total,
            'confirmed': status_counts[ValidationResult.CONFIRMED],
            'rejected': status_counts[ValidationResult.REJECTED],
            'pending': status_counts[ValidationResult.PENDING],
            'expired': status_counts[ValidationResult.EXPIRED],
            'success_rate': status_counts[ValidationResult.CONFIRMED] / validated * 100 if validated > 0 else 0,
            'avg_return': sum(returns) / len(returns) if returns else 0,
        }


class SignalValidator:
    """综合信号验证器"""
    
    def __init__(self):
        self.mtf_validator = MultiTimeframeValidator()
        self.volume_validator = VolumeValidator()
        self.signal_tracker = SignalTracker()
    
    def validate_and_enhance_signal(self, signal: TradingSignal,
                                   daily_data: pd.DataFrame,
                                   weekly_data: pd.DataFrame = None,
                                   monthly_data: pd.DataFrame = None) -> TradingSignal:
        """验证并增强信号
        
        Args:
            signal: 原始信号
            daily_data: 日线数据
            weekly_data: 周线数据
            monthly_data: 月线数据
        
        Returns:
            增强后的信号
        """
        # 多周期验证
        mtf_confirmed, mtf_details = self.mtf_validator.validate_signal(
            signal.symbol, signal.signal_type,
            daily_data, weekly_data, monthly_data
        )
        
        signal.confirm_daily = mtf_details.get('timeframe_results', {}).get('daily', {}).get('confirmed', False)
        
        if weekly_data is not None:
            signal.confirm_weekly = mtf_details.get('timeframe_results', {}).get('weekly', {}).get('confirmed', False)
        
        if monthly_data is not None:
            signal.confirm_monthly = mtf_details.get('timeframe_results', {}).get('monthly', {}).get('confirmed', False)
        
        # 成交量验证
        vol_confirmed, vol_details = self.volume_validator.validate_with_volume(
            daily_data, signal.signal_type
        )
        signal.volume_confirm = vol_confirmed
        
        # 更新信号强度
        confirmation_count = sum([
            signal.confirm_daily,
            signal.confirm_weekly,
            signal.confirm_monthly,
            signal.volume_confirm,
        ])
        
        if confirmation_count >= 3:
            signal.strength = SignalStrength.STRONG
            signal.confidence = min(signal.confidence + 0.2, 1.0)
        elif confirmation_count >= 2:
            signal.strength = SignalStrength.MODERATE
        else:
            signal.strength = SignalStrength.WEAK
            signal.confidence = max(signal.confidence - 0.1, 0.1)
        
        # 添加到追踪器
        self.signal_tracker.add_signal(signal)
        
        return signal
    
    def get_active_signals(self, symbol: str = None) -> List[TradingSignal]:
        """获取活跃信号"""
        if symbol:
            return [
                s for s in self.signal_tracker.signals.get(symbol, [])
                if s.validation_result == ValidationResult.PENDING
            ]
        
        active = []
        for sym_signals in self.signal_tracker.signals.values():
            active.extend([
                s for s in sym_signals
                if s.validation_result == ValidationResult.PENDING
            ])
        
        return active
    
    def get_statistics(self, symbol: str = None) -> Dict:
        """获取信号统计"""
        return self.signal_tracker.get_signal_statistics(symbol)
