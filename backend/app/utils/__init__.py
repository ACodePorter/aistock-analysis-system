"""
Utils module - 工具与辅助模块

包含MongoDB存储、数据质量验证、监控指标、代理任务等功能。
"""

from .mongo_storage import get_storage, StockNewsStorage
from .background_task_queue import BackgroundTaskQueue
from .metrics import NewsMetrics

# 延迟导入以避免循环依赖
def __getattr__(name):
    if name == 'enrich_stock_profile':
        from .stock_profile_enrichment import enrich_stock_profile
        return enrich_stock_profile
    elif name == 'validate_stock_profile':
        from .stock_profile_validator import validate_stock_profile
        return validate_stock_profile
    elif name == 'update_stock_profile':
        from .profile_updater import update_stock_profile
        return update_stock_profile
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'get_storage',
    'StockNewsStorage',
    'enrich_stock_profile',
    'validate_stock_profile',
    'update_stock_profile',
    'BackgroundTaskQueue',
    'NewsMetrics',
]
