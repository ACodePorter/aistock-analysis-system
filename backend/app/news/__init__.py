"""
News module - 新闻处理模块

包含新闻搜索、网页爬虫、LLM分析、去重检测、调度等功能。
"""

from .news_service import NewsSearchService, NewsProcessor
from .news_crawler import NewsContentCrawler
from .llm_processor import LLMNewsProcessor, NewsAnalysisResult
from .news_deduplication import NewsDeduplicator
from .news_strategy import NewsStrategy
from .enhanced_news_scheduler import EnhancedNewsScheduler

__all__ = [
    'NewsSearchService',
    'NewsProcessor',
    'NewsContentCrawler',
    'LLMNewsProcessor',
    'NewsAnalysisResult',
    'NewsDeduplicator',
    'NewsStrategy',
    'EnhancedNewsScheduler',
]
