"""
Requests fetcher

使用requests库获取页面内容（支持cookies和代理）
"""

from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
import time

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None

from ..utils.http_utils import HeaderManager, RateLimiter, get_retry_backoff
from ..utils.detect_login import is_login_page


class RequestsFetcher:
    """Requests-based fetcher"""
    
    def __init__(
        self,
        rate_limit: float = 1.0,
        timeout: int = 30,
        max_retries: int = 3,
        user_agents: Optional[List[str]] = None,
        proxies: Optional[List[str]] = None
    ):
        """
        初始化Requests fetcher
        
        Args:
            rate_limit: 每秒请求数限制
            timeout: 请求超时（秒）
            max_retries: 最大重试次数
            user_agents: User-Agent列表
            proxies: 代理列表
        """
        if not requests:
            raise ImportError("requests library is required")
        
        self.rate_limit = rate_limit
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agents = user_agents
        self.proxies = proxies or []
        self.current_proxy_index = 0
        self.rate_limiters = {}  # 每个域名一个rate limiter
    
    def fetch(
        self,
        url: str,
        cookies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        获取页面内容
        
        Args:
            url: 要获取的URL
            cookies: Cookie字典
            headers: 自定义请求头
            **kwargs: 其他参数传递给requests
            
        Returns:
            {
                'url': url,
                'status_code': 200,
                'content': 'HTML内容',
                'headers': {...},
                'is_login_page': False,
                'elapsed_time': 1.23,
                'proxy_used': None,
            }
            如果获取失败返回None
        """
        
        # 应用rate limiting
        domain = urlparse(url).netloc
        if domain not in self.rate_limiters:
            self.rate_limiters[domain] = RateLimiter(self.rate_limit)
        
        self.rate_limiters[domain].wait_if_needed()
        
        # 构建session
        session = self._create_session()
        
        # 构建请求参数
        req_kwargs = {
            'timeout': self.timeout,
            'allow_redirects': True,
            'verify': True,
            **kwargs
        }
        
        # 添加headers
        if headers is None:
            headers = HeaderManager.get_default_headers()
        req_kwargs['headers'] = headers
        
        # 添加cookies
        if cookies:
            req_kwargs['cookies'] = cookies
        
        # 尝试请求
        last_error = None
        proxy_used = None
        
        for attempt in range(self.max_retries):
            try:
                # 可选择性地使用代理
                if self.proxies and attempt > 0:
                    proxy = self.proxies[self.current_proxy_index]
                    req_kwargs['proxies'] = {'http': proxy, 'https': proxy}
                    proxy_used = proxy
                    self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
                
                # 发送请求
                start_time = time.time()
                response = session.get(url, **req_kwargs)
                elapsed_time = time.time() - start_time
                
                # 检查响应
                is_login, login_reason = is_login_page(
                    response.text,
                    dict(response.headers),
                    url,
                    response.status_code
                )
                
                return {
                    'url': url,
                    'status_code': response.status_code,
                    'content': response.text,
                    'headers': dict(response.headers),
                    'is_login_page': is_login,
                    'login_reason': login_reason if is_login else None,
                    'elapsed_time': elapsed_time,
                    'proxy_used': proxy_used,
                    'encoding': response.encoding,
                    'content_length': len(response.text),
                }
            
            except Exception as e:
                last_error = e
                
                if attempt < self.max_retries - 1:
                    # 计算退避时间
                    backoff = get_retry_backoff(attempt)
                    time.sleep(backoff)
                
            finally:
                session.close()
        
        # 所有重试都失败了
        print(f"Failed to fetch {url} after {self.max_retries} attempts: {last_error}")
        return None
    
    def _create_session(self) -> requests.Session:
        """创建带重试策略的Session"""
        
        session = requests.Session()
        
        # 配置重试策略
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            backoff_factor=1
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session


class RequestsFetcherWithCookies(RequestsFetcher):
    """支持cookie持久化的Requests fetcher"""
    
    def __init__(self, cookie_jar_path: Optional[str] = None, **kwargs):
        """
        初始化
        
        Args:
            cookie_jar_path: cookiejar文件路径
            **kwargs: 传递给RequestsFetcher
        """
        super().__init__(**kwargs)
        self.cookie_jar_path = cookie_jar_path
        self.cookies = {}
        
        if cookie_jar_path:
            self._load_cookies()
    
    def _load_cookies(self):
        """从文件加载cookies"""
        try:
            import json
            from pathlib import Path
            
            path = Path(self.cookie_jar_path)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    self.cookies = json.load(f)
        except Exception as e:
            print(f"Failed to load cookies: {e}")
    
    def _save_cookies(self):
        """保存cookies到文件"""
        try:
            import json
            from pathlib import Path
            
            if self.cookie_jar_path:
                path = Path(self.cookie_jar_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.cookies, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save cookies: {e}")
    
    def fetch(self, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        """使用持久化的cookies获取页面"""
        result = super().fetch(url, cookies=self.cookies, **kwargs)
        
        # 从响应中更新cookies
        if result and result.get('headers', {}).get('Set-Cookie'):
            # 解析Set-Cookie头并更新
            pass
        
        self._save_cookies()
        return result
