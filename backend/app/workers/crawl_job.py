"""
采集任务 - 定时/按需采集观察池舆情

工作流程：
1. 遍历watchlist.active股票
2. 为每只股票采集最新新闻
3. 标准化处理
4. 触发事件抽取
5. 记录失败归因
"""

import logging
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger(__name__)


async def crawl_watchlist() -> dict:
    """
    定时任务：采集观察池所有股票的最新新闻
    
    Returns:
        {
            "task_id": "task_xxx",
            "symbols_processed": 50,
            "articles_collected": 200,
            "errors": [...],
            "duration_sec": 600,
        }
    """
    logger.info("Starting watchlist crawl job")
    # TODO: 实现
    pass


async def crawl_symbol(symbol: str) -> dict:
    """为单只股票采集"""
    logger.info(f"Crawling news for {symbol}")
    # TODO: 实现
    pass


async def replay_failed_urls() -> dict:
    """
    补抓任务：重新尝试采集失败的URLs
    
    从MongoDB.fetch_failures中取出，按失败类型分类重试
    """
    logger.info("Starting failed URL replay job")
    # TODO: 实现
    pass


async def cleanup_old_articles(days: int = 90) -> dict:
    """清理旧文章（保留时间窗外的可归档）"""
    # TODO: 实现
    pass
