"""
回测系统模块

提供策略回测、绩效评估、交易模拟等功能
"""

from .engine import BacktestEngine, BacktestConfig, BacktestResult
from .strategies import BaseStrategy, SignalStrategy, MACrossStrategy
from .performance import PerformanceAnalyzer

__all__ = [
    'BacktestEngine',
    'BacktestConfig', 
    'BacktestResult',
    'BaseStrategy',
    'SignalStrategy',
    'MACrossStrategy',
    'PerformanceAnalyzer',
]
