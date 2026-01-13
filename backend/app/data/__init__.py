"""
Data module - 数据获取模块

包含数据源聚合、多源回退策略、数据标准化等功能。
"""

from .data_source import (
    normalize_symbol,
    fetch_daily,
    fetch_fund_flow_daily,
    search_stocks,
    get_stock_info,
    get_realtime_stock,
    get_spot_snapshot,
)

__all__ = [
    'normalize_symbol',
    'fetch_daily',
    'fetch_fund_flow_daily',
    'search_stocks',
    'get_stock_info',
    'get_realtime_stock',
    'get_spot_snapshot',
]
