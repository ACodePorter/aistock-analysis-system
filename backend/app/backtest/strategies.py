"""
回测策略模块

提供回测策略基类和常用策略实现
"""

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional, Any

from .engine import Order, OrderSide, OrderType

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.params = {}
    
    def initialize(self, engine):
        """策略初始化（回测开始时调用）"""
        pass
    
    @abstractmethod
    def on_bar(self, engine, dt: date, bar_data: Dict[str, Dict]) -> List[Order]:
        """处理每日数据
        
        Args:
            engine: 回测引擎实例
            dt: 当前日期
            bar_data: 当日行情数据 {symbol: {open, high, low, close, volume, ...}}
        
        Returns:
            订单列表
        """
        pass
    
    def finalize(self, engine):
        """策略结束（回测结束时调用）"""
        pass
    
    def calculate_position_size(self, engine, symbol: str, 
                                price: float, signal_strength: float = 1.0) -> int:
        """计算仓位大小
        
        Args:
            engine: 回测引擎
            symbol: 股票代码
            price: 当前价格
            signal_strength: 信号强度 0-1
        
        Returns:
            买入数量
        """
        # 计算可用资金
        available = engine.cash * engine.config.max_single_position
        
        # 信号强度调整
        available *= signal_strength
        
        # 计算可买数量
        quantity = int(available / price)
        
        # 调整为交易单位的整数倍
        quantity = (quantity // engine.config.trade_unit) * engine.config.trade_unit
        
        return quantity


class SignalStrategy(BaseStrategy):
    """基于信号的策略
    
    使用分析系统生成的信号进行交易
    """
    
    def __init__(self, signals: Dict[str, Dict[date, Dict]], 
                 buy_threshold: float = 70,
                 sell_threshold: float = 40,
                 name: str = "SignalStrategy"):
        """
        Args:
            signals: 信号数据 {symbol: {date: {score, recommendation, ...}}}
            buy_threshold: 买入阈值（评分大于此值买入）
            sell_threshold: 卖出阈值（评分小于此值卖出）
        """
        super().__init__(name)
        self.signals = signals
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
    
    def on_bar(self, engine, dt: date, bar_data: Dict[str, Dict]) -> List[Order]:
        orders = []
        
        for symbol, data in bar_data.items():
            if symbol not in self.signals:
                continue
            
            signal = self.signals[symbol].get(dt)
            if not signal:
                continue
            
            score = signal.get('score', 50)
            recommendation = signal.get('recommendation', 'hold')
            
            # 持仓检查
            has_position = symbol in engine.positions
            
            # 买入信号
            if not has_position and (score >= self.buy_threshold or recommendation == 'buy'):
                price = data.get('close', 0)
                if price > 0:
                    quantity = self.calculate_position_size(
                        engine, symbol, price, 
                        signal_strength=min(score / 100, 1.0)
                    )
                    if quantity > 0:
                        orders.append(Order(
                            symbol=symbol,
                            side=OrderSide.BUY,
                            quantity=quantity,
                            reason=f"信号买入: score={score}, rec={recommendation}"
                        ))
            
            # 卖出信号
            elif has_position and (score < self.sell_threshold or recommendation == 'sell'):
                pos = engine.positions[symbol]
                orders.append(Order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    reason=f"信号卖出: score={score}, rec={recommendation}"
                ))
        
        return orders


class MACrossStrategy(BaseStrategy):
    """均线交叉策略
    
    金叉买入，死叉卖出
    """
    
    def __init__(self, fast_period: int = 5, slow_period: int = 20, 
                 name: str = "MACrossStrategy"):
        """
        Args:
            fast_period: 快线周期
            slow_period: 慢线周期
        """
        super().__init__(name)
        self.fast_period = fast_period
        self.slow_period = slow_period
        
        # 历史数据缓存
        self.price_history: Dict[str, List[float]] = {}
        self.prev_cross: Dict[str, str] = {}  # 上一次交叉状态
    
    def on_bar(self, engine, dt: date, bar_data: Dict[str, Dict]) -> List[Order]:
        orders = []
        
        for symbol, data in bar_data.items():
            close = data.get('close')
            if close is None:
                continue
            
            # 更新价格历史
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(close)
            
            # 保留足够的历史
            max_len = self.slow_period + 10
            if len(self.price_history[symbol]) > max_len:
                self.price_history[symbol] = self.price_history[symbol][-max_len:]
            
            # 计算均线
            prices = self.price_history[symbol]
            if len(prices) < self.slow_period:
                continue
            
            fast_ma = sum(prices[-self.fast_period:]) / self.fast_period
            slow_ma = sum(prices[-self.slow_period:]) / self.slow_period
            
            # 判断交叉
            current_cross = 'golden' if fast_ma > slow_ma else 'death'
            prev_cross = self.prev_cross.get(symbol)
            self.prev_cross[symbol] = current_cross
            
            if prev_cross is None:
                continue
            
            has_position = symbol in engine.positions
            
            # 金叉买入
            if prev_cross == 'death' and current_cross == 'golden' and not has_position:
                quantity = self.calculate_position_size(engine, symbol, close)
                if quantity > 0:
                    orders.append(Order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=quantity,
                        reason=f"金叉买入: MA{self.fast_period}={fast_ma:.2f} > MA{self.slow_period}={slow_ma:.2f}"
                    ))
            
            # 死叉卖出
            elif prev_cross == 'golden' and current_cross == 'death' and has_position:
                pos = engine.positions[symbol]
                orders.append(Order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    reason=f"死叉卖出: MA{self.fast_period}={fast_ma:.2f} < MA{self.slow_period}={slow_ma:.2f}"
                ))
        
        return orders


class RSIStrategy(BaseStrategy):
    """RSI超买超卖策略"""
    
    def __init__(self, period: int = 14, 
                 oversold: float = 30, overbought: float = 70,
                 name: str = "RSIStrategy"):
        """
        Args:
            period: RSI周期
            oversold: 超卖阈值
            overbought: 超买阈值
        """
        super().__init__(name)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        
        self.price_history: Dict[str, List[float]] = {}
    
    def calculate_rsi(self, prices: List[float]) -> Optional[float]:
        """计算RSI"""
        if len(prices) < self.period + 1:
            return None
        
        # 计算价格变化
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # 取最近period个变化
        recent_changes = changes[-self.period:]
        
        gains = [c for c in recent_changes if c > 0]
        losses = [-c for c in recent_changes if c < 0]
        
        avg_gain = sum(gains) / self.period if gains else 0
        avg_loss = sum(losses) / self.period if losses else 0
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def on_bar(self, engine, dt: date, bar_data: Dict[str, Dict]) -> List[Order]:
        orders = []
        
        for symbol, data in bar_data.items():
            close = data.get('close')
            if close is None:
                continue
            
            # 更新价格历史
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(close)
            
            # 保留足够的历史
            max_len = self.period + 20
            if len(self.price_history[symbol]) > max_len:
                self.price_history[symbol] = self.price_history[symbol][-max_len:]
            
            # 计算RSI
            rsi = self.calculate_rsi(self.price_history[symbol])
            if rsi is None:
                continue
            
            has_position = symbol in engine.positions
            
            # 超卖买入
            if rsi < self.oversold and not has_position:
                quantity = self.calculate_position_size(engine, symbol, close)
                if quantity > 0:
                    orders.append(Order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=quantity,
                        reason=f"RSI超卖买入: RSI={rsi:.2f} < {self.oversold}"
                    ))
            
            # 超买卖出
            elif rsi > self.overbought and has_position:
                pos = engine.positions[symbol]
                orders.append(Order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    reason=f"RSI超买卖出: RSI={rsi:.2f} > {self.overbought}"
                ))
        
        return orders


class CompositeStrategy(BaseStrategy):
    """组合策略
    
    组合多个策略，通过投票或加权方式决定交易
    """
    
    def __init__(self, strategies: List[BaseStrategy], 
                 voting_threshold: float = 0.5,
                 name: str = "CompositeStrategy"):
        """
        Args:
            strategies: 子策略列表
            voting_threshold: 投票阈值（超过此比例的策略同意才交易）
        """
        super().__init__(name)
        self.strategies = strategies
        self.voting_threshold = voting_threshold
    
    def initialize(self, engine):
        for strategy in self.strategies:
            strategy.initialize(engine)
    
    def on_bar(self, engine, dt: date, bar_data: Dict[str, Dict]) -> List[Order]:
        # 收集所有策略的订单
        all_orders: Dict[str, Dict[str, List[Order]]] = {}  # symbol -> side -> orders
        
        for strategy in self.strategies:
            orders = strategy.on_bar(engine, dt, bar_data)
            for order in orders:
                if order.symbol not in all_orders:
                    all_orders[order.symbol] = {'buy': [], 'sell': []}
                all_orders[order.symbol][order.side.value].append(order)
        
        # 投票决定
        final_orders = []
        threshold = len(self.strategies) * self.voting_threshold
        
        for symbol, sides in all_orders.items():
            # 买入投票
            if len(sides['buy']) >= threshold:
                # 取平均数量
                avg_quantity = sum(o.quantity for o in sides['buy']) // len(sides['buy'])
                if avg_quantity > 0:
                    final_orders.append(Order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=avg_quantity,
                        reason=f"组合策略买入: {len(sides['buy'])}/{len(self.strategies)}策略同意"
                    ))
            
            # 卖出投票
            if len(sides['sell']) >= threshold:
                # 取最大数量
                max_quantity = max(o.quantity for o in sides['sell'])
                final_orders.append(Order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=max_quantity,
                    reason=f"组合策略卖出: {len(sides['sell'])}/{len(self.strategies)}策略同意"
                ))
        
        return final_orders
    
    def finalize(self, engine):
        for strategy in self.strategies:
            strategy.finalize(engine)
