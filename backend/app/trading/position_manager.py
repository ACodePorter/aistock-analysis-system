"""
仓位管理模块

提供多种仓位管理策略：
- 固定比例仓位
- Kelly公式仓位
- 波动率加权仓位
- 等权重仓位
- 风险平价仓位

同时包含风险控制功能：
- 止盈止损管理
- 最大回撤控制
- 相关性分析
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PositionSizingMethod(str, Enum):
    """仓位管理方法"""
    FIXED_RATIO = "fixed_ratio"         # 固定比例
    KELLY = "kelly"                      # Kelly公式
    VOLATILITY = "volatility"            # 波动率加权
    EQUAL_WEIGHT = "equal_weight"        # 等权重
    RISK_PARITY = "risk_parity"          # 风险平价


class StopLossType(str, Enum):
    """止损类型"""
    FIXED = "fixed"                      # 固定止损
    TRAILING = "trailing"                # 追踪止损
    ATR = "atr"                          # ATR止损
    VOLATILITY = "volatility"            # 波动率止损


@dataclass
class RiskConfig:
    """风控配置"""
    # 仓位限制
    max_single_position: float = 0.2     # 单只最大仓位 20%
    min_single_position: float = 0.02    # 单只最小仓位 2%
    max_total_position: float = 0.95     # 最大总仓位 95%
    max_sector_position: float = 0.3     # 行业最大仓位 30%
    max_positions: int = 10              # 最大持仓股票数
    
    # 止损止盈
    stop_loss_pct: float = 0.08          # 止损 8%
    take_profit_pct: float = 0.20        # 止盈 20%
    trailing_stop_pct: float = 0.10      # 追踪止损 10%
    
    # 风险限制
    max_daily_loss: float = 0.03         # 单日最大亏损 3%
    max_drawdown: float = 0.15           # 最大回撤 15%
    
    # Kelly参数
    kelly_fraction: float = 0.5          # Kelly系数折扣（一般用半Kelly）


class PositionManager:
    """仓位管理器"""
    
    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        
        # 持仓记录
        self.positions: Dict[str, Dict] = {}  # symbol -> {quantity, avg_cost, entry_date, highest_price, ...}
        
        # 风控状态
        self.daily_pnl = 0.0
        self.peak_value = 0.0
        self.current_drawdown = 0.0
        
        # 历史数据缓存
        self.returns_cache: Dict[str, List[float]] = {}
    
    def calculate_fixed_ratio_size(self, capital: float, price: float,
                                   ratio: float = None) -> int:
        """固定比例仓位
        
        Args:
            capital: 可用资金
            price: 当前价格
            ratio: 仓位比例，默认使用配置的max_single_position
        
        Returns:
            买入数量（100股的整数倍）
        """
        ratio = ratio or self.config.max_single_position
        
        position_value = capital * ratio
        quantity = int(position_value / price / 100) * 100
        
        return max(quantity, 0)
    
    def calculate_kelly_size(self, capital: float, price: float,
                            win_rate: float, avg_win: float, 
                            avg_loss: float) -> int:
        """Kelly公式仓位
        
        Kelly% = W - (1-W) / R
        W = 胜率
        R = 盈亏比 = 平均盈利 / 平均亏损
        
        Args:
            capital: 可用资金
            price: 当前价格
            win_rate: 胜率 (0-1)
            avg_win: 平均盈利比例
            avg_loss: 平均亏损比例
        
        Returns:
            买入数量
        """
        if avg_loss <= 0:
            return 0
        
        # 盈亏比
        r = avg_win / avg_loss
        
        # Kelly比例
        kelly = win_rate - (1 - win_rate) / r
        
        # 限制范围并应用折扣
        kelly = max(0, min(kelly, 0.5))  # 限制在0-50%
        kelly *= self.config.kelly_fraction  # 应用半Kelly
        
        # 再限制在最大单只仓位
        kelly = min(kelly, self.config.max_single_position)
        
        position_value = capital * kelly
        quantity = int(position_value / price / 100) * 100
        
        return max(quantity, 0)
    
    def calculate_volatility_size(self, capital: float, price: float,
                                  volatility: float, 
                                  target_vol: float = 0.15) -> int:
        """波动率加权仓位
        
        仓位 = 目标波动率 / 股票波动率 * 基础仓位
        
        Args:
            capital: 可用资金
            price: 当前价格
            volatility: 股票年化波动率
            target_vol: 目标波动率（组合层面）
        
        Returns:
            买入数量
        """
        if volatility <= 0:
            return 0
        
        # 波动率调整因子
        vol_factor = target_vol / volatility
        
        # 基础仓位
        base_ratio = self.config.max_single_position
        
        # 调整后仓位（限制范围）
        ratio = min(base_ratio * vol_factor, self.config.max_single_position)
        ratio = max(ratio, self.config.min_single_position)
        
        position_value = capital * ratio
        quantity = int(position_value / price / 100) * 100
        
        return max(quantity, 0)
    
    def calculate_equal_weight_size(self, capital: float, price: float,
                                    num_stocks: int) -> int:
        """等权重仓位
        
        Args:
            capital: 可用资金
            price: 当前价格
            num_stocks: 股票数量
        
        Returns:
            买入数量
        """
        if num_stocks <= 0:
            return 0
        
        # 等权重分配
        weight = 1.0 / num_stocks
        
        # 限制最大单只仓位
        weight = min(weight, self.config.max_single_position)
        
        position_value = capital * weight
        quantity = int(position_value / price / 100) * 100
        
        return max(quantity, 0)
    
    def calculate_position_size(self, method: PositionSizingMethod,
                               capital: float, price: float,
                               **kwargs) -> int:
        """统一计算仓位大小入口
        
        Args:
            method: 仓位管理方法
            capital: 可用资金
            price: 当前价格
            **kwargs: 方法特定参数
        
        Returns:
            买入数量
        """
        if method == PositionSizingMethod.FIXED_RATIO:
            return self.calculate_fixed_ratio_size(
                capital, price, kwargs.get('ratio')
            )
        
        elif method == PositionSizingMethod.KELLY:
            return self.calculate_kelly_size(
                capital, price,
                kwargs.get('win_rate', 0.5),
                kwargs.get('avg_win', 0.05),
                kwargs.get('avg_loss', 0.03)
            )
        
        elif method == PositionSizingMethod.VOLATILITY:
            return self.calculate_volatility_size(
                capital, price,
                kwargs.get('volatility', 0.3),
                kwargs.get('target_vol', 0.15)
            )
        
        elif method == PositionSizingMethod.EQUAL_WEIGHT:
            return self.calculate_equal_weight_size(
                capital, price,
                kwargs.get('num_stocks', 10)
            )
        
        else:
            return self.calculate_fixed_ratio_size(capital, price)
    
    def check_stop_loss(self, symbol: str, current_price: float) -> Tuple[bool, str]:
        """检查止损条件
        
        Args:
            symbol: 股票代码
            current_price: 当前价格
        
        Returns:
            (是否触发止损, 原因)
        """
        if symbol not in self.positions:
            return False, ""
        
        pos = self.positions[symbol]
        avg_cost = pos.get('avg_cost', 0)
        highest_price = pos.get('highest_price', avg_cost)
        
        if avg_cost <= 0:
            return False, ""
        
        # 盈亏比例
        pnl_pct = (current_price - avg_cost) / avg_cost
        
        # 固定止损
        if pnl_pct <= -self.config.stop_loss_pct:
            return True, f"固定止损触发: 亏损{pnl_pct*100:.2f}% > {self.config.stop_loss_pct*100:.1f}%"
        
        # 追踪止损（仅在盈利时启用）
        if highest_price > avg_cost:
            trailing_pnl = (current_price - highest_price) / highest_price
            if trailing_pnl <= -self.config.trailing_stop_pct:
                return True, f"追踪止损触发: 从最高点{highest_price:.2f}回落{trailing_pnl*100:.2f}%"
        
        return False, ""
    
    def check_take_profit(self, symbol: str, current_price: float) -> Tuple[bool, str]:
        """检查止盈条件
        
        Args:
            symbol: 股票代码
            current_price: 当前价格
        
        Returns:
            (是否触发止盈, 原因)
        """
        if symbol not in self.positions:
            return False, ""
        
        pos = self.positions[symbol]
        avg_cost = pos.get('avg_cost', 0)
        
        if avg_cost <= 0:
            return False, ""
        
        pnl_pct = (current_price - avg_cost) / avg_cost
        
        if pnl_pct >= self.config.take_profit_pct:
            return True, f"止盈触发: 盈利{pnl_pct*100:.2f}% >= {self.config.take_profit_pct*100:.1f}%"
        
        return False, ""
    
    def update_position(self, symbol: str, quantity: int, price: float,
                       entry_date: date = None):
        """更新持仓
        
        Args:
            symbol: 股票代码
            quantity: 数量（正数买入，负数卖出）
            price: 价格
            entry_date: 建仓日期
        """
        if symbol not in self.positions:
            if quantity > 0:
                self.positions[symbol] = {
                    'quantity': quantity,
                    'avg_cost': price,
                    'entry_date': entry_date or date.today(),
                    'highest_price': price,
                    'unrealized_pnl': 0,
                }
        else:
            pos = self.positions[symbol]
            
            if quantity > 0:  # 买入
                total_cost = pos['quantity'] * pos['avg_cost'] + quantity * price
                total_quantity = pos['quantity'] + quantity
                pos['avg_cost'] = total_cost / total_quantity
                pos['quantity'] = total_quantity
            else:  # 卖出
                pos['quantity'] += quantity  # quantity是负数
                
                if pos['quantity'] <= 0:
                    del self.positions[symbol]
                    return
            
            # 更新最高价
            pos['highest_price'] = max(pos.get('highest_price', price), price)
    
    def update_prices(self, prices: Dict[str, float]):
        """更新持仓市价
        
        Args:
            prices: {symbol: price}
        """
        for symbol, pos in self.positions.items():
            if symbol in prices:
                current_price = prices[symbol]
                
                # 更新最高价
                pos['highest_price'] = max(pos.get('highest_price', current_price), current_price)
                
                # 更新未实现盈亏
                pos['unrealized_pnl'] = (current_price - pos['avg_cost']) * pos['quantity']
    
    def check_portfolio_risk(self, portfolio_value: float) -> List[str]:
        """检查组合风险
        
        Args:
            portfolio_value: 组合总价值
        
        Returns:
            风险警告列表
        """
        warnings = []
        
        # 检查最大回撤
        if portfolio_value > self.peak_value:
            self.peak_value = portfolio_value
        
        if self.peak_value > 0:
            self.current_drawdown = (self.peak_value - portfolio_value) / self.peak_value
            
            if self.current_drawdown >= self.config.max_drawdown:
                warnings.append(f"最大回撤警告: {self.current_drawdown*100:.2f}% >= {self.config.max_drawdown*100:.1f}%")
        
        # 检查持仓数量
        if len(self.positions) > self.config.max_positions:
            warnings.append(f"持仓数量警告: {len(self.positions)} > {self.config.max_positions}")
        
        # 检查单只持仓比例
        for symbol, pos in self.positions.items():
            position_value = pos['quantity'] * pos.get('current_price', pos['avg_cost'])
            weight = position_value / portfolio_value if portfolio_value > 0 else 0
            
            if weight > self.config.max_single_position:
                warnings.append(f"{symbol} 仓位过重: {weight*100:.2f}% > {self.config.max_single_position*100:.1f}%")
        
        return warnings
    
    def get_rebalance_orders(self, target_weights: Dict[str, float],
                            current_prices: Dict[str, float],
                            portfolio_value: float) -> List[Dict]:
        """生成再平衡订单
        
        Args:
            target_weights: 目标权重 {symbol: weight}
            current_prices: 当前价格 {symbol: price}
            portfolio_value: 组合总价值
        
        Returns:
            订单列表 [{'symbol', 'side', 'quantity', 'reason'}, ...]
        """
        orders = []
        
        # 计算当前权重
        current_weights = {}
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol, pos['avg_cost'])
            value = pos['quantity'] * price
            current_weights[symbol] = value / portfolio_value if portfolio_value > 0 else 0
        
        # 生成调仓订单
        all_symbols = set(target_weights.keys()) | set(current_weights.keys())
        
        for symbol in all_symbols:
            target = target_weights.get(symbol, 0)
            current = current_weights.get(symbol, 0)
            price = current_prices.get(symbol)
            
            if price is None or price <= 0:
                continue
            
            diff = target - current
            
            # 忽略小幅变动（小于1%）
            if abs(diff) < 0.01:
                continue
            
            # 计算调整数量
            target_value = portfolio_value * diff
            quantity = int(abs(target_value) / price / 100) * 100
            
            if quantity <= 0:
                continue
            
            if diff > 0:
                orders.append({
                    'symbol': symbol,
                    'side': 'buy',
                    'quantity': quantity,
                    'reason': f'再平衡买入: 目标{target*100:.1f}%, 当前{current*100:.1f}%'
                })
            else:
                orders.append({
                    'symbol': symbol,
                    'side': 'sell',
                    'quantity': quantity,
                    'reason': f'再平衡卖出: 目标{target*100:.1f}%, 当前{current*100:.1f}%'
                })
        
        return orders
    
    def calculate_var(self, returns: List[float], confidence: float = 0.95) -> float:
        """计算VaR（风险价值）
        
        Args:
            returns: 收益率序列
            confidence: 置信度
        
        Returns:
            VaR值（负数表示亏损）
        """
        if not returns:
            return 0
        
        return float(np.percentile(returns, (1 - confidence) * 100))
    
    def get_position_summary(self) -> Dict:
        """获取持仓摘要"""
        total_value = sum(
            pos['quantity'] * pos.get('current_price', pos['avg_cost'])
            for pos in self.positions.values()
        )
        
        total_unrealized_pnl = sum(
            pos.get('unrealized_pnl', 0)
            for pos in self.positions.values()
        )
        
        return {
            'position_count': len(self.positions),
            'total_value': total_value,
            'total_unrealized_pnl': total_unrealized_pnl,
            'current_drawdown': self.current_drawdown,
            'positions': [
                {
                    'symbol': symbol,
                    'quantity': pos['quantity'],
                    'avg_cost': pos['avg_cost'],
                    'current_price': pos.get('current_price', pos['avg_cost']),
                    'unrealized_pnl': pos.get('unrealized_pnl', 0),
                    'entry_date': pos['entry_date'].isoformat() if isinstance(pos['entry_date'], date) else pos['entry_date'],
                }
                for symbol, pos in self.positions.items()
            ]
        }
