"""
事件抽取任务 - 从新文章抽取结构化事件

工作流程：
1. 查找未处理的新文章
2. 调用LLM抽取事件
3. 事件合并与去重
4. 保存到events表
5. 触发简报更新
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def extract_events_from_new_articles() -> dict:
    """
    定时任务：从最近新文章抽取事件
    
    Returns:
        {
            "task_id": "task_xxx",
            "articles_processed": 50,
            "events_extracted": 15,
            "events_merged": 3,
            "duration_sec": 120,
        }
    """
    logger.info("Starting event extraction job")
    # TODO: 实现
    pass


async def merge_similar_events() -> dict:
    """
    合并任务：定时检查并合并相似事件
    
    规则：
    - 同股票+同事件类型+3天内 -> 合并
    - 多源一致 -> 提升置信度
    """
    logger.info("Starting event merge job")
    # TODO: 实现
    pass


async def update_event_confidence() -> dict:
    """更新已有事件的置信度"""
    # TODO: 实现
    pass
