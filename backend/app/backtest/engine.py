"""
回测引擎核心模块

提供历史数据回测功能：
- 支持多股票组合回测
- 支持自定义策略
- 计算绩效指标（收益率、夏普比率、最大回撤等）
- 生成交易记录
"""

import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import json

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"       # 市价单
    LIMIT = "limit"         # 限价单


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    """订单"""
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    timestamp: Optional[datetime] = None
    reason: str = ""


@dataclass
class Trade:
    """成交记录"""
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: datetime
    commission: float = 0.0
    reason: str = ""
    
    @property
    def value(self) -> float:
        """交易金额"""
        return self.quantity * self.price
    
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'side': self.side.value,
            'quantity': self.quantity,
            'price': self.price,
            'timestamp': self.timestamp.isoformat(),
            'commission': self.commission,
            'value': self.value,
            'reason': self.reason,
        }


@dataclass
class Position:
    """持仓"""
    symbol: str
    quantity: int
    avg_cost: float
    entry_date: date
    
    @property
    def market_value(self) -> float:
        """市值（需要外部提供价格）"""
        return 0  # 由引擎计算
    
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'quantity': self.quantity,
            'avg_cost': self.avg_cost,
            'entry_date': self.entry_date.isoformat(),
        }


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 100000.0       # 初始资金
    commission_rate: float = 0.0003         # 手续费率（万三）
    slippage: float = 0.001                 # 滑点（0.1%）
    stamp_tax: float = 0.001                # 印花税（卖出时收取，千一）
    min_commission: float = 5.0             # 最低手续费
    trade_unit: int = 100                   # 交易单位（A股100股）
    
    # 风控参数
    max_single_position: float = 0.2        # 单只股票最大仓位
    max_total_position: float = 0.95        # 最大总仓位
    stop_loss_pct: Optional[float] = None   # 止损比例
    take_profit_pct: Optional[float] = None # 止盈比例
    trailing_stop_pct: Optional[float] = None  # 追踪止损比例
    
    # 回测参数
    benchmark: str = "000300.SH"            # 基准指数
    freq: str = "D"                         # 频率：D-日，W-周
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    """回测结果"""
    # 基本信息
    strategy_name: str
    start_date: date
    end_date: date
    config: BacktestConfig
    
    # 绩效指标
    initial_capital: float = 0
    final_value: float = 0
    total_return: float = 0             # 总收益率 %
    annual_return: float = 0            # 年化收益率 %
    
    # 风险指标
    max_drawdown: float = 0             # 最大回撤 %
    max_drawdown_duration: int = 0      # 最大回撤持续天数
    volatility: float = 0               # 波动率 %
    sharpe_ratio: float = 0             # 夏普比率
    sortino_ratio: float = 0            # 索提诺比率
    calmar_ratio: float = 0             # 卡玛比率
    
    # 交易统计
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0                 # 胜率 %
    avg_profit: float = 0               # 平均盈利 %
    avg_loss: float = 0                 # 平均亏损 %
    profit_factor: float = 0            # 盈亏比
    avg_holding_days: float = 0         # 平均持仓天数
    
    # 基准对比
    benchmark_return: float = 0         # 基准收益率 %
    alpha: float = 0
    beta: float = 0
    information_ratio: float = 0        # 信息比率
    
    # 详细数据
    equity_curve: List[Dict] = field(default_factory=list)      # 权益曲线
    trades: List[Dict] = field(default_factory=list)            # 交易记录
    monthly_returns: List[Dict] = field(default_factory=list)   # 月度收益
    positions_history: List[Dict] = field(default_factory=list) # 持仓历史
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['start_date'] = self.start_date.isoformat()
        d['end_date'] = self.end_date.isoformat()
        d['config'] = self.config.to_dict()
        return d
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        
        # 账户状态
        self.cash = self.config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        
        # 历史数据
        self.data: Dict[str, pd.DataFrame] = {}
        self.benchmark_data: Optional[pd.DataFrame] = None
        
        # 回测状态
        self.current_date: Optional[date] = None
        self.equity_history: List[Dict] = []
        self.positions_history: List[Dict] = []
        
        # 追踪止损
        self.highest_price: Dict[str, float] = {}
        
    def load_data(self, symbols: List[str], start_date: date, end_date: date):
        """加载历史数据
        
        Args:
            symbols: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
        """
        from app.data.data_source import DataSource
        
        ds = DataSource()
        
        for symbol in symbols:
            try:
                df = ds.get_price_data(symbol, start_date, end_date)
                if df is not None and not df.empty:
                    self.data[symbol] = df
                    logger.info(f"加载 {symbol} 数据: {len(df)} 条")
            except Exception as e:
                logger.error(f"加载 {symbol} 数据失败: {e}")
        
        # 加载基准数据
        try:
            self.benchmark_data = ds.get_price_data(
                self.config.benchmark, start_date, end_date
            )
        except Exception as e:
            logger.warning(f"加载基准数据失败: {e}")
    
    def load_data_from_df(self, data: Dict[str, pd.DataFrame], 
                          benchmark: pd.DataFrame = None):
        """从DataFrame加载数据
        
        Args:
            data: {symbol: DataFrame} 字典
            benchmark: 基准数据DataFrame
        """
        self.data = data
        self.benchmark_data = benchmark
    
    def get_price(self, symbol: str, dt: date, field: str = 'close') -> Optional[float]:
        """获取指定日期的价格
        
        Args:
            symbol: 股票代码
            dt: 日期
            field: 字段名（open/high/low/close）
        
        Returns:
            价格或None
        """
        if symbol not in self.data:
            return None
        
        df = self.data[symbol]
        
        # 尝试不同的索引方式
        if isinstance(df.index, pd.DatetimeIndex):
            idx = pd.Timestamp(dt)
        else:
            idx = dt
        
        try:
            if idx in df.index:
                return float(df.loc[idx, field])
            # 尝试查找最近的交易日
            mask = df.index <= idx
            if mask.any():
                return float(df.loc[mask].iloc[-1][field])
        except (KeyError, IndexError):
            pass
        
        return None
    
    def get_portfolio_value(self) -> float:
        """计算组合总价值"""
        value = self.cash
        
        for symbol, pos in self.positions.items():
            price = self.get_price(symbol, self.current_date)
            if price:
                value += pos.quantity * price
        
        return value
    
    def get_position_value(self, symbol: str) -> float:
        """获取持仓市值"""
        if symbol not in self.positions:
            return 0
        
        pos = self.positions[symbol]
        price = self.get_price(symbol, self.current_date)
        
        return pos.quantity * price if price else 0
    
    def calculate_commission(self, trade: Trade) -> float:
        """计算交易费用
        
        Args:
            trade: 交易记录
        
        Returns:
            总费用
        """
        value = trade.value
        
        # 手续费
        commission = max(value * self.config.commission_rate, self.config.min_commission)
        
        # 印花税（仅卖出收取）
        stamp_tax = 0
        if trade.side == OrderSide.SELL:
            stamp_tax = value * self.config.stamp_tax
        
        return commission + stamp_tax
    
    def execute_order(self, order: Order) -> Optional[Trade]:
        """执行订单
        
        Args:
            order: 订单
        
        Returns:
            成交记录或None
        """
        # 获取执行价格
        if order.order_type == OrderType.MARKET:
            # 市价单使用当日开盘价 + 滑点
            price = self.get_price(order.symbol, self.current_date, 'open')
            if price is None:
                logger.warning(f"无法获取 {order.symbol} 在 {self.current_date} 的价格")
                return None
            
            # 加入滑点
            if order.side == OrderSide.BUY:
                price *= (1 + self.config.slippage)
            else:
                price *= (1 - self.config.slippage)
        else:
            price = order.price
        
        # 数量调整为交易单位的整数倍
        quantity = (order.quantity // self.config.trade_unit) * self.config.trade_unit
        if quantity <= 0:
            return None
        
        # 创建交易记录
        trade = Trade(
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=price,
            timestamp=datetime.combine(self.current_date, datetime.min.time()),
            reason=order.reason,
        )
        trade.commission = self.calculate_commission(trade)
        
        # 检查资金/持仓
        if order.side == OrderSide.BUY:
            required = trade.value + trade.commission
            if required > self.cash:
                # 资金不足，调整数量
                max_quantity = int((self.cash * 0.99 - self.config.min_commission) / price)
                max_quantity = (max_quantity // self.config.trade_unit) * self.config.trade_unit
                if max_quantity <= 0:
                    logger.warning(f"资金不足，无法买入 {order.symbol}")
                    return None
                quantity = max_quantity
                trade.quantity = quantity
                trade.commission = self.calculate_commission(trade)
            
            # 更新持仓
            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                total_cost = pos.quantity * pos.avg_cost + quantity * price
                total_quantity = pos.quantity + quantity
                pos.avg_cost = total_cost / total_quantity
                pos.quantity = total_quantity
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=quantity,
                    avg_cost=price,
                    entry_date=self.current_date,
                )
            
            # 更新现金
            self.cash -= (trade.value + trade.commission)
            
            # 初始化追踪止损
            self.highest_price[order.symbol] = price
            
        else:  # SELL
            if order.symbol not in self.positions:
                logger.warning(f"无持仓，无法卖出 {order.symbol}")
                return None
            
            pos = self.positions[order.symbol]
            if quantity > pos.quantity:
                quantity = pos.quantity
                trade.quantity = quantity
                trade.commission = self.calculate_commission(trade)
            
            # 更新持仓
            pos.quantity -= quantity
            if pos.quantity <= 0:
                del self.positions[order.symbol]
                if order.symbol in self.highest_price:
                    del self.highest_price[order.symbol]
            
            # 更新现金
            self.cash += (trade.value - trade.commission)
        
        # 记录交易
        self.trades.append(trade)
        
        return trade
    
    def check_risk_management(self):
        """检查风控条件，执行止损止盈"""
        orders = []
        
        for symbol, pos in list(self.positions.items()):
            current_price = self.get_price(symbol, self.current_date)
            if current_price is None:
                continue
            
            # 更新最高价（用于追踪止损）
            if symbol in self.highest_price:
                self.highest_price[symbol] = max(self.highest_price[symbol], current_price)
            
            pnl_pct = (current_price - pos.avg_cost) / pos.avg_cost
            
            # 固定止损
            if self.config.stop_loss_pct and pnl_pct <= -self.config.stop_loss_pct:
                orders.append(Order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    reason=f"止损触发: {pnl_pct*100:.2f}%"
                ))
                continue
            
            # 追踪止损
            if self.config.trailing_stop_pct and symbol in self.highest_price:
                trailing_pnl = (current_price - self.highest_price[symbol]) / self.highest_price[symbol]
                if trailing_pnl <= -self.config.trailing_stop_pct:
                    orders.append(Order(
                        symbol=symbol,
                        side=OrderSide.SELL,
                        quantity=pos.quantity,
                        reason=f"追踪止损触发: 从最高点回落 {trailing_pnl*100:.2f}%"
                    ))
                    continue
            
            # 止盈
            if self.config.take_profit_pct and pnl_pct >= self.config.take_profit_pct:
                orders.append(Order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    reason=f"止盈触发: {pnl_pct*100:.2f}%"
                ))
        
        # 执行止损止盈订单
        for order in orders:
            self.execute_order(order)
    
    def run(self, strategy, symbols: List[str], 
            start_date: date, end_date: date) -> BacktestResult:
        """运行回测
        
        Args:
            strategy: 策略对象（需要实现 on_bar 方法）
            symbols: 股票列表
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            回测结果
        """
        # 重置状态
        self.cash = self.config.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_history = []
        self.positions_history = []
        self.highest_price = {}
        
        # 加载数据
        if not self.data:
            self.load_data(symbols, start_date, end_date)
        
        # 获取所有交易日
        all_dates = set()
        for df in self.data.values():
            if isinstance(df.index, pd.DatetimeIndex):
                all_dates.update(df.index.date)
            else:
                all_dates.update(df.index)
        
        trade_dates = sorted([d for d in all_dates if start_date <= d <= end_date])
        
        if not trade_dates:
            logger.warning("没有可回测的交易日")
            return self._create_result(strategy.name, start_date, end_date)
        
        logger.info(f"开始回测: {start_date} - {end_date}, 共 {len(trade_dates)} 个交易日")
        
        # 策略初始化
        strategy.initialize(self)
        
        # 按日期遍历
        for dt in trade_dates:
            self.current_date = dt
            
            # 检查风控（止损止盈）
            self.check_risk_management()
            
            # 准备当日数据
            bar_data = {}
            for symbol in symbols:
                if symbol in self.data:
                    df = self.data[symbol]
                    idx = pd.Timestamp(dt) if isinstance(df.index, pd.DatetimeIndex) else dt
                    if idx in df.index:
                        bar_data[symbol] = df.loc[idx].to_dict()
            
            # 调用策略
            if bar_data:
                try:
                    orders = strategy.on_bar(self, dt, bar_data)
                    if orders:
                        for order in orders:
                            self.execute_order(order)
                except Exception as e:
                    logger.error(f"策略执行错误 @ {dt}: {e}")
            
            # 记录权益
            portfolio_value = self.get_portfolio_value()
            self.equity_history.append({
                'date': dt.isoformat(),
                'value': portfolio_value,
                'cash': self.cash,
                'positions': len(self.positions),
            })
            
            # 记录持仓
            positions_snapshot = {
                'date': dt.isoformat(),
                'positions': [pos.to_dict() for pos in self.positions.values()]
            }
            self.positions_history.append(positions_snapshot)
        
        # 策略结束
        strategy.finalize(self)
        
        # 计算结果
        return self._create_result(strategy.name, start_date, end_date)
    
    def _create_result(self, strategy_name: str, 
                       start_date: date, end_date: date) -> BacktestResult:
        """创建回测结果"""
        from .performance import PerformanceAnalyzer
        
        result = BacktestResult(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            config=self.config,
            initial_capital=self.config.initial_capital,
        )
        
        # 权益曲线
        result.equity_curve = self.equity_history
        result.trades = [t.to_dict() for t in self.trades]
        result.positions_history = self.positions_history
        
        if not self.equity_history:
            return result
        
        # 基本绩效
        result.final_value = self.equity_history[-1]['value']
        result.total_return = (result.final_value / result.initial_capital - 1) * 100
        
        # 使用绩效分析器 - 传入字典列表而非 Trade 对象
        trades_as_dicts = [t.to_dict() for t in self.trades]
        analyzer = PerformanceAnalyzer(self.equity_history, trades_as_dicts)
        
        # 年化收益
        days = (end_date - start_date).days
        if days > 0:
            result.annual_return = (pow(result.final_value / result.initial_capital, 
                                        365 / days) - 1) * 100
        
        # 风险指标
        result.max_drawdown = analyzer.max_drawdown()
        result.volatility = analyzer.volatility()
        result.sharpe_ratio = analyzer.sharpe_ratio()
        result.sortino_ratio = analyzer.sortino_ratio()
        result.calmar_ratio = analyzer.calmar_ratio()
        
        # 交易统计
        trade_stats = analyzer.trade_statistics()
        result.total_trades = trade_stats['total_trades']
        result.winning_trades = trade_stats['winning_trades']
        result.losing_trades = trade_stats['losing_trades']
        result.win_rate = trade_stats['win_rate']
        result.avg_profit = trade_stats['avg_profit']
        result.avg_loss = trade_stats['avg_loss']
        result.profit_factor = trade_stats['profit_factor']
        result.avg_holding_days = trade_stats['avg_holding_days']
        
        # 月度收益
        result.monthly_returns = analyzer.monthly_returns()
        
        # 基准对比
        if self.benchmark_data is not None and not self.benchmark_data.empty:
            benchmark_stats = analyzer.benchmark_comparison(self.benchmark_data)
            result.benchmark_return = benchmark_stats['benchmark_return']
            result.alpha = benchmark_stats['alpha']
            result.beta = benchmark_stats['beta']
            result.information_ratio = benchmark_stats['information_ratio']
        
        return result
