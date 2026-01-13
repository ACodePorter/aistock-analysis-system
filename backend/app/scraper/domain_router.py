"""
域名路由模块

根据URL的域名选择合适的fetcher
"""

import re
from typing import Optional, Dict, List
from urllib.parse import urlparse


class DomainRouter:
    """域名路由器"""
    
    def __init__(self, domain_config: Dict[str, Dict]):
        """
        初始化域名路由器
        
        Args:
            domain_config: 域名配置，格式:
            {
                'wikipedia': {
                    'patterns': ['*.wikipedia.org', '...'],
                    'fetcher': 'wikipedia',
                    'requires_state': False
                },
                ...
            }
        """
        self.domain_config = domain_config
        self.compiled_patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict[str, List]:
        """编译所有域名模式"""
        compiled = {}
        
        for domain_name, config in self.domain_config.items():
            patterns = config.get('patterns', [])
            compiled[domain_name] = [self._pattern_to_regex(p) for p in patterns]
        
        return compiled
    
    @staticmethod
    def _pattern_to_regex(pattern: str) -> re.Pattern:
        """
        将通配符模式转换为正则表达式
        
        例: *.wikipedia.org -> 正则表达式
        """
        # 转义特殊字符
        pattern = re.escape(pattern)
        # 将转义后的*替换回正则的匹配
        pattern = pattern.replace(r'\*', '.*')
        return re.compile(f'^{pattern}$', re.IGNORECASE)
    
    def route(self, url: str) -> Optional[Dict]:
        """
        根据URL路由到对应的fetcher配置
        
        Args:
            url: 要爬取的URL
            
        Returns:
            匹配的配置字典，格式:
            {
                'domain': 'wikipedia',
                'fetcher': 'wikipedia',
                'patterns': ['*.wikipedia.org'],
                'requires_state': False
            }
            如果未匹配则返回None
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # 遍历所有domain配置
            for domain_name, config in self.domain_config.items():
                patterns = self.compiled_patterns.get(domain_name, [])
                
                # 检查是否匹配任何模式
                for pattern in patterns:
                    if pattern.match(domain):
                        return {
                            'domain': domain_name,
                            'fetcher': config.get('fetcher', 'requests'),
                            'patterns': config.get('patterns', []),
                            'requires_state': config.get('requires_state', False),
                            'requires_login': config.get('requires_login', False),
                        }
            
            # 默认返回requests fetcher
            return {
                'domain': 'unknown',
                'fetcher': 'requests',
                'patterns': [domain],
                'requires_state': False,
                'requires_login': False,
            }
        
        except Exception as e:
            print(f"Error routing URL {url}: {e}")
            return None
    
    def get_fetcher_type(self, url: str) -> str:
        """
        获取应该使用的fetcher类型
        
        Args:
            url: URL
            
        Returns:
            fetcher类型: 'wikipedia', 'playwright', 'requests'
        """
        route = self.route(url)
        if route:
            return route.get('fetcher', 'requests')
        return 'requests'
    
    def requires_state(self, url: str) -> bool:
        """检查该URL是否需要browser state"""
        route = self.route(url)
        if route:
            return route.get('requires_state', False)
        return False
    
    def requires_login(self, url: str) -> bool:
        """检查该URL是否需要登录"""
        route = self.route(url)
        if route:
            return route.get('requires_login', False)
        return False
    
    def get_domain_name(self, url: str) -> str:
        """获取URL匹配的domain配置名称"""
        route = self.route(url)
        if route:
            return route.get('domain', 'unknown')
        return 'unknown'
