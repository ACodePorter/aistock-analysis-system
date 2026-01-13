"""
Wikipedia fetcher

通过Wikimedia API获取Wikipedia页面内容
"""

import re
from typing import Optional, Dict, Any
from urllib.parse import quote
import asyncio

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    import requests
except ImportError:
    requests = None


class WikipediaFetcher:
    """Wikipedia内容获取器"""
    
    API_ENDPOINT = "https://{lang}.wikipedia.org/w/api.php"
    
    def __init__(self, timeout: int = 30, retries: int = 3):
        """
        初始化Wikipedia fetcher
        
        Args:
            timeout: 请求超时（秒）
            retries: 重试次数
        """
        self.timeout = timeout
        self.retries = retries
    
    def fetch_page_text(
        self,
        title: str,
        lang: str = "zh",
        get_full_page: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        获取Wikipedia页面的纯文本内容
        
        Args:
            title: Wikipedia页面标题
            lang: 语言代码 (默认: zh)
            get_full_page: 是否获取完整页面还是只摘要 (默认: False)
            
        Returns:
            {
                'title': '页面标题',
                'content': '纯文本内容',
                'url': '页面URL',
                'extract_length': 123,
                'language': 'zh'
            }
            如果获取失败返回None
        """
        if not requests:
            return self._fetch_page_text_async(title, lang, get_full_page)
        
        return self._fetch_page_text_sync(title, lang, get_full_page)
    
    def _fetch_page_text_sync(
        self,
        title: str,
        lang: str,
        get_full_page: bool
    ) -> Optional[Dict[str, Any]]:
        """同步方式获取页面内容"""
        
        api_url = self.API_ENDPOINT.format(lang=lang)
        
        params = {
            'action': 'query',
            'titles': title,
            'format': 'json',
            'prop': 'extracts|info|images',
            'inprop': 'url',
            'explaintext': True,
            'redirects': 1,
        }
        
        if not get_full_page:
            params['exlimit'] = 1  # 只获取摘要
            params['exintro'] = True
        else:
            params['explimit'] = 'max'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': f'{lang};q=0.9,en;q=0.8',
        }
        
        for attempt in range(self.retries):
            try:
                response = requests.get(
                    api_url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout
                )
                response.raise_for_status()
                
                data = response.json()
                
                if 'query' not in data or 'pages' not in data['query']:
                    return None
                
                pages = data['query']['pages']
                page_data = next(iter(pages.values()), None)
                
                if not page_data or 'extract' not in page_data:
                    return None
                
                return {
                    'title': page_data.get('title', title),
                    'content': page_data['extract'],
                    'url': page_data.get('fullurl', f'https://{lang}.wikipedia.org/wiki/{title}'),
                    'extract_length': len(page_data['extract']),
                    'language': lang,
                    'pageid': page_data.get('pageid'),
                }
            
            except Exception as e:
                if attempt == self.retries - 1:
                    print(f"Failed to fetch Wikipedia page '{title}': {e}")
                    return None
                
                # 指数退避重试
                import time
                wait_time = 2 ** attempt
                time.sleep(wait_time)
        
        return None
    
    def _fetch_page_text_async(
        self,
        title: str,
        lang: str,
        get_full_page: bool
    ) -> Optional[Dict[str, Any]]:
        """异步方式获取页面内容"""
        
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self._fetch_page_text_async_impl(title, lang, get_full_page)
        )
    
    async def _fetch_page_text_async_impl(
        self,
        title: str,
        lang: str,
        get_full_page: bool
    ) -> Optional[Dict[str, Any]]:
        """异步实现"""
        
        if not aiohttp:
            return None
        
        api_url = self.API_ENDPOINT.format(lang=lang)
        
        params = {
            'action': 'query',
            'titles': title,
            'format': 'json',
            'prop': 'extracts|info',
            'inprop': 'url',
            'explaintext': True,
            'redirects': 1,
        }
        
        if not get_full_page:
            params['exintro'] = True
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': f'{lang};q=0.9,en;q=0.8',
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    api_url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    data = await response.json()
                    
                    if 'query' not in data or 'pages' not in data['query']:
                        return None
                    
                    pages = data['query']['pages']
                    page_data = next(iter(pages.values()), None)
                    
                    if not page_data or 'extract' not in page_data:
                        return None
                    
                    return {
                        'title': page_data.get('title', title),
                        'content': page_data['extract'],
                        'url': page_data.get('fullurl', f'https://{lang}.wikipedia.org/wiki/{title}'),
                        'extract_length': len(page_data['extract']),
                        'language': lang,
                        'pageid': page_data.get('pageid'),
                    }
            
            except Exception as e:
                print(f"Failed to fetch Wikipedia page '{title}': {e}")
                return None
    
    @staticmethod
    def extract_title_from_url(url: str) -> Optional[str]:
        """
        从Wikipedia URL中提取页面标题
        
        Args:
            url: Wikipedia URL
            
        Returns:
            页面标题，如果解析失败返回None
        """
        # 支持的URL格式:
        # - https://zh.wikipedia.org/wiki/Title
        # - https://en.wikipedia.org/w/index.php?title=Title
        
        # 格式1: /wiki/Title
        match = re.search(r'/wiki/(.+?)(?:\?|#|$)', url)
        if match:
            return match.group(1)
        
        # 格式2: ?title=Title
        match = re.search(r'[?&]title=([^&]+)', url)
        if match:
            return match.group(1)
        
        return None
