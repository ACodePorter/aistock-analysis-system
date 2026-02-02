"""
绩效分析模块

计算回测绩效指标：
- 收益率指标（总收益、年化收益、月度收益）
- 风险指标（最大回撤、波动率、夏普比率、索提诺比率）
- 交易统计（胜率、盈亏比、平均持仓天数）
- 基准对比（Alpha、Beta、信息比率）
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """绩效分析器"""
    
    def __init__(self, equity_curve: List[Dict], trades: List[Dict] = None,
                 risk_free_rate: float = 0.03):
        """
        Args:
            equity_curve: 权益曲线 [{'date': str, 'value': float, ...}, ...]
            trades: 交易记录 [{'symbol', 'side', 'quantity', 'price', 'timestamp'}, ...]
            risk_free_rate: 无风险利率（年化）
        """
        self.equity_curve = equity_curve
        self.trades = trades or []
        self.risk_free_rate = risk_free_rate
        
        # 转换为DataFrame
        self.equity_df = pd.DataFrame(equity_curve)
        if not self.equity_df.empty:
            self.equity_df['date'] = pd.to_datetime(self.equity_df['date'])
            self.equity_df.set_index('date', inplace=True)
            self.equity_df.sort_index(inplace=True)
            
            # 计算日收益率
            self.equity_df['return'] = self.equity_df['value'].pct_change()
    
    def total_return(self) -> float:
        """总收益率（%）"""
        if self.equity_df.empty:
            return 0
        
        initial = self.equity_df['value'].iloc[0]
        final = self.equity_df['value'].iloc[-1]
        
        return (final / initial - 1) * 100
    
    def annual_return(self) -> float:
        """年化收益率（%）"""
        if self.equity_df.empty:
            return 0
        
        initial = self.equity_df['value'].iloc[0]
        final = self.equity_df['value'].iloc[-1]
        
        days = (self.equity_df.index[-1] - self.equity_df.index[0]).days
        if days <= 0:
            return 0
        
        return (pow(final / initial, 365 / days) - 1) * 100
    
    def max_drawdown(self) -> float:
        """最大回撤（%）"""
        if self.equity_df.empty:
            return 0
        
        values = self.equity_df['value']
        peak = values.expanding(min_periods=1).max()
        drawdown = (values - peak) / peak
        
        return abs(drawdown.min()) * 100
    
    def max_drawdown_duration(self) -> int:
        """最大回撤持续天数"""
        if self.equity_df.empty:
            return 0
        
        values = self.equity_df['value']
        peak = values.expanding(min_periods=1).max()
        drawdown = (values - peak) / peak
        
        # 找到回撤开始和恢复的位置
        in_drawdown = drawdown < 0
        
        if not in_drawdown.any():
            return 0
        
        # 计算连续回撤天数
        max_duration = 0
        current_duration = 0
        
        for is_dd in in_drawdown:
            if is_dd:
                current_duration += 1
            else:
                max_duration = max(max_duration, current_duration)
                current_duration = 0
        
        return max(max_duration, current_duration)
    
    def volatility(self, annualize: bool = True) -> float:
        """波动率（%）
        
        Args:
            annualize: 是否年化
        
        Returns:
            波动率百分比
        """
        if self.equity_df.empty or 'return' not in self.equity_df.columns:
            return 0
        
        returns = self.equity_df['return'].dropna()
        if returns.empty:
            return 0
        
        vol = returns.std()
        
        if annualize:
            vol *= np.sqrt(252)  # 年化
        
        return vol * 100
    
    def sharpe_ratio(self) -> float:
        """夏普比率
        
        Sharpe = (年化收益 - 无风险利率) / 年化波动率
        """
        if self.equity_df.empty:
            return 0
        
        annual_ret = self.annual_return() / 100
        vol = self.volatility() / 100
        
        if vol == 0:
            return 0
        
        return (annual_ret - self.risk_free_rate) / vol
    
    def sortino_ratio(self) -> float:
        """索提诺比率
        
        只考虑下行波动率
        """
        if self.equity_df.empty or 'return' not in self.equity_df.columns:
            return 0
        
        returns = self.equity_df['return'].dropna()
        if returns.empty:
            return 0
        
        # 下行波动率
        negative_returns = returns[returns < 0]
        if negative_returns.empty:
            return float('inf')
        
        downside_vol = negative_returns.std() * np.sqrt(252)
        
        if downside_vol == 0:
            return 0
        
        annual_ret = self.annual_return() / 100
        
        return (annual_ret - self.risk_free_rate) / downside_vol
    
    def calmar_ratio(self) -> float:
        """卡玛比率
        
        Calmar = 年化收益 / 最大回撤
        """
        max_dd = self.max_drawdown()
        if max_dd == 0:
            return 0
        
        annual_ret = self.annual_return()
        
        return annual_ret / max_dd
    
    def trade_statistics(self) -> Dict:
        """交易统计"""
        stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'avg_profit': 0,
            'avg_loss': 0,
            'profit_factor': 0,
            'avg_holding_days': 0,
        }
        
        if not self.trades:
            return stats
        
        # 按股票分组计算盈亏
        trades_by_symbol: Dict[str, List] = defaultdict(list)
        for trade in self.trades:
            symbol = trade.get('symbol')
            if symbol:
                trades_by_symbol[symbol].append(trade)
        
        profits = []
        losses = []
        holding_days = []
        
        for symbol, symbol_trades in trades_by_symbol.items():
            # 按时间排序
            symbol_trades = sorted(symbol_trades, key=lambda x: x.get('timestamp', ''))
            
            # 配对买入卖出
            buy_trades = []
            
            for trade in symbol_trades:
                side = trade.get('side', '')
                
                if side == 'buy':
                    buy_trades.append(trade)
                elif side == 'sell' and buy_trades:
                    buy_trade = buy_trades.pop(0)
                    
                    buy_price = buy_trade.get('price', 0)
                    sell_price = trade.get('price', 0)
                    
                    if buy_price > 0:
                        pnl_pct = (sell_price - buy_price) / buy_price * 100
                        
                        if pnl_pct > 0:
                            profits.append(pnl_pct)
                        else:
                            losses.append(abs(pnl_pct))
                        
                        # 计算持仓天数
                        try:
                            buy_time = pd.to_datetime(buy_trade.get('timestamp'))
                            sell_time = pd.to_datetime(trade.get('timestamp'))
                            days = (sell_time - buy_time).days
                            holding_days.append(max(days, 1))
                        except:
                            pass
        
        # 统计
        total_trades = len(profits) + len(losses)
        stats['total_trades'] = total_trades
        stats['winning_trades'] = len(profits)
        stats['losing_trades'] = len(losses)
        
        if total_trades > 0:
            stats['win_rate'] = len(profits) / total_trades * 100
        
        if profits:
            stats['avg_profit'] = sum(profits) / len(profits)
        
        if losses:
            stats['avg_loss'] = sum(losses) / len(losses)
        
        if losses and sum(losses) > 0:
            stats['profit_factor'] = sum(profits) / sum(losses) if profits else 0
        
        if holding_days:
            stats['avg_holding_days'] = sum(holding_days) / len(holding_days)
        
        return stats
    
    def monthly_returns(self) -> List[Dict]:
        """月度收益"""
        if self.equity_df.empty:
            return []
        
        # 按月重采样
        monthly = self.equity_df['value'].resample('ME').last()
        
        results = []
        prev_value = None
        
        for dt, value in monthly.items():
            if prev_value is not None:
                ret = (value / prev_value - 1) * 100
                results.append({
                    'month': dt.strftime('%Y-%m'),
                    'return': ret,
                    'value': value,
                })
            prev_value = value
        
        return results
    
    def benchmark_comparison(self, benchmark_data: pd.DataFrame) -> Dict:
        """基准对比
        
        Args:
            benchmark_data: 基准数据 DataFrame（需要有 close 列）
        
        Returns:
            对比指标
        """
        result = {
            'benchmark_return': 0,
            'alpha': 0,
            'beta': 0,
            'information_ratio': 0,
        }
        
        if self.equity_df.empty or benchmark_data is None or benchmark_data.empty:
            return result
        
        # 对齐日期
        if isinstance(benchmark_data.index, pd.DatetimeIndex):
            benchmark = benchmark_data
        else:
            benchmark = benchmark_data.copy()
            benchmark.index = pd.to_datetime(benchmark.index)
        
        # 计算基准收益率
        benchmark_returns = benchmark['close'].pct_change().dropna()
        strategy_returns = self.equity_df['return'].dropna()
        
        # 对齐
        common_dates = strategy_returns.index.intersection(benchmark_returns.index)
        if len(common_dates) < 10:
            return result
        
        strat_ret = strategy_returns.loc[common_dates]
        bench_ret = benchmark_returns.loc[common_dates]
        
        # 基准总收益
        result['benchmark_return'] = (
            (1 + bench_ret).prod() - 1
        ) * 100
        
        # Beta 和 Alpha
        if bench_ret.var() > 0:
            covariance = strat_ret.cov(bench_ret)
            variance = bench_ret.var()
            result['beta'] = covariance / variance
            
            # Alpha (年化)
            strat_annual = self.annual_return() / 100
            bench_annual = (pow((1 + result['benchmark_return']/100), 
                               365 / len(common_dates)) - 1)
            result['alpha'] = (strat_annual - self.risk_free_rate - 
                              result['beta'] * (bench_annual - self.risk_free_rate)) * 100
        
        # 信息比率
        excess_returns = strat_ret - bench_ret
        tracking_error = excess_returns.std() * np.sqrt(252)
        
        if tracking_error > 0:
            result['information_ratio'] = excess_returns.mean() * 252 / tracking_error
        
        return result
    
    def summary(self) -> Dict:
        """绩效摘要"""
        trade_stats = self.trade_statistics()
        
        return {
            'total_return': self.total_return(),
            'annual_return': self.annual_return(),
            'max_drawdown': self.max_drawdown(),
            'max_drawdown_duration': self.max_drawdown_duration(),
            'volatility': self.volatility(),
            'sharpe_ratio': self.sharpe_ratio(),
            'sortino_ratio': self.sortino_ratio(),
            'calmar_ratio': self.calmar_ratio(),
            **trade_stats,
        }
