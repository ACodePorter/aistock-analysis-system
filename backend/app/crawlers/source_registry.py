"""
多信源财经爬虫注册表

信源覆盖：
1. 综合新闻：东方财富、新浪财经、腾讯财经、网易财经
2. 专业资讯：财联社、同花顺、雪球
3. 官方公告：巨潮资讯、上交所、深交所、证监会
4. 行业报告：券商研报、行业协会
5. 通用搜索：SearXNG（作为兜底）

作者：AI Stock Analysis Enhancement
日期：2026-01
"""

import os
import re
import json
import time
import random
import logging
import hashlib
import sqlite3
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import requests
from urllib.parse import urljoin, quote
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class SourceType(Enum):
    """信源类型"""
    NEWS = "news"              # 新闻资讯
    ANNOUNCEMENT = "ann"       # 公告披露
    RESEARCH = "research"      # 研究报告
    COMMUNITY = "community"    # 社区讨论
    OFFICIAL = "official"      # 官方信息
    SEARCH = "search"          # 搜索引擎


class SourceStatus(Enum):
    """信源状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


@dataclass
class NewsSource:
    """新闻信源配置"""
    name: str                          # 信源名称
    source_type: SourceType            # 信源类型
    base_url: str                      # 基础URL
    rate_limit: float = 0.5            # 请求速率（次/秒）
    priority: int = 5                  # 优先级（越小越优先）
    enabled: bool = True               # 是否启用
    requires_js: bool = False          # 是否需要JS渲染
    description: str = ""              # 描述
    status: SourceStatus = SourceStatus.ACTIVE


class SourceRegistry:
    """信源注册表
    
    管理所有可用的财经信源
    """
    
    # 预定义的信源列表
    BUILTIN_SOURCES = {
        # ===== 综合财经新闻 =====
        'eastmoney': NewsSource(
            name='eastmoney',
            source_type=SourceType.NEWS,
            base_url='https://www.eastmoney.com',
            rate_limit=0.5,
            priority=1,
            description='东方财富网 - 国内最大财经门户'
        ),
        'sina_finance': NewsSource(
            name='sina_finance',
            source_type=SourceType.NEWS,
            base_url='https://finance.sina.com.cn',
            rate_limit=0.5,
            priority=2,
            description='新浪财经'
        ),
        'qq_finance': NewsSource(
            name='qq_finance',
            source_type=SourceType.NEWS,
            base_url='https://finance.qq.com',
            rate_limit=0.5,
            priority=3,
            description='腾讯财经'
        ),
        '163_finance': NewsSource(
            name='163_finance',
            source_type=SourceType.NEWS,
            base_url='https://money.163.com',
            rate_limit=0.5,
            priority=4,
            description='网易财经'
        ),
        
        # ===== 专业财经资讯 =====
        'cls': NewsSource(
            name='cls',
            source_type=SourceType.NEWS,
            base_url='https://www.cls.cn',
            rate_limit=0.5,
            priority=1,
            description='财联社 - 专业财经快讯'
        ),
        'tonghuashun': NewsSource(
            name='tonghuashun',
            source_type=SourceType.NEWS,
            base_url='https://www.10jqka.com.cn',
            rate_limit=0.3,
            priority=2,
            requires_js=True,
            description='同花顺 - 炒股软件龙头'
        ),
        'xueqiu': NewsSource(
            name='xueqiu',
            source_type=SourceType.COMMUNITY,
            base_url='https://xueqiu.com',
            rate_limit=0.3,
            priority=3,
            requires_js=True,
            description='雪球 - 投资者社区'
        ),
        
        # ===== 官方公告 =====
        'cninfo': NewsSource(
            name='cninfo',
            source_type=SourceType.ANNOUNCEMENT,
            base_url='http://www.cninfo.com.cn',
            rate_limit=0.3,
            priority=1,
            description='巨潮资讯 - 官方信息披露平台'
        ),
        'sse': NewsSource(
            name='sse',
            source_type=SourceType.ANNOUNCEMENT,
            base_url='http://www.sse.com.cn',
            rate_limit=0.2,
            priority=1,
            description='上海证券交易所'
        ),
        'szse': NewsSource(
            name='szse',
            source_type=SourceType.ANNOUNCEMENT,
            base_url='http://www.szse.cn',
            rate_limit=0.2,
            priority=1,
            description='深圳证券交易所'
        ),
        'csrc': NewsSource(
            name='csrc',
            source_type=SourceType.OFFICIAL,
            base_url='http://www.csrc.gov.cn',
            rate_limit=0.2,
            priority=2,
            description='中国证监会'
        ),
        
        # ===== 研究报告 =====
        'eastmoney_research': NewsSource(
            name='eastmoney_research',
            source_type=SourceType.RESEARCH,
            base_url='https://data.eastmoney.com/report',
            rate_limit=0.3,
            priority=2,
            description='东方财富研报中心'
        ),
        
        # ===== 搜索引擎（兜底） =====
        'searxng': NewsSource(
            name='searxng',
            source_type=SourceType.SEARCH,
            base_url=os.getenv('SEARXNG_URL', 'http://localhost:10000'),
            rate_limit=0.2,  # 更保守的限速
            priority=10,     # 最低优先级
            description='SearXNG - 自托管搜索引擎'
        ),
    }
    
    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: SQLite数据库路径
        """
        self.db_path = db_path or os.path.join(
            os.path.dirname(__file__), '..', 'data', 'source_registry.db'
        )
        self.sources: Dict[str, NewsSource] = dict(self.BUILTIN_SOURCES)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 信源配置表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sources (
                name TEXT PRIMARY KEY,
                source_type TEXT,
                base_url TEXT,
                rate_limit REAL,
                priority INTEGER,
                enabled INTEGER DEFAULT 1,
                requires_js INTEGER DEFAULT 0,
                description TEXT,
                status TEXT DEFAULT 'active',
                last_success TEXT,
                last_failure TEXT,
                failure_count INTEGER DEFAULT 0
            )
        ''')
        
        # 抓取记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawl_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                query TEXT,
                task_type TEXT,
                result_count INTEGER,
                duration_ms INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                success INTEGER DEFAULT 1,
                error TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_crawl_source ON crawl_history(source)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_crawl_created ON crawl_history(created_at)
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info(f"[信源] 数据库初始化完成: {self.db_path}")
    
    def register(self, source: NewsSource):
        """注册新信源"""
        self.sources[source.name] = source
        
        # 持久化
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO sources 
            (name, source_type, base_url, rate_limit, priority, enabled, requires_js, description, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            source.name,
            source.source_type.value,
            source.base_url,
            source.rate_limit,
            source.priority,
            1 if source.enabled else 0,
            1 if source.requires_js else 0,
            source.description,
            source.status.value,
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"[信源] 已注册: {source.name}")
    
    def get(self, name: str) -> Optional[NewsSource]:
        """获取信源"""
        return self.sources.get(name)
    
    def get_by_type(self, source_type: SourceType, enabled_only: bool = True) -> List[NewsSource]:
        """按类型获取信源列表"""
        sources = [s for s in self.sources.values() if s.source_type == source_type]
        if enabled_only:
            sources = [s for s in sources if s.enabled]
        return sorted(sources, key=lambda s: s.priority)
    
    def get_all(self, enabled_only: bool = True) -> List[NewsSource]:
        """获取所有信源"""
        sources = list(self.sources.values())
        if enabled_only:
            sources = [s for s in sources if s.enabled]
        return sorted(sources, key=lambda s: s.priority)
    
    def record_success(self, name: str, query: str, task_type: str, result_count: int, duration_ms: int):
        """记录成功抓取"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO crawl_history (source, query, task_type, result_count, duration_ms, success)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (name, query, task_type, result_count, duration_ms))
        
        cursor.execute('''
            UPDATE sources SET last_success = ?, failure_count = 0, status = 'active'
            WHERE name = ?
        ''', (datetime.now().isoformat(), name))
        
        conn.commit()
        conn.close()
    
    def record_failure(self, name: str, query: str, task_type: str, error: str):
        """记录失败"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO crawl_history (source, query, task_type, success, error)
            VALUES (?, ?, ?, 0, ?)
        ''', (name, query, task_type, error))
        
        cursor.execute('''
            UPDATE sources SET last_failure = ?, failure_count = failure_count + 1
            WHERE name = ?
        ''', (datetime.now().isoformat(), name))
        
        # 连续失败超过5次，标记为错误状态
        cursor.execute('''
            UPDATE sources SET status = 'error'
            WHERE name = ? AND failure_count >= 5
        ''', (name,))
        
        conn.commit()
        conn.close()
    
    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """获取信源统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        since = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute('''
            SELECT source, 
                   COUNT(*) as total,
                   SUM(success) as success_count,
                   AVG(result_count) as avg_results,
                   AVG(duration_ms) as avg_duration
            FROM crawl_history
            WHERE created_at > ?
            GROUP BY source
        ''', (since,))
        
        stats = {}
        for row in cursor.fetchall():
            stats[row[0]] = {
                'total': row[1],
                'success_count': row[2],
                'success_rate': row[2] / row[1] if row[1] > 0 else 0,
                'avg_results': row[3],
                'avg_duration_ms': row[4],
            }
        
        conn.close()
        return stats


# 全局信源注册表
_source_registry: Optional[SourceRegistry] = None


def get_source_registry() -> SourceRegistry:
    """获取全局信源注册表"""
    global _source_registry
    if _source_registry is None:
        _source_registry = SourceRegistry()
    return _source_registry
