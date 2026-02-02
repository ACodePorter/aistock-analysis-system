"""
智能爬虫调度队列

解决SearXNG等搜索引擎限流问题：
1. 令牌桶限速 - 控制每个源的请求速率
2. 优先级队列 - 重要任务优先处理
3. 失败重试 - 指数退避重试
4. 健康监控 - 自动跳过不健康的源

作者：AI Stock Analysis Enhancement
日期：2026-01
"""

import os
import time
import queue
import logging
import threading
import sqlite3
from typing import Callable, Any, Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """任务优先级"""
    CRITICAL = 0      # 紧急任务（用户实时请求）
    HIGH = 1          # 高优先级（重要股票）
    NORMAL = 2        # 普通优先级
    LOW = 3           # 低优先级（批量补充）
    BACKGROUND = 4    # 后台任务


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


@dataclass(order=True)
class CrawlerTask:
    """爬虫任务"""
    priority: int
    task_id: str = field(compare=False)
    source: str = field(compare=False)           # 信源名称
    task_type: str = field(compare=False)        # stock_news, industry_news, policy, announcement
    query: str = field(compare=False)            # 搜索关键词
    params: Dict[str, Any] = field(compare=False, default_factory=dict)
    callback: Optional[Callable] = field(compare=False, default=None)
    created_at: datetime = field(compare=False, default_factory=datetime.now)
    status: TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    retry_count: int = field(compare=False, default=0)
    max_retries: int = field(compare=False, default=3)
    result: Any = field(compare=False, default=None)
    error: Optional[str] = field(compare=False, default=None)


class TokenBucket:
    """令牌桶限速器
    
    用于控制对每个源的请求速率
    """
    
    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: 每秒生成的令牌数
            capacity: 桶的最大容量
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_time = time.time()
        self.lock = threading.Lock()
    
    def acquire(self, tokens: int = 1, block: bool = True, timeout: float = None) -> bool:
        """获取令牌
        
        Args:
            tokens: 需要的令牌数
            block: 是否阻塞等待
            timeout: 超时时间（秒）
        
        Returns:
            是否成功获取令牌
        """
        start_time = time.time()
        
        while True:
            with self.lock:
                # 补充令牌
                now = time.time()
                elapsed = now - self.last_time
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_time = now
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
            
            if not block:
                return False
            
            if timeout and (time.time() - start_time) >= timeout:
                return False
            
            # 等待一段时间后重试
            time.sleep(0.1)
    
    def get_wait_time(self, tokens: int = 1) -> float:
        """计算需要等待的时间"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_time
            current_tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            
            if current_tokens >= tokens:
                return 0
            
            needed = tokens - current_tokens
            return needed / self.rate


class SourceHealthMonitor:
    """信源健康监控"""
    
    def __init__(self, cooldown_seconds: int = 1800):
        """
        Args:
            cooldown_seconds: 默认冷却时间（秒）
        """
        self.cooldown_seconds = cooldown_seconds
        self.source_status: Dict[str, Dict] = {}
        self.lock = threading.Lock()
    
    def mark_healthy(self, source: str):
        """标记源为健康"""
        with self.lock:
            self.source_status[source] = {
                'healthy': True,
                'last_success': datetime.now(),
                'consecutive_failures': 0,
                'cooldown_until': None,
            }
    
    def mark_failure(self, source: str, reason: str = None, cooldown: int = None):
        """标记源失败"""
        with self.lock:
            if source not in self.source_status:
                self.source_status[source] = {
                    'healthy': True,
                    'consecutive_failures': 0,
                }
            
            status = self.source_status[source]
            status['consecutive_failures'] = status.get('consecutive_failures', 0) + 1
            status['last_failure'] = datetime.now()
            status['last_failure_reason'] = reason
            
            # 连续失败3次以上进入冷却
            if status['consecutive_failures'] >= 3:
                cd = cooldown or self.cooldown_seconds
                status['healthy'] = False
                status['cooldown_until'] = datetime.now() + timedelta(seconds=cd)
                logger.warning(f"[健康监控] {source} 进入冷却期 {cd}秒, 原因: {reason}")
    
    def is_healthy(self, source: str) -> bool:
        """检查源是否健康可用"""
        with self.lock:
            if source not in self.source_status:
                return True  # 新源默认健康
            
            status = self.source_status[source]
            
            # 检查冷却期是否结束
            if status.get('cooldown_until'):
                if datetime.now() >= status['cooldown_until']:
                    # 冷却期结束，恢复健康
                    status['healthy'] = True
                    status['cooldown_until'] = None
                    status['consecutive_failures'] = 0
                    logger.info(f"[健康监控] {source} 冷却期结束，恢复可用")
                    return True
                return False
            
            return status.get('healthy', True)
    
    def get_status(self) -> Dict[str, Dict]:
        """获取所有源的状态"""
        with self.lock:
            return dict(self.source_status)


class CrawlerQueue:
    """智能爬虫调度队列
    
    特性：
    1. 优先级队列 - 重要任务优先处理
    2. 令牌桶限速 - 控制每个源的请求速率
    3. 健康监控 - 自动跳过不健康的源
    4. 持久化 - 任务可持久化到SQLite
    5. 指数退避重试
    """
    
    # 各信源的默认速率限制（每秒请求数）
    DEFAULT_RATE_LIMITS = {
        'searxng': 0.2,          # SearXNG: 5秒1次（避免限流）
        'eastmoney': 0.5,        # 东方财富: 2秒1次
        'sina': 0.5,             # 新浪财经
        'tencent': 0.5,          # 腾讯财经
        'tonghuashun': 0.3,      # 同花顺
        'cls': 0.5,              # 财联社
        'cninfo': 0.3,           # 巨潮资讯
        'sse': 0.2,              # 上交所
        'szse': 0.2,             # 深交所
        'csrc': 0.2,             # 证监会
        'default': 0.5,          # 默认
    }
    
    def __init__(
        self,
        db_path: str = None,
        max_workers: int = 3,
        enable_persistence: bool = True
    ):
        """
        Args:
            db_path: SQLite数据库路径
            max_workers: 最大工作线程数
            enable_persistence: 是否启用持久化
        """
        self.db_path = db_path or os.path.join(
            os.path.dirname(__file__), '..', 'data', 'crawler_queue.db'
        )
        self.max_workers = max_workers
        self.enable_persistence = enable_persistence
        
        # 优先级队列
        self.task_queue = queue.PriorityQueue()
        
        # 各源的令牌桶
        self.rate_limiters: Dict[str, TokenBucket] = {}
        self.rate_limiters_lock = threading.Lock()
        
        # 健康监控
        self.health_monitor = SourceHealthMonitor()
        
        # 任务注册表
        self.tasks: Dict[str, CrawlerTask] = {}
        self.tasks_lock = threading.Lock()
        
        # 统计
        self.stats = {
            'submitted': 0,
            'completed': 0,
            'failed': 0,
            'retried': 0,
        }
        self.stats_lock = threading.Lock()
        
        # 控制
        self.is_running = False
        self.stop_event = threading.Event()
        self.workers: List[threading.Thread] = []
        
        # 任务计数器
        self._task_counter = 0
        self._task_counter_lock = threading.Lock()
        
        # 初始化数据库
        if self.enable_persistence:
            self._init_db()
    
    def _init_db(self):
        """初始化SQLite数据库"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawler_tasks (
                task_id TEXT PRIMARY KEY,
                source TEXT,
                task_type TEXT,
                query TEXT,
                params TEXT,
                priority INTEGER,
                status TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT,
                completed_at TEXT,
                result TEXT,
                error TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_status ON crawler_tasks(status)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_source ON crawler_tasks(source)
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info(f"[队列] 数据库初始化完成: {self.db_path}")
    
    def _get_rate_limiter(self, source: str) -> TokenBucket:
        """获取或创建源的令牌桶"""
        with self.rate_limiters_lock:
            if source not in self.rate_limiters:
                rate = self.DEFAULT_RATE_LIMITS.get(source, self.DEFAULT_RATE_LIMITS['default'])
                # 容量设为速率的2倍，允许短时突发
                self.rate_limiters[source] = TokenBucket(rate=rate, capacity=max(2, int(rate * 2)))
                logger.debug(f"[队列] 创建限速器 {source}: {rate}/秒")
            return self.rate_limiters[source]
    
    def _generate_task_id(self) -> str:
        """生成唯一任务ID"""
        with self._task_counter_lock:
            self._task_counter += 1
            return f"crawl_{self._task_counter}_{int(time.time() * 1000)}"
    
    def submit(
        self,
        source: str,
        task_type: str,
        query: str,
        params: Dict[str, Any] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        callback: Callable = None,
        max_retries: int = 3
    ) -> str:
        """提交爬虫任务
        
        Args:
            source: 信源名称
            task_type: 任务类型
            query: 搜索关键词
            params: 额外参数
            priority: 优先级
            callback: 完成回调
            max_retries: 最大重试次数
        
        Returns:
            任务ID
        """
        task_id = self._generate_task_id()
        
        task = CrawlerTask(
            priority=priority.value,
            task_id=task_id,
            source=source,
            task_type=task_type,
            query=query,
            params=params or {},
            callback=callback,
            max_retries=max_retries,
        )
        
        with self.tasks_lock:
            self.tasks[task_id] = task
        
        self.task_queue.put(task)
        
        with self.stats_lock:
            self.stats['submitted'] += 1
        
        # 持久化
        if self.enable_persistence:
            self._persist_task(task)
        
        logger.debug(f"[队列] 任务已提交: {task_id} source={source} type={task_type} query={query[:30]}")
        return task_id
    
    def _persist_task(self, task: CrawlerTask):
        """持久化任务到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO crawler_tasks 
                (task_id, source, task_type, query, params, priority, status, retry_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task.task_id,
                task.source,
                task.task_type,
                task.query,
                json.dumps(task.params, ensure_ascii=False),
                task.priority,
                task.status.value,
                task.retry_count,
                task.created_at.isoformat(),
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[队列] 持久化失败: {e}")
    
    def _update_task_status(self, task: CrawlerTask):
        """更新任务状态"""
        if self.enable_persistence:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE crawler_tasks 
                    SET status = ?, retry_count = ?, completed_at = ?, result = ?, error = ?
                    WHERE task_id = ?
                ''', (
                    task.status.value,
                    task.retry_count,
                    datetime.now().isoformat() if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) else None,
                    json.dumps(task.result, ensure_ascii=False) if task.result else None,
                    task.error,
                    task.task_id,
                ))
                
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"[队列] 更新状态失败: {e}")
    
    def start(self, crawler_registry: Dict[str, Callable] = None):
        """启动队列处理
        
        Args:
            crawler_registry: 爬虫函数注册表 {source: crawler_func}
        """
        if self.is_running:
            return
        
        self.crawler_registry = crawler_registry or {}
        self.is_running = True
        self.stop_event.clear()
        
        # 启动工作线程
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"CrawlerWorker-{i}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
        
        logger.info(f"✅ [队列] 爬虫队列已启动，工作线程数: {self.max_workers}")
    
    def stop(self, timeout: float = 10):
        """停止队列处理"""
        if not self.is_running:
            return
        
        self.stop_event.set()
        
        for worker in self.workers:
            worker.join(timeout=timeout / self.max_workers)
        
        self.workers.clear()
        self.is_running = False
        
        logger.info("⛔ [队列] 爬虫队列已停止")
    
    def _worker_loop(self):
        """工作线程主循环"""
        while not self.stop_event.is_set():
            try:
                # 从队列获取任务（带超时）
                try:
                    task = self.task_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # 检查源是否健康
                if not self.health_monitor.is_healthy(task.source):
                    # 源不健康，延迟重新入队
                    if task.retry_count < task.max_retries:
                        task.retry_count += 1
                        task.status = TaskStatus.RETRY
                        time.sleep(2)  # 短暂等待
                        self.task_queue.put(task)
                    else:
                        task.status = TaskStatus.FAILED
                        task.error = f"Source {task.source} unhealthy after {task.max_retries} retries"
                        self._update_task_status(task)
                        with self.stats_lock:
                            self.stats['failed'] += 1
                    continue
                
                # 获取令牌（限速）
                rate_limiter = self._get_rate_limiter(task.source)
                wait_time = rate_limiter.get_wait_time()
                if wait_time > 0:
                    logger.debug(f"[队列] 限速等待 {task.source}: {wait_time:.2f}秒")
                    time.sleep(wait_time)
                
                rate_limiter.acquire(block=True, timeout=30)
                
                # 执行任务
                task.status = TaskStatus.RUNNING
                self._execute_task(task)
                
            except Exception as e:
                logger.error(f"[队列] 工作线程异常: {e}")
    
    def _execute_task(self, task: CrawlerTask):
        """执行爬虫任务"""
        try:
            # 获取对应的爬虫函数
            crawler_func = self.crawler_registry.get(task.source)
            
            if not crawler_func:
                # 使用默认的SearXNG爬虫
                crawler_func = self.crawler_registry.get('default')
            
            if not crawler_func:
                raise ValueError(f"No crawler registered for source: {task.source}")
            
            # 执行爬虫
            result = crawler_func(
                query=task.query,
                task_type=task.task_type,
                **task.params
            )
            
            task.result = result
            task.status = TaskStatus.COMPLETED
            self._update_task_status(task)
            
            # 标记源健康
            self.health_monitor.mark_healthy(task.source)
            
            with self.stats_lock:
                self.stats['completed'] += 1
            
            # 执行回调
            if task.callback:
                try:
                    task.callback(task)
                except Exception as e:
                    logger.error(f"[队列] 回调执行失败: {e}")
            
            logger.debug(f"[队列] 任务完成: {task.task_id}")
            
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"[队列] 任务失败: {task.task_id} - {error_msg}")
            
            # 检测限流错误
            is_rate_limit = any(kw in error_msg.lower() for kw in ['captcha', 'rate limit', 'too many', '429'])
            
            if is_rate_limit:
                self.health_monitor.mark_failure(task.source, error_msg, cooldown=1800)
            else:
                self.health_monitor.mark_failure(task.source, error_msg)
            
            # 重试逻辑
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = TaskStatus.RETRY
                
                # 指数退避
                backoff = min(300, 10 * (2 ** task.retry_count))
                logger.info(f"[队列] 任务重试 ({task.retry_count}/{task.max_retries}): {task.task_id}, 等待{backoff}秒")
                
                with self.stats_lock:
                    self.stats['retried'] += 1
                
                # 延迟重新入队
                def delayed_requeue():
                    time.sleep(backoff)
                    if not self.stop_event.is_set():
                        self.task_queue.put(task)
                
                threading.Thread(target=delayed_requeue, daemon=True).start()
            else:
                task.status = TaskStatus.FAILED
                task.error = error_msg
                self._update_task_status(task)
                
                with self.stats_lock:
                    self.stats['failed'] += 1
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        with self.tasks_lock:
            task = self.tasks.get(task_id)
            if task:
                return {
                    'task_id': task.task_id,
                    'source': task.source,
                    'task_type': task.task_type,
                    'query': task.query,
                    'status': task.status.value,
                    'retry_count': task.retry_count,
                    'result': task.result,
                    'error': task.error,
                }
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取队列统计"""
        with self.stats_lock:
            return {
                **self.stats,
                'queue_size': self.task_queue.qsize(),
                'source_health': self.health_monitor.get_status(),
            }
    
    def get_pending_count(self) -> int:
        """获取待处理任务数"""
        return self.task_queue.qsize()


# 全局队列实例
_global_queue: Optional[CrawlerQueue] = None


def get_crawler_queue() -> CrawlerQueue:
    """获取全局爬虫队列"""
    global _global_queue
    if _global_queue is None:
        _global_queue = CrawlerQueue()
    return _global_queue
