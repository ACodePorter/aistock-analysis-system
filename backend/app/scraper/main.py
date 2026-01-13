"""
Main Scraper Orchestrator

协调所有fetcher、状态管理、任务队列、重试逻辑、告警机制
"""

import asyncio
import yaml
import json
import time
from typing import Optional, Dict, Any, List
from pathlib import Path

from .domain_router import DomainRouter
from .utils.detect_login import is_login_page
from .utils.logger import ScraperEventLogger
from .storage.state_manager import StateManager
from .queue.task_queue import TaskQueue, TaskStatus
from .fetchers.wikipedia import WikipediaFetcher
from .fetchers.requests_fetcher import RequestsFetcher
from .fetchers.playwright_fetcher import PlaywrightFetcher


class ScraperOrchestrator:
    """主级Scraper协调器"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        初始化orchestrator
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.config = self._load_config()
        
        # 初始化各个组件
        self.domain_router = DomainRouter(self.config.get('domains', {}))
        self.event_logger = ScraperEventLogger(
            self.config.get('logging', {}).get('file', 'scraper.log')
        )
        self.task_queue = TaskQueue(
            self.config.get('queue', {}).get('db_path', 'scraper_queue.db')
        )
        
        # 初始化状态管理器
        self.state_managers = {}  # domain -> StateManager
        
        # 从全局storage_states配置中初始化
        storage_states_config = self.config.get('storage_states', {})
        for domain, state_path in storage_states_config.items():
            if state_path:
                # state_path可能是字符串或列表
                paths = [state_path] if isinstance(state_path, str) else state_path
                sm = StateManager(paths)
                self.state_managers[domain] = sm
        
        # 初始化fetcher池
        self.fetchers = {}
        self._init_fetchers()
        
        # 运行状态
        self.running = False
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'manual_review': 0,
        }
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.event_logger.log_event(
                'error',
                'Failed to load config',
                {'error': str(e), 'path': self.config_path}
            )
            raise
    
    def _init_fetchers(self):
        """初始化所有fetcher"""
        # Wikipedia fetcher
        self.fetchers['wikipedia'] = WikipediaFetcher()
        
        # Requests fetcher - 从rate_limit_per_domain配置中获取默认速率
        rate_limits = self.config.get('rate_limit_per_domain', {})
        default_rate_limit = rate_limits.get('default', 1.0)
        
        self.fetchers['requests'] = RequestsFetcher(
            rate_limit=default_rate_limit,
            timeout=self.config.get('browser', {}).get('timeout', 30),
            user_agents=self.config.get('user_agents', []),
            proxies=self.config.get('proxies', [])
        )
        
        # Playwright fetcher
        try:
            self.fetchers['playwright'] = PlaywrightFetcher(
                headless=self.config.get('browser', {}).get('headless', True),
                timeout=self.config.get('browser', {}).get('timeout', 30000),
                max_concurrent=self.config.get('browser', {}).get('max_concurrent', 3),
                proxies=self.config.get('proxies', []),
            )
        except ImportError:
            self.event_logger.log_event(
                'warning',
                'Playwright not installed, browser fetcher disabled',
                {}
            )
    
    def add_url(self, url: str, priority: int = 0) -> int:
        """
        添加URL到队列
        
        Args:
            url: 页面URL
            priority: 优先级
            
        Returns:
            任务ID
        """
        # 获取域名
        domain = self.domain_router.get_domain(url)
        
        # 入队
        task_id = self.task_queue.enqueue(url, domain, priority)
        
        self.event_logger.log_event(
            'task_enqueued',
            f'Task {task_id} enqueued',
            {'url': url, 'domain': domain, 'priority': priority}
        )
        
        return task_id
    
    def add_urls(self, urls: List[str], priority: int = 0) -> List[int]:
        """批量添加URL"""
        task_ids = []
        for url in urls:
            task_id = self.add_url(url, priority)
            task_ids.append(task_id)
        return task_ids
    
    async def process_queue(
        self,
        max_concurrent: int = 5,
        max_duration: Optional[int] = None,
    ):
        """
        处理队列中的所有任务
        
        Args:
            max_concurrent: 最大并发任务数
            max_duration: 最大运行时间（秒）
        """
        self.running = True
        start_time = time.time()
        
        self.event_logger.log_event(
            'scraper_start',
            'Scraper started',
            {'max_concurrent': max_concurrent, 'max_duration': max_duration}
        )
        
        try:
            # 创建任务队列
            tasks = set()
            
            while self.running:
                # 检查最大运行时间
                if max_duration and (time.time() - start_time) > max_duration:
                    self.event_logger.log_event(
                        'scraper_timeout',
                        'Scraper timeout reached',
                        {'duration': max_duration}
                    )
                    break
                
                # 补充并发任务
                while len(tasks) < max_concurrent:
                    task = self.task_queue.dequeue()
                    if not task:
                        # 没有更多待处理任务
                        if not tasks:
                            # 所有任务完成
                            break
                        break
                    
                    # 创建处理任务
                    coro = self._process_task(task)
                    asyncio.create_task(coro)
                    tasks.add(coro)
                
                # 如果有任务在运行，等待一个完成
                if tasks:
                    done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        tasks.discard(task)
                else:
                    # 没有任务，可以退出
                    break
                
                # 短暂暂停
                await asyncio.sleep(0.1)
        
        except Exception as e:
            self.event_logger.log_event(
                'scraper_error',
                'Scraper error',
                {'error': str(e)}
            )
        finally:
            self.running = False
            elapsed = time.time() - start_time
            self.event_logger.log_event(
                'scraper_stop',
                'Scraper stopped',
                {'elapsed_time': elapsed, 'stats': self.stats}
            )
    
    async def _process_task(self, task: Dict[str, Any]):
        """处理单个任务"""
        task_id = task['id']
        url = task['url']
        domain = task['domain']
        attempts = task['attempts']
        max_attempts = task['max_attempts']
        
        self.event_logger.log_event(
            'task_start',
            f'Task {task_id} started',
            {'url': url, 'domain': domain, 'attempt': attempts}
        )
        
        try:
            # 获取router配置
            router_config = self.domain_router.route(url)
            fetcher_type = router_config['fetcher']
            
            # 获取fetcher
            if fetcher_type not in self.fetchers:
                raise ValueError(f"Unknown fetcher type: {fetcher_type}")
            
            fetcher = self.fetchers[fetcher_type]
            
            # 获取结果
            result = await self._fetch_with_retry(
                fetcher,
                url,
                domain,
                fetcher_type,
                task_id,
            )
            
            if result:
                # 成功
                self.task_queue.mark_success(task_id, result)
                self.event_logger.log_event(
                    'task_success',
                    f'Task {task_id} succeeded',
                    {
                        'url': url,
                        'content_length': result.get('content_length', 0),
                        'elapsed_time': result.get('elapsed_time', 0),
                    }
                )
                self.stats['success'] += 1
            else:
                # 失败，标记为失败
                should_retry = self.task_queue.mark_failed(
                    task_id,
                    "Failed to fetch",
                    None
                )
                
                if should_retry:
                    self.event_logger.log_event(
                        'task_retry',
                        f'Task {task_id} will be retried',
                        {'attempt': attempts, 'max_attempts': max_attempts}
                    )
                    self.stats['failed'] += 1
                else:
                    self.event_logger.log_event(
                        'task_manual_review',
                        f'Task {task_id} moved to manual review',
                        {'url': url, 'domain': domain}
                    )
                    self.stats['manual_review'] += 1
        
        except Exception as e:
            # 异常处理
            should_retry = self.task_queue.mark_failed(
                task_id,
                str(e),
                None
            )
            
            self.event_logger.log_event(
                'task_error',
                f'Task {task_id} error',
                {'url': url, 'error': str(e), 'retry': should_retry}
            )
            
            if not should_retry:
                self.stats['manual_review'] += 1
        
        self.stats['total'] += 1
    
    async def _fetch_with_retry(
        self,
        fetcher,
        url: str,
        domain: str,
        fetcher_type: str,
        task_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        带重试的获取（处理登录检测和状态轮转）
        
        Returns:
            Result dict 或 None
        """
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # 调用fetcher
                if fetcher_type == 'wikipedia':
                    result = await fetcher.fetch_async(url)
                elif fetcher_type == 'playwright':
                    result = await fetcher.fetch(url)
                else:
                    # requests fetcher
                    result = fetcher.fetch(url)
                
                if not result:
                    return None
                
                # 检查是否为登录页
                if result.get('is_login_page'):
                    # 尝试轮转state
                    state_manager = self.state_managers.get(domain)
                    if state_manager:
                        state_manager.mark_state_failure(result.get('state_used'))
                        # 继续重试
                        if attempt < max_retries - 1:
                            continue
                    return None
                
                return result
            
            except Exception as e:
                self.event_logger.log_event(
                    'fetch_error',
                    f'Fetch error on attempt {attempt + 1}',
                    {'url': url, 'error': str(e)}
                )
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    continue
                
                return None
        
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        queue_stats = self.task_queue.get_stats()
        return {
            'scraper': self.stats,
            'queue': queue_stats,
        }
    
    def get_failed_tasks(self) -> List[Dict[str, Any]]:
        """获取失败的任务"""
        return self.task_queue.get_failed_tasks()
    
    async def close(self):
        """关闭所有资源"""
        self.running = False
        
        # 关闭playwright
        if 'playwright' in self.fetchers:
            await self.fetchers['playwright'].close()
        
        self.event_logger.log_event(
            'scraper_closed',
            'Scraper resources closed',
            {'stats': self.stats}
        )


# 便利函数
async def run_scraper(
    urls: List[str],
    config_path: str = "config.yaml",
    max_concurrent: int = 5,
    max_duration: Optional[int] = None,
) -> Dict[str, Any]:
    """
    运行scraper
    
    Args:
        urls: URL列表
        config_path: 配置文件路径
        max_concurrent: 最大并发数
        max_duration: 最大运行时间（秒）
        
    Returns:
        统计信息
    """
    orchestrator = ScraperOrchestrator(config_path)
    
    # 添加URLs
    orchestrator.add_urls(urls)
    
    # 处理队列
    await orchestrator.process_queue(max_concurrent, max_duration)
    
    # 获取统计
    stats = orchestrator.get_stats()
    
    # 关闭资源
    await orchestrator.close()
    
    return stats


def run_scraper_sync(
    urls: List[str],
    config_path: str = "config.yaml",
    max_concurrent: int = 5,
    max_duration: Optional[int] = None,
) -> Dict[str, Any]:
    """同步版本"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        return loop.run_until_complete(
            run_scraper(urls, config_path, max_concurrent, max_duration)
        )
    finally:
        loop.close()
