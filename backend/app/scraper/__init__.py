"""
Scraper Module

完整的多域名爬虫模块，支持：
- 多种fetcher策略（Wikipedia API、Playwright、requests）
- 登录检测与状态管理
- 任务队列与中断恢复
- 结构化日志与监控
"""

from .main import ScraperOrchestrator, run_scraper, run_scraper_sync
from .domain_router import DomainRouter
from .utils.logger import ScraperEventLogger
from .utils.detect_login import is_login_page
from .storage.state_manager import StateManager
from .queue.task_queue import TaskQueue, TaskStatus
from .fetchers.wikipedia import WikipediaFetcher
from .fetchers.requests_fetcher import RequestsFetcher, RequestsFetcherWithCookies
from .fetchers.playwright_fetcher import PlaywrightFetcher, PlaywrightFetcherSync

__all__ = [
    'ScraperOrchestrator',
    'run_scraper',
    'run_scraper_sync',
    'DomainRouter',
    'ScraperEventLogger',
    'is_login_page',
    'StateManager',
    'TaskQueue',
    'TaskStatus',
    'WikipediaFetcher',
    'RequestsFetcher',
    'RequestsFetcherWithCookies',
    'PlaywrightFetcher',
    'PlaywrightFetcherSync',
]

__version__ = '1.0.0'
