"""
爬虫调度器（Orchestrator）

统一管理所有爬虫任务：
1. 任务调度与队列管理
2. 多源并行抓取
3. 结果聚合与去重
4. 定时任务调度
5. 信源库存储

作者：AI Stock Analysis Enhancement
日期：2026-01
"""

import os
import json
import time
import logging
import threading
import sqlite3
import hashlib
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .crawler_queue import CrawlerQueue, CrawlerTask, TaskPriority, get_crawler_queue
from .source_registry import SourceRegistry, SourceType, get_source_registry
from .crawlers import (
    get_crawler,
    crawl_stock_news_multi,
    EastMoneyCrawler,
    SinaFinanceCrawler,
    CLSCrawler,
    CNInfoCrawler,
    OpenClawCrawler,
)

logger = logging.getLogger(__name__)


class NewsStore:
    """新闻信源库
    
    存储抓取的新闻数据，支持：
    - 去重
    - 全文检索
    - 按股票/行业查询
    """
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(
            os.path.dirname(__file__), '..', 'data', 'news_store.db'
        )
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 新闻表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT UNIQUE,
                title TEXT,
                url TEXT,
                content TEXT,
                source TEXT,
                publish_time TEXT,
                crawl_time TEXT DEFAULT CURRENT_TIMESTAMP,
                stock_code TEXT,
                stock_name TEXT,
                industry TEXT,
                is_industry_news INTEGER DEFAULT 0,
                is_announcement INTEGER DEFAULT 0,
                is_research INTEGER DEFAULT 0,
                sentiment_score REAL,
                importance_score REAL,
                extra_data TEXT
            )
        ''')
        
        # 索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_stock ON news(stock_code)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_industry ON news(industry)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_source ON news(source)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_time ON news(publish_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_crawl ON news(crawl_time)')
        
        # 股票关注列表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist (
                stock_code TEXT PRIMARY KEY,
                stock_name TEXT,
                industry TEXT,
                priority INTEGER DEFAULT 5,
                enabled INTEGER DEFAULT 1,
                last_crawl TEXT,
                crawl_interval_hours INTEGER DEFAULT 4,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 行业关注列表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS industry_watchlist (
                industry TEXT PRIMARY KEY,
                keywords TEXT,
                priority INTEGER DEFAULT 5,
                enabled INTEGER DEFAULT 1,
                last_crawl TEXT,
                crawl_interval_hours INTEGER DEFAULT 6,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info(f"[信源库] 数据库初始化完成: {self.db_path}")
    
    def _url_hash(self, url: str) -> str:
        """计算URL哈希"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def save_news(self, news_list: List[Dict[str, Any]]) -> int:
        """保存新闻列表
        
        Returns:
            成功保存的数量
        """
        if not news_list:
            return 0
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        saved = 0
        for news in news_list:
            url = news.get('url', '')
            if not url:
                continue
            
            url_hash = self._url_hash(url)
            
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO news 
                    (url_hash, title, url, content, source, publish_time, 
                     stock_code, stock_name, industry, is_industry_news, 
                     is_announcement, is_research, extra_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    url_hash,
                    news.get('title', ''),
                    url,
                    news.get('content', ''),
                    news.get('source', ''),
                    news.get('publish_time', ''),
                    news.get('stock_code', ''),
                    news.get('stock_name', ''),
                    news.get('industry', ''),
                    1 if news.get('is_industry_news') else 0,
                    1 if news.get('is_announcement') else 0,
                    1 if news.get('is_research') else 0,
                    json.dumps({k: v for k, v in news.items() 
                               if k not in ['title', 'url', 'content', 'source', 
                                           'publish_time', 'stock_code', 'stock_name', 
                                           'industry', 'is_industry_news', 
                                           'is_announcement', 'is_research']},
                              ensure_ascii=False),
                ))
                
                if cursor.rowcount > 0:
                    saved += 1
            except Exception as e:
                logger.warning(f"[信源库] 保存失败: {e}")
        
        conn.commit()
        conn.close()
        
        if saved > 0:
            logger.info(f"[信源库] 保存 {saved}/{len(news_list)} 条新闻")
        
        return saved
    
    def query_by_stock(
        self, 
        stock_code: str, 
        limit: int = 20, 
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """按股票代码查询新闻"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        since = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute('''
            SELECT title, url, content, source, publish_time, 
                   is_industry_news, is_announcement, is_research
            FROM news
            WHERE stock_code = ? AND crawl_time > ?
            ORDER BY publish_time DESC
            LIMIT ?
        ''', (stock_code, since, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'title': row[0],
                'url': row[1],
                'content': row[2],
                'source': row[3],
                'publish_time': row[4],
                'is_industry_news': bool(row[5]),
                'is_announcement': bool(row[6]),
                'is_research': bool(row[7]),
            })
        
        conn.close()
        return results
    
    def query_by_industry(
        self, 
        industry: str, 
        limit: int = 20, 
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """按行业查询新闻"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        since = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute('''
            SELECT title, url, content, source, publish_time
            FROM news
            WHERE industry = ? AND crawl_time > ?
            ORDER BY publish_time DESC
            LIMIT ?
        ''', (industry, since, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'title': row[0],
                'url': row[1],
                'content': row[2],
                'source': row[3],
                'publish_time': row[4],
                'is_industry_news': True,
            })
        
        conn.close()
        return results
    
    def search(
        self, 
        keyword: str, 
        limit: int = 20,
        stock_code: str = None,
        industry: str = None,
    ) -> List[Dict[str, Any]]:
        """全文搜索新闻"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = '''
            SELECT title, url, content, source, publish_time, 
                   stock_code, industry, is_industry_news
            FROM news
            WHERE (title LIKE ? OR content LIKE ?)
        '''
        params = [f'%{keyword}%', f'%{keyword}%']
        
        if stock_code:
            query += ' AND stock_code = ?'
            params.append(stock_code)
        
        if industry:
            query += ' AND industry = ?'
            params.append(industry)
        
        query += ' ORDER BY crawl_time DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'title': row[0],
                'url': row[1],
                'content': row[2],
                'source': row[3],
                'publish_time': row[4],
                'stock_code': row[5],
                'industry': row[6],
                'is_industry_news': bool(row[7]),
            })
        
        conn.close()
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # 总数
        cursor.execute('SELECT COUNT(*) FROM news')
        stats['total_news'] = cursor.fetchone()[0]
        
        # 按源统计
        cursor.execute('''
            SELECT source, COUNT(*) FROM news
            GROUP BY source ORDER BY COUNT(*) DESC
        ''')
        stats['by_source'] = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 最近24小时
        since = (datetime.now() - timedelta(hours=24)).isoformat()
        cursor.execute('SELECT COUNT(*) FROM news WHERE crawl_time > ?', (since,))
        stats['last_24h'] = cursor.fetchone()[0]
        
        conn.close()
        return stats
    
    # ===== 关注列表管理 =====
    
    def add_to_watchlist(self, stock_code: str, stock_name: str = '', industry: str = '', priority: int = 5):
        """添加股票到关注列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO watchlist (stock_code, stock_name, industry, priority)
            VALUES (?, ?, ?, ?)
        ''', (stock_code, stock_name, industry, priority))
        
        conn.commit()
        conn.close()
    
    def get_watchlist(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """获取关注列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = 'SELECT stock_code, stock_name, industry, priority, last_crawl FROM watchlist'
        if enabled_only:
            query += ' WHERE enabled = 1'
        query += ' ORDER BY priority'
        
        cursor.execute(query)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'stock_code': row[0],
                'stock_name': row[1],
                'industry': row[2],
                'priority': row[3],
                'last_crawl': row[4],
            })
        
        conn.close()
        return results
    
    def update_last_crawl(self, stock_code: str):
        """更新最后抓取时间"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE watchlist SET last_crawl = ? WHERE stock_code = ?
        ''', (datetime.now().isoformat(), stock_code))
        
        conn.commit()
        conn.close()


class CrawlerOrchestrator:
    """爬虫调度器
    
    核心功能：
    1. 管理多个爬虫
    2. 任务队列调度
    3. 定时抓取
    4. 结果聚合存储
    """
    
    def __init__(
        self,
        max_workers: int = 3,
        enable_scheduler: bool = True,
    ):
        self.max_workers = max_workers
        self.enable_scheduler = enable_scheduler
        
        # 初始化组件
        self.queue = get_crawler_queue()
        self.registry = get_source_registry()
        self.store = NewsStore()
        
        # 注册爬虫函数到队列
        self._register_crawlers()
        
        # 调度器
        self.scheduler_thread: Optional[threading.Thread] = None
        self.stop_scheduler = threading.Event()
        
        # 执行线程池
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        self.is_running = False
    
    def _register_crawlers(self):
        """注册爬虫函数到队列"""
        crawler_funcs = {
            'eastmoney': self._crawl_eastmoney,
            'sina_finance': self._crawl_sina,
            'cls': self._crawl_cls,
            'cninfo': self._crawl_cninfo,
            'openclaw': self._crawl_openclaw,
            'default': self._crawl_openclaw,
        }
        
        self.queue.start(crawler_funcs)
    
    def _crawl_eastmoney(self, query: str, task_type: str, **kwargs) -> List[Dict[str, Any]]:
        """东方财富爬虫入口"""
        crawler = EastMoneyCrawler()
        
        if task_type == 'stock_news':
            return crawler.crawl_stock_news(
                kwargs.get('stock_code', ''),
                kwargs.get('stock_name', query),
                kwargs.get('limit', 10)
            )
        elif task_type == 'industry_news':
            return crawler.crawl_industry_news(query, kwargs.get('limit', 10))
        elif task_type == 'research':
            return crawler.crawl_research_report(
                kwargs.get('stock_code', ''),
                kwargs.get('limit', 5)
            )
        
        return []
    
    def _crawl_sina(self, query: str, task_type: str, **kwargs) -> List[Dict[str, Any]]:
        """新浪财经爬虫入口"""
        crawler = SinaFinanceCrawler()
        return crawler.crawl_stock_news(
            kwargs.get('stock_code', ''),
            kwargs.get('stock_name', query),
            kwargs.get('limit', 10)
        )
    
    def _crawl_cls(self, query: str, task_type: str, **kwargs) -> List[Dict[str, Any]]:
        """财联社爬虫入口"""
        crawler = CLSCrawler()
        
        if task_type == 'telegraph':
            return crawler.crawl_telegraph(query, kwargs.get('limit', 20))
        else:
            return crawler.crawl_stock_news(
                kwargs.get('stock_code', ''),
                kwargs.get('stock_name', query),
                kwargs.get('limit', 10)
            )
    
    def _crawl_cninfo(self, query: str, task_type: str, **kwargs) -> List[Dict[str, Any]]:
        """巨潮资讯爬虫入口"""
        crawler = CNInfoCrawler()
        return crawler.crawl_announcements(
            kwargs.get('stock_code', query),
            kwargs.get('limit', 10)
        )
    
    def _crawl_openclaw(self, query: str, task_type: str, **kwargs) -> List[Dict[str, Any]]:
        """OpenClaw 检索爬虫入口"""
        crawler = OpenClawCrawler()
        return crawler.crawl(query, task_type, kwargs.get('limit', 10))
    
    def start(self):
        """启动调度器"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # 启动定时调度
        if self.enable_scheduler:
            self.stop_scheduler.clear()
            self.scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                name="CrawlerScheduler",
                daemon=True
            )
            self.scheduler_thread.start()
        
        logger.info("✅ [调度器] 爬虫调度器已启动")
    
    def stop(self):
        """停止调度器"""
        if not self.is_running:
            return
        
        # 停止调度器
        self.stop_scheduler.set()
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        
        # 停止队列
        self.queue.stop()
        
        # 关闭线程池
        self.executor.shutdown(wait=False)
        
        self.is_running = False
        logger.info("⛔ [调度器] 爬虫调度器已停止")
    
    def _scheduler_loop(self):
        """定时调度循环"""
        while not self.stop_scheduler.is_set():
            try:
                # 检查需要抓取的股票
                self._schedule_watchlist_crawl()
                
                # 每10分钟检查一次
                self.stop_scheduler.wait(600)
            except Exception as e:
                logger.error(f"[调度器] 调度循环异常: {e}")
                time.sleep(60)
    
    def _schedule_watchlist_crawl(self):
        """调度关注列表抓取"""
        watchlist = self.store.get_watchlist()
        
        now = datetime.now()
        
        for stock in watchlist:
            # 检查是否需要抓取
            last_crawl = stock.get('last_crawl')
            if last_crawl:
                last_dt = datetime.fromisoformat(last_crawl)
                # 默认4小时间隔
                if (now - last_dt).total_seconds() < 4 * 3600:
                    continue
            
            # 提交抓取任务
            self.crawl_stock(
                stock['stock_name'],
                stock['stock_code'],
                industry=stock.get('industry', ''),
                priority=TaskPriority.BACKGROUND
            )
    
    # ===== 公开API =====
    
    def crawl_stock(
        self,
        stock_name: str,
        stock_code: str,
        industry: str = '',
        priority: TaskPriority = TaskPriority.NORMAL,
        callback: Callable = None,
    ) -> List[str]:
        """抓取股票新闻
        
        从多个源抓取，自动存储到信源库
        
        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            industry: 行业
            priority: 优先级
            callback: 完成回调
        
        Returns:
            任务ID列表
        """
        task_ids = []
        
        # 定义保存回调
        def save_callback(task: CrawlerTask):
            if task.result:
                # 添加股票信息
                for news in task.result:
                    news['stock_code'] = stock_code
                    news['stock_name'] = stock_name
                    news['industry'] = industry
                
                self.store.save_news(task.result)
            
            if callback:
                callback(task)
        
        # 提交到多个源
        sources = ['cls', 'eastmoney', 'sina_finance']
        
        for source in sources:
            task_id = self.queue.submit(
                source=source,
                task_type='stock_news',
                query=stock_name,
                params={
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'limit': 10,
                },
                priority=priority,
                callback=save_callback,
            )
            task_ids.append(task_id)
        
        # 添加公告抓取
        task_id = self.queue.submit(
            source='cninfo',
            task_type='announcement',
            query=stock_code,
            params={
                'stock_code': stock_code,
                'limit': 5,
            },
            priority=priority,
            callback=save_callback,
        )
        task_ids.append(task_id)
        
        # 更新最后抓取时间
        self.store.update_last_crawl(stock_code)
        
        logger.info(f"[调度器] 已提交 {len(task_ids)} 个抓取任务: {stock_name} ({stock_code})")
        return task_ids
    
    def crawl_industry(
        self,
        industry: str,
        keywords: List[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> List[str]:
        """抓取行业新闻"""
        task_ids = []
        
        def save_callback(task: CrawlerTask):
            if task.result:
                for news in task.result:
                    news['industry'] = industry
                    news['is_industry_news'] = True
                self.store.save_news(task.result)
        
        # 东方财富行业新闻
        task_id = self.queue.submit(
            source='eastmoney',
            task_type='industry_news',
            query=industry,
            params={'limit': 15},
            priority=priority,
            callback=save_callback,
        )
        task_ids.append(task_id)
        
        # SearXNG补充
        search_query = f'{industry} 行业 政策'
        task_id = self.queue.submit(
            source='openclaw',
            task_type='industry_news',
            query=search_query,
            params={'limit': 10},
            priority=priority,
            callback=save_callback,
        )
        task_ids.append(task_id)
        
        return task_ids
    
    def crawl_telegraph(self, keyword: str = '', limit: int = 50) -> str:
        """抓取财联社电报快讯"""
        def save_callback(task: CrawlerTask):
            if task.result:
                self.store.save_news(task.result)
        
        return self.queue.submit(
            source='cls',
            task_type='telegraph',
            query=keyword,
            params={'limit': limit},
            priority=TaskPriority.HIGH,
            callback=save_callback,
        )
    
    def get_stock_news(
        self,
        stock_code: str,
        stock_name: str = '',
        limit: int = 20,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """获取股票新闻（优先从信源库获取）
        
        如果信源库数据不足或过期，自动触发抓取
        """
        # 先从信源库查询
        news = self.store.query_by_stock(stock_code, limit)
        
        # 如果数据不足，触发抓取
        if len(news) < 5 or force_refresh:
            # 异步触发抓取（不等待结果）
            self.crawl_stock(stock_name, stock_code, priority=TaskPriority.HIGH)
        
        return news
    
    def add_to_watchlist(self, stock_code: str, stock_name: str = '', industry: str = ''):
        """添加到关注列表"""
        self.store.add_to_watchlist(stock_code, stock_name, industry)
        
        # 立即触发一次抓取
        self.crawl_stock(stock_name, stock_code, industry, priority=TaskPriority.HIGH)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'queue': self.queue.get_stats(),
            'store': self.store.get_stats(),
            'sources': self.registry.get_stats(),
        }


# ===== 全局实例 =====

_orchestrator: Optional[CrawlerOrchestrator] = None


def get_orchestrator() -> CrawlerOrchestrator:
    """获取全局调度器"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CrawlerOrchestrator()
    return _orchestrator


def init_crawler_system():
    """初始化爬虫系统"""
    orchestrator = get_orchestrator()
    orchestrator.start()
    logger.info("✅ 爬虫系统初始化完成")
    return orchestrator


