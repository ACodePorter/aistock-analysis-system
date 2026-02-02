"""
智能财经爬虫框架

功能：
1. 多信源爬虫 - 覆盖东方财富、同花顺、新浪财经、证监会公告等
2. 智能调度队列 - 控制请求速率，避免被限流
3. 信源库管理 - 自动存储、去重、分类

使用方式：
    from app.crawlers import CrawlerOrchestrator
    
    orchestrator = CrawlerOrchestrator()
    orchestrator.start()
    
    # 抓取某只股票的新闻
    orchestrator.crawl_stock("贵州茅台", "600519")
    
    # 抓取行业新闻
    orchestrator.crawl_industry("新能源")
"""

from .crawler_queue import CrawlerQueue, CrawlerTask
from .source_registry import SourceRegistry, NewsSource
from .orchestrator import CrawlerOrchestrator

__all__ = [
    'CrawlerQueue',
    'CrawlerTask', 
    'SourceRegistry',
    'NewsSource',
    'CrawlerOrchestrator',
]
