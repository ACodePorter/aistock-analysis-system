"""
HTTP工具模块

提供User-Agent轮换、请求头管理等功能
"""

import random
from typing import List, Dict, Optional


class UserAgentRotator:
    """User-Agent轮换器"""
    
    DEFAULT_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]
    
    def __init__(self, user_agents: Optional[List[str]] = None):
        """
        初始化User-Agent轮换器
        
        Args:
            user_agents: User-Agent列表，如果为None则使用默认列表
        """
        self.user_agents = user_agents or self.DEFAULT_USER_AGENTS
        self.current_index = 0
    
    def get_random(self) -> str:
        """获取随机User-Agent"""
        return random.choice(self.user_agents)
    
    def get_next(self) -> str:
        """获取下一个User-Agent (轮转)"""
        ua = self.user_agents[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.user_agents)
        return ua


class HeaderManager:
    """HTTP请求头管理器"""
    
    @staticmethod
    def get_default_headers(user_agent: Optional[str] = None) -> Dict[str, str]:
        """
        获取默认的请求头
        
        Args:
            user_agent: 自定义User-Agent，如果为None则随机选择
            
        Returns:
            请求头字典
        """
        ua_rotator = UserAgentRotator()
        user_agent = user_agent or ua_rotator.get_random()
        
        return {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }
    
    @staticmethod
    def get_headers_for_domain(domain: str, user_agent: Optional[str] = None) -> Dict[str, str]:
        """
        获取适配特定域名的请求头
        
        Args:
            domain: 域名
            user_agent: 自定义User-Agent
            
        Returns:
            请求头字典
        """
        headers = HeaderManager.get_default_headers(user_agent)
        
        # 特定域名的请求头调整
        if 'api' in domain or 'json' in domain:
            headers['Accept'] = 'application/json'
        
        if 'tianyancha' in domain or 'qcc' in domain:
            # 这些站点可能检查Referer
            headers['Referer'] = f'https://{domain}/'
        
        return headers


class RateLimiter:
    """速率限制器 (Token Bucket算法)"""
    
    def __init__(self, rate: float):
        """
        初始化速率限制器
        
        Args:
            rate: 每秒允许的请求数
        """
        self.rate = rate
        self.tokens = rate
        self.last_update = None
    
    def wait_if_needed(self) -> float:
        """
        如果需要则等待，返回实际等待的时间（秒）
        """
        import time
        
        now = time.time()
        
        if self.last_update is None:
            self.last_update = now
            return 0.0
        
        elapsed = now - self.last_update
        self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
        self.last_update = now
        
        if self.tokens < 1:
            wait_time = (1 - self.tokens) / self.rate
            time.sleep(wait_time)
            self.tokens = 0
            return wait_time
        
        self.tokens -= 1
        return 0.0


def get_retry_backoff(attempt: int, base: float = 2, max_backoff: float = 60) -> float:
    """
    计算指数退避时间
    
    Args:
        attempt: 当前尝试次数 (从0开始)
        base: 退避底数
        max_backoff: 最大退避时间（秒）
        
    Returns:
        应该等待的时间（秒）
    """
    backoff = min(base ** attempt, max_backoff)
    # 添加随机抖动 (±20%)
    jitter = backoff * 0.2 * random.random() * (1 if random.random() > 0.5 else -1)
    return backoff + jitter
