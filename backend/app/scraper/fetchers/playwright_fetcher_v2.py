"""
改进的Playwright fetcher - 支持state轮换、自动降级、失败监控

主要改进:
1. 多state轮换 - 支持多个登录状态文件，失败时自动切换
2. 自动降级 - Playwright失败时自动降级到requests fetcher
3. 失败监控 - 追踪state失效情况，标记待更新
4. 代理轮换 - 支持代理列表轮换，规避IP封禁
5. 重试机制 - 指数退避重试策略
"""

from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse
import asyncio
import time
import json
import logging
from pathlib import Path
from dataclasses import dataclass

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext
except ImportError:
    async_playwright = None

from ..storage.state_manager import StateManager
from ..utils.http_utils import UserAgentRotator
from ..utils.detect_login import is_login_page
from .requests_fetcher import RequestsFetcher


@dataclass
class StateStatus:
    """State状态追踪"""
    path: str
    failure_count: int = 0
    success_count: int = 0
    last_used: Optional[float] = None
    marked_invalid: bool = False
    
    @property
    def failure_rate(self) -> float:
        total = self.failure_count + self.success_count
        return self.failure_count / total if total > 0 else 0.0
    
    @property
    def is_suspicious(self) -> bool:
        """检查state是否可疑（失败率超过50%）"""
        return self.failure_rate > 0.5 and self.success_count >= 5


class ImprovedPlaywrightFetcher:
    """改进的Playwright fetcher，支持state轮换和自动降级"""
    
    def __init__(
        self,
        state_paths: Optional[List[str]] = None,
        headless: bool = True,
        timeout: int = 30000,
        wait_until: str = "networkidle",
        max_concurrent: int = 3,
        user_agents: Optional[List[str]] = None,
        proxies: Optional[List[str]] = None,
        max_retries: int = 3,
        fallback_to_requests: bool = True,
    ):
        """
        初始化改进的Playwright fetcher
        
        Args:
            state_paths: 登录状态文件列表（用于轮换）
            headless: 是否无头模式
            timeout: 超时时间（毫秒）
            wait_until: 加载条件
            max_concurrent: 最大并发浏览器数
            user_agents: User-Agent列表
            proxies: 代理列表
            max_retries: 最大重试次数
            fallback_to_requests: 失败时是否回退到requests
        """
        if not async_playwright:
            raise ImportError("playwright library is required")
        
        self.state_paths = state_paths or []
        self.state_statuses: Dict[str, StateStatus] = {
            path: StateStatus(path=path) for path in self.state_paths
        }
        self.current_state_index = 0
        
        self.headless = headless
        self.timeout = timeout
        self.wait_until = wait_until
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.fallback_to_requests = fallback_to_requests
        
        self.ua_rotator = UserAgentRotator(user_agents)
        self.proxies = proxies or []
        self.current_proxy_index = 0
        
        self.browser = None
        self.active_contexts = 0
        
        # 请求fetcher用于降级
        self.requests_fetcher = None
        if fallback_to_requests:
            self.requests_fetcher = RequestsFetcher(
                timeout=timeout // 1000,  # 转换为秒
                user_agents=user_agents,
                proxies=proxies
            )
        
        self.logger = logging.getLogger(__name__)
    
    def _get_next_state_path(self) -> Optional[str]:
        """获取下一个state（跳过标记为无效的）"""
        if not self.state_paths:
            return None
        
        # 找到可用的state（优先选择未标记的）
        available_states = [
            (i, path) for i, path in enumerate(self.state_paths)
            if not self.state_statuses[path].marked_invalid
        ]
        
        if not available_states:
            # 所有state都标记为无效，重新启用所有
            for status in self.state_statuses.values():
                status.marked_invalid = False
            available_states = list(enumerate(self.state_paths))
        
        if not available_states:
            return None
        
        # 轮换选择
        idx, path = available_states[self.current_state_index % len(available_states)]
        self.current_state_index += 1
        
        return path
    
    def _get_next_proxy(self) -> Optional[str]:
        """获取下一个代理"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_proxy_index % len(self.proxies)]
        self.current_proxy_index += 1
        
        return proxy
    
    async def _init_browser(self):
        """初始化浏览器"""
        p = await async_playwright().start()
        self.browser = await p.chromium.launch(headless=self.headless)
    
    async def _create_context(self, state_path: Optional[str] = None, proxy: Optional[str] = None):
        """创建浏览器context"""
        kwargs = {
            'viewport': {'width': 1920, 'height': 1080},
            'user_agent': self.ua_rotator.get_next(),
        }
        
        # 加载状态
        if state_path and Path(state_path).exists():
            try:
                kwargs['storage_state'] = state_path
                self.logger.debug(f"Loading storage state from {state_path}")
            except Exception as e:
                self.logger.warning(f"Failed to load state {state_path}: {e}")
        
        # 设置代理
        if proxy:
            kwargs['proxy'] = proxy
            self.logger.debug(f"Using proxy: {proxy}")
        
        return await self.browser.new_context(**kwargs)
    
    async def fetch(
        self,
        url: str,
        selector: Optional[str] = None,
        wait_for_selector: Optional[str] = None,
        with_state: bool = True,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        获取页面内容，支持state轮换和自动降级
        
        Args:
            url: 目标URL
            selector: CSS选择器
            wait_for_selector: 等待选择器
            with_state: 是否使用登录状态
            
        Returns:
            {
                'url': url,
                'status_code': 200,
                'content': 'HTML内容',
                'is_login_page': False,
                'state_used': 'state_path or None',
                'proxy_used': 'proxy or None',
                'fetch_method': 'playwright or requests',
                'elapsed_time': 1.23,
            }
        """
        
        start_time = time.time()
        
        # 尝试用Playwright
        for attempt in range(self.max_retries):
            result = await self._fetch_with_playwright(
                url,
                selector,
                wait_for_selector,
                use_state=with_state and attempt == 0,  # 首次尝试用state
                **kwargs
            )
            
            if result:
                elapsed = time.time() - start_time
                result['elapsed_time'] = elapsed
                result['fetch_method'] = 'playwright'
                
                # 检查是否为登录页
                if result.get('is_login_page'):
                    self.logger.warning(f"Got login page for {url}, trying next state")
                    # 标记该state的失败
                    state_used = result.get('state_used')
                    if state_used and state_used in self.state_statuses:
                        self.state_statuses[state_used].failure_count += 1
                        if self.state_statuses[state_used].is_suspicious:
                            self.state_statuses[state_used].marked_invalid = True
                            self.logger.error(f"State {state_used} marked as invalid (failure rate > 50%)")
                    
                    # 继续重试下一个state
                    if attempt < self.max_retries - 1:
                        continue
                    else:
                        # 所有重试用尽，记录失败state供人工更新
                        self._log_state_failure(url, result)
                        
                        # 尝试降级到requests
                        if self.fallback_to_requests:
                            return await self._fallback_to_requests(url)
                        return None
                
                # 成功获取
                if result.get('state_used') and result['state_used'] in self.state_statuses:
                    self.state_statuses[result['state_used']].success_count += 1
                
                return result
            
            # Playwright失败，等待后重试
            if attempt < self.max_retries - 1:
                backoff = 2 ** attempt  # 指数退避：1s, 2s, 4s
                self.logger.warning(f"Playwright fetch failed for {url}, retrying in {backoff}s")
                await asyncio.sleep(backoff)
        
        # Playwright完全失败，尝试降级
        if self.fallback_to_requests:
            self.logger.info(f"Playwright failed, falling back to requests for {url}")
            return await self._fallback_to_requests(url)
        
        self.logger.error(f"Failed to fetch {url} with all methods")
        return None
    
    async def _fetch_with_playwright(
        self,
        url: str,
        selector: Optional[str] = None,
        wait_for_selector: Optional[str] = None,
        use_state: bool = True,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """使用Playwright获取（内部方法）"""
        
        if not self.browser:
            await self._init_browser()
        
        # 限制并发
        while self.active_contexts >= self.max_concurrent:
            await asyncio.sleep(0.1)
        
        # 选择state和代理
        state_path = self._get_next_state_path() if use_state else None
        proxy = self._get_next_proxy()
        
        context = None
        try:
            self.active_contexts += 1
            context = await self._create_context(state_path, proxy)
            page = await context.new_page()
            
            # 导航
            try:
                await page.goto(url, wait_until=self.wait_until, timeout=self.timeout)
            except Exception as e:
                self.logger.warning(f"Failed to navigate to {url}: {e}")
                return None
            
            # 等待选择器
            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=self.timeout)
                except:
                    self.logger.debug(f"Selector {wait_for_selector} not found")
            
            # 获取内容
            if selector:
                content = await page.locator(selector).inner_html()
            else:
                content = await page.content()
            
            # 检查登录页
            response = page.response()
            is_login, login_reason = is_login_page(
                content,
                dict(response.headers) if response else {},
                url,
                response.status if response else 200
            )
            
            return {
                'url': url,
                'status_code': response.status if response else 200,
                'content': content,
                'is_login_page': is_login,
                'login_reason': login_reason,
                'state_used': state_path,
                'proxy_used': proxy,
            }
        
        except Exception as e:
            self.logger.error(f"Playwright fetch error for {url}: {e}")
            return None
        
        finally:
            if context:
                await context.close()
            self.active_contexts -= 1
    
    async def _fallback_to_requests(self, url: str) -> Optional[Dict[str, Any]]:
        """降级到requests fetcher"""
        
        if not self.requests_fetcher:
            return None
        
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, 
                self.requests_fetcher.fetch,
                url
            )
            
            if result:
                result['fetch_method'] = 'requests'
                result['state_used'] = None
            
            return result
        
        except Exception as e:
            self.logger.error(f"Requests fallback failed for {url}: {e}")
            return None
    
    def _log_state_failure(self, url: str, result: Dict[str, Any]):
        """记录state失败，供人工干预"""
        
        failure_log = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'url': url,
            'state_used': result.get('state_used'),
            'proxy_used': result.get('proxy_used'),
            'login_reason': result.get('login_reason'),
            'response_snippet': result.get('content', '')[:500],
            'state_statuses': {
                path: {
                    'failure_count': status.failure_count,
                    'success_count': status.success_count,
                    'failure_rate': f"{status.failure_rate:.1%}",
                    'marked_invalid': status.marked_invalid,
                }
                for path, status in self.state_statuses.items()
            }
        }
        
        self.logger.error(f"State failure recorded: {json.dumps(failure_log, indent=2, ensure_ascii=False)}")
    
    def get_state_report(self) -> Dict[str, Any]:
        """获取所有state的状态报告"""
        return {
            path: {
                'failure_count': status.failure_count,
                'success_count': status.success_count,
                'failure_rate': f"{status.failure_rate:.1%}",
                'marked_invalid': status.marked_invalid,
            }
            for path, status in self.state_statuses.items()
        }
