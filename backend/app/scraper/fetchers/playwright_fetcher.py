"""
Playwright fetcher

使用Playwright浏览器获取页面内容（支持JavaScript渲染和登录状态）
"""

from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
import asyncio
import time

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext
except ImportError:
    async_playwright = None
    Browser = None
    BrowserContext = None

from ..storage.state_manager import StateManager
from ..utils.http_utils import UserAgentRotator
from ..utils.detect_login import is_login_page


class PlaywrightFetcher:
    """Playwright-based fetcher"""
    
    def __init__(
        self,
        state_manager: Optional[StateManager] = None,
        headless: bool = True,
        timeout: int = 30000,
        wait_until: str = "networkidle",
        max_concurrent: int = 3,
        user_agents: Optional[List[str]] = None,
        proxies: Optional[List[str]] = None,
    ):
        """
        初始化Playwright fetcher
        
        Args:
            state_manager: 状态管理器（包含storage_state）
            headless: 是否无头模式
            timeout: 页面加载超时（毫秒）
            wait_until: 等待条件 ('load', 'domcontentloaded', 'networkidle')
            max_concurrent: 最大并发浏览器数
            user_agents: User-Agent列表
            proxies: 代理列表
        """
        if not async_playwright:
            raise ImportError("playwright library is required")
        
        self.state_manager = state_manager
        self.headless = headless
        self.timeout = timeout
        self.wait_until = wait_until
        self.max_concurrent = max_concurrent
        self.user_agents = user_agents
        self.proxies = proxies or []
        self.current_proxy_index = 0
        
        self.browser = None
        self.contexts = {}
        self.active_contexts = 0
        self.ua_rotator = UserAgentRotator(user_agents)
    
    async def fetch(
        self,
        url: str,
        selector: Optional[str] = None,
        wait_for_selector: Optional[str] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        获取页面内容
        
        Args:
            url: 要获取的URL
            selector: 如果指定，只提取该CSS选择器的HTML内容
            wait_for_selector: 等待该选择器出现后再提取
            **kwargs: 其他参数
            
        Returns:
            {
                'url': url,
                'status_code': 200,
                'content': 'HTML内容',
                'is_login_page': False,
                'state_used': 'state_path',
                'elapsed_time': 1.23,
                'proxy_used': None,
            }
            如果获取失败返回None
        """
        
        start_time = time.time()
        
        try:
            # 初始化浏览器
            if not self.browser:
                await self._init_browser()
            
            # 限制并发
            while self.active_contexts >= self.max_concurrent:
                await asyncio.sleep(0.1)
            
            # 创建context
            context = await self._create_context()
            self.active_contexts += 1
            
            try:
                # 打开页面
                page = await context.new_page()
                
                # 设置User-Agent
                ua = self.ua_rotator.get_next()
                await page.context.set_extra_http_headers({
                    'User-Agent': ua,
                })
                
                # 导航到页面
                try:
                    await page.goto(url, wait_until=self.wait_until, timeout=self.timeout)
                except Exception as e:
                    print(f"Failed to navigate to {url}: {e}")
                    return None
                
                # 等待特定选择器（可选）
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(wait_for_selector, timeout=self.timeout)
                    except:
                        print(f"Selector {wait_for_selector} not found within timeout")
                
                # 获取页面内容
                if selector:
                    content = await page.locator(selector).inner_html()
                else:
                    content = await page.content()
                
                # 检查是否为登录页
                is_login, login_reason = is_login_page(
                    content,
                    dict(page.response().headers) if page.response() else {},
                    url,
                    page.response().status if page.response() else 200
                )
                
                elapsed_time = time.time() - start_time
                
                result = {
                    'url': url,
                    'status_code': page.response().status if page.response() else 200,
                    'content': content,
                    'is_login_page': is_login,
                    'login_reason': login_reason if is_login else None,
                    'state_used': self.state_manager.get_current_state_path() if self.state_manager else None,
                    'elapsed_time': elapsed_time,
                    'proxy_used': None,  # TODO: 记录使用的代理
                    'content_length': len(content),
                    'user_agent': ua,
                }
                
                if is_login:
                    # 标记state失败
                    if self.state_manager:
                        state_path = self.state_manager.get_current_state_path()
                        if state_path:
                            self.state_manager.mark_state_failure(state_path)
                
                await page.close()
                return result
            
            finally:
                await context.close()
                self.active_contexts -= 1
        
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    async def _init_browser(self):
        """初始化浏览器"""
        playwright = await async_playwright().start()
        
        launch_args = {
            'headless': self.headless,
        }
        
        # 添加代理（可选）
        if self.proxies:
            proxy = self.proxies[self.current_proxy_index]
            launch_args['proxy'] = {
                'server': proxy,
            }
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        
        self.browser = await playwright.chromium.launch(**launch_args)
    
    async def _create_context(self) -> BrowserContext:
        """创建浏览器context（可能加载storage_state）"""
        
        context_args = {
            'viewport': {'width': 1280, 'height': 720},
        }
        
        # 加载storage_state（登录状态）
        if self.state_manager:
            state = self.state_manager.get_next_state()
            if state:
                context_args['storage_state'] = state
        
        context = await self.browser.new_context(**context_args)
        return context
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            self.browser = None


class PlaywrightFetcherSync:
    """同步接口包装"""
    
    def __init__(self, **kwargs):
        self.fetcher = PlaywrightFetcher(**kwargs)
        self.loop = None
    
    def fetch(self, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        """同步调用async fetch"""
        try:
            if self.loop is None:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
            
            return self.loop.run_until_complete(self.fetcher.fetch(url, **kwargs))
        except Exception as e:
            print(f"Error in sync fetch: {e}")
            return None
    
    def close(self):
        """关闭资源"""
        try:
            if self.loop:
                self.loop.run_until_complete(self.fetcher.close())
        except:
            pass
