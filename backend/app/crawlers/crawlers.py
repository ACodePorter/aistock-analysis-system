"""
多信源财经爬虫实现

支持的信源：
1. 东方财富 - 新闻、研报、公告
2. 新浪财经 - 新闻、快讯
3. 财联社 - 电报快讯
4. 巨潮资讯 - 官方公告
5. 同花顺 - 新闻、资讯
6. SearXNG - 通用搜索兜底

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
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from urllib.parse import urljoin, quote, urlencode
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class BaseCrawler:
    """爬虫基类"""
    
    # 通用请求头
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    }
    
    def __init__(self, timeout: int = 15, retries: int = 3):
        self.timeout = timeout
        self.session = self._create_session(retries)
    
    def _create_session(self, retries: int) -> requests.Session:
        """创建带重试的会话"""
        session = requests.Session()
        
        retry = Retry(
            total=retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update(self.DEFAULT_HEADERS)
        # 全局默认代理（用于大多数爬虫请求），可由环境变量 NEWS_HTTP_PROXY 指定
        default_proxy = os.getenv('NEWS_HTTP_PROXY') or None
        if default_proxy:
            session.proxies.update({'http': default_proxy, 'https': default_proxy})
        
        return session
    
    def _safe_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """安全的HTTP请求"""
        kwargs.setdefault('timeout', self.timeout)
        
        try:
            resp = self.session.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            logger.warning(f"[爬虫] 请求失败 {url}: {e}")
            return None
    
    def _extract_text(self, html: str, selector: str = None) -> str:
        """从HTML提取文本"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # 移除脚本和样式
            for script in soup(['script', 'style']):
                script.decompose()
            
            if selector:
                element = soup.select_one(selector)
                return element.get_text(strip=True) if element else ''
            
            return soup.get_text(strip=True)
        except Exception:
            return ''
    
    def _normalize_date(self, date_str: str) -> Optional[str]:
        """标准化日期格式"""
        if not date_str:
            return None
        
        patterns = [
            (r'(\d{4})-(\d{1,2})-(\d{1,2})', '%Y-%m-%d'),
            (r'(\d{4})/(\d{1,2})/(\d{1,2})', '%Y/%m/%d'),
            (r'(\d{4})年(\d{1,2})月(\d{1,2})日', '%Y年%m月%d日'),
            (r'(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})', None),  # 需要特殊处理
        ]
        
        for pattern, fmt in patterns:
            match = re.search(pattern, date_str)
            if match:
                try:
                    if fmt:
                        dt = datetime.strptime(match.group(), fmt)
                        return dt.strftime('%Y-%m-%d')
                except Exception:
                    pass
        
        return date_str[:10] if len(date_str) >= 10 else None


class EastMoneyCrawler(BaseCrawler):
    """东方财富爬虫
    
    支持：
    - 个股新闻（使用股吧和资讯列表API）
    - 行业新闻
    - 研究报告
    - 公司公告
    """
    
    BASE_URL = 'https://www.eastmoney.com'
    
    # API端点 - 使用更稳定的接口
    # 股吧个股新闻API
    GUBA_NEWS_API = 'https://guba.eastmoney.com/interface/GetData.aspx'
    # 资讯中心API
    NEWS_LIST_API = 'https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html'
    # 财经资讯搜索
    CAIJING_SEARCH_API = 'https://so.eastmoney.com/web/s'
    
    def crawl_stock_news(self, stock_code: str, stock_name: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """抓取个股新闻
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            limit: 返回数量
        
        Returns:
            新闻列表
        """
        results = []
        
        # 方法1: 尝试股吧个股新闻接口
        try:
            # 确定市场代码
            market = '1' if stock_code.startswith('6') else '0'  # 1=沪市, 0=深市
            
            params = {
                'param': f'secid={market}.{stock_code}',
                'path': 'newstocks/news',
                'apiver': 'v1',
            }
            
            resp = self._safe_request('get', self.GUBA_NEWS_API, params=params)
            
            if resp and resp.text:
                try:
                    # 尝试解析JSON
                    text = resp.text.strip()
                    if text.startswith('var'):
                        # 处理 var xxx = {...} 格式
                        text = text.split('=', 1)[1].strip().rstrip(';')
                    data = json.loads(text)
                    items = data.get('re', []) or data.get('data', []) or []
                    
                    for item in items[:limit]:
                        title = item.get('title', '') or item.get('Title', '')
                        url = item.get('url', '') or item.get('Url', '')
                        if not url and item.get('code'):
                            url = f"https://guba.eastmoney.com/news,{stock_code},{item.get('code')}.html"
                        
                        if title:
                            results.append({
                                'title': title,
                                'url': url,
                                'content': item.get('digest', '') or item.get('Content', ''),
                                'source': 'eastmoney',
                                'publish_time': item.get('post_publish_time', '') or item.get('ShowTime', ''),
                                'stock_code': stock_code,
                            })
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.debug(f"[东方财富] 股吧接口失败: {e}")
        
        # 方法2: 如果股吧接口没有结果，尝试HTML页面抓取
        if not results:
            try:
                from bs4 import BeautifulSoup
                
                # 访问股票资讯页面
                url = f"https://quote.eastmoney.com/{stock_code[:2].lower()}{stock_code}.html"
                resp = self._safe_request('get', url)
                
                if resp:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    # 尝试多种选择器
                    news_items = soup.select('.news_list li a, .newslist li a, .news-list a')
                    
                    for item in news_items[:limit]:
                        title = item.get_text(strip=True)
                        href = item.get('href', '')
                        
                        if title and href and len(title) > 5:
                            results.append({
                                'title': title,
                                'url': href if href.startswith('http') else f"https:{href}",
                                'content': '',
                                'source': 'eastmoney',
                                'stock_code': stock_code,
                            })
            except Exception as e:
                logger.debug(f"[东方财富] HTML抓取失败: {e}")
        
        # 方法3: 使用搜索页面（最后备选）
        if not results and stock_name:
            try:
                from bs4 import BeautifulSoup
                
                params = {'keyword': stock_name, 'type': 0}
                resp = self._safe_request('get', self.CAIJING_SEARCH_API, params=params)
                
                if resp:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    for item in soup.select('.result-list .item, .news-item')[:limit]:
                        title_elem = item.select_one('a.title, h3 a, .title a')
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                            href = title_elem.get('href', '')
                            
                            if title and href:
                                results.append({
                                    'title': title,
                                    'url': href,
                                    'content': '',
                                    'source': 'eastmoney',
                                    'stock_code': stock_code,
                                })
            except Exception as e:
                logger.debug(f"[东方财富] 搜索失败: {e}")
        
        if not results:
            logger.warning(f"[东方财富] 未获取到 {stock_code} 的新闻")
        
        return results
    
    def crawl_industry_news(self, industry: str, limit: int = 10) -> List[Dict[str, Any]]:
        """抓取行业新闻"""
        results = []
        
        try:
            from bs4 import BeautifulSoup
            
            # 使用搜索页面
            params = {'keyword': f'{industry}行业', 'type': 0}
            resp = self._safe_request('get', self.CAIJING_SEARCH_API, params=params)
            
            if resp:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                for item in soup.select('.result-list .item, .news-item, .list-item')[:limit]:
                    title_elem = item.select_one('a.title, h3 a, .title a')
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        href = title_elem.get('href', '')
                        
                        if title and href:
                            results.append({
                                'title': title,
                                'url': href,
                                'content': '',
                                'source': 'eastmoney',
                                'industry': industry,
                                'is_industry_news': True,
                            })
        except Exception as e:
            logger.warning(f"[东方财富] 行业新闻失败: {e}")
        
        if not results:
            logger.debug(f"[东方财富] 未获取到 {industry} 行业新闻")
        
        return results
    
    def crawl_research_report(self, stock_code: str, limit: int = 5) -> List[Dict[str, Any]]:
        """抓取研究报告"""
        results = []
        
        try:
            # 研报中心API
            api = 'https://data.eastmoney.com/report/info.aspx'
            params = {
                'code': stock_code,
                'type': 'company',
            }
            
            resp = self._safe_request('get', api, params=params)
            
            if resp:
                # 解析HTML页面
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                for item in soup.select('.report-list .item')[:limit]:
                    title_elem = item.select_one('.title a')
                    if title_elem:
                        results.append({
                            'title': title_elem.get_text(strip=True),
                            'url': urljoin(self.BASE_URL, title_elem.get('href', '')),
                            'source': 'eastmoney_research',
                            'stock_code': stock_code,
                            'is_research': True,
                        })
        except Exception as e:
            logger.warning(f"[东方财富] 研报失败: {e}")
        
        return results


class SinaFinanceCrawler(BaseCrawler):
    """新浪财经爬虫"""
    
    SEARCH_API = 'https://search.sina.com.cn/news'
    
    def crawl_stock_news(self, stock_code: str, stock_name: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """抓取个股新闻"""
        results = []
        
        try:
            search_query = stock_name or stock_code
            params = {
                'q': search_query,
                'c': 'news',
                'range': 'all',
                'num': limit,
            }
            
            resp = self._safe_request('get', self.SEARCH_API, params=params)
            
            if resp:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                for item in soup.select('.result .box-result')[:limit]:
                    title_elem = item.select_one('h2 a')
                    content_elem = item.select_one('.content')
                    time_elem = item.select_one('.fgray_time')
                    
                    if title_elem:
                        results.append({
                            'title': title_elem.get_text(strip=True),
                            'url': title_elem.get('href', ''),
                            'content': content_elem.get_text(strip=True) if content_elem else '',
                            'source': 'sina_finance',
                            'publish_time': time_elem.get_text(strip=True) if time_elem else '',
                            'stock_code': stock_code,
                        })
        except Exception as e:
            logger.warning(f"[新浪财经] 搜索失败: {e}")
        
        return results


class CLSCrawler(BaseCrawler):
    """财联社爬虫
    
    专业财经快讯 - 使用HTML页面抓取
    """
    
    BASE_URL = 'https://www.cls.cn'
    TELEGRAPH_PAGE = 'https://www.cls.cn/telegraph'
    SEARCH_PAGE = 'https://www.cls.cn/searchPage'
    
    def crawl_telegraph(self, keyword: str = '', limit: int = 20) -> List[Dict[str, Any]]:
        """抓取电报快讯"""
        results = []
        
        try:
            from bs4 import BeautifulSoup
            
            headers = {
                **self.DEFAULT_HEADERS,
                'Referer': 'https://www.cls.cn/',
            }
            
            if keyword:
                # 使用搜索页面
                resp = self._safe_request('get', f"{self.SEARCH_PAGE}?keyword={quote(keyword)}", headers=headers)
            else:
                # 获取电报页面
                resp = self._safe_request('get', self.TELEGRAPH_PAGE, headers=headers)
            
            if resp:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # 查找电报列表 - 尝试多种选择器
                items = soup.select('.telegraph-item, .telegraph-content-box, .content-box, article.item')
                
                if not items:
                    # 尝试其他选择器
                    items = soup.select('div[class*="telegraph"], div[class*="news-item"]')
                
                for item in items[:limit]:
                    # 提取标题/内容
                    content_elem = item.select_one('.telegraph-content, .content, p, .desc')
                    title_elem = item.select_one('.title, h3, h4') or content_elem
                    link_elem = item.select_one('a[href*="/detail/"]')
                    time_elem = item.select_one('.time, .date, span[class*="time"]')
                    
                    content = content_elem.get_text(strip=True) if content_elem else ''
                    title = title_elem.get_text(strip=True) if title_elem else content[:50]
                    
                    if title or content:
                        url = ''
                        if link_elem:
                            href = link_elem.get('href', '')
                            url = href if href.startswith('http') else f"{self.BASE_URL}{href}"
                        
                        results.append({
                            'title': title[:100] if title else content[:100],
                            'content': content,
                            'url': url,
                            'source': 'cls',
                            'publish_time': time_elem.get_text(strip=True) if time_elem else '',
                            'is_telegraph': True,
                        })
        except Exception as e:
            logger.warning(f"[财联社] 快讯失败: {e}")
        
        if not results:
            logger.debug("[财联社] 未获取到快讯数据")
        
        return results
    
    def crawl_stock_news(self, stock_code: str, stock_name: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """搜索个股相关快讯"""
        keyword = stock_name or stock_code
        results = self.crawl_telegraph(keyword, limit)
        
        # 标记股票代码
        for r in results:
            r['stock_code'] = stock_code
        
        return results


class CNInfoCrawler(BaseCrawler):
    """巨潮资讯爬虫
    
    官方信息披露平台
    """
    
    BASE_URL = 'http://www.cninfo.com.cn'
    ANNOUNCEMENT_API = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
    DISCLOSURE_PAGE = 'http://www.cninfo.com.cn/new/disclosure'
    
    def crawl_announcements(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """抓取公司公告"""
        results = []
        
        try:
            headers = {
                **self.DEFAULT_HEADERS,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': 'http://www.cninfo.com.cn/new/disclosure',
                'Origin': 'http://www.cninfo.com.cn',
            }
            
            # 构造股票代码（需要带市场前缀）
            # 深市: 000xxx, 002xxx, 300xxx; 沪市: 600xxx, 601xxx, 603xxx, 688xxx
            if stock_code.startswith(('0', '3')):
                plate = 'sz'
            else:
                plate = 'sh'
            
            data = {
                'stock': stock_code,
                'tabName': 'fulltext',
                'pageSize': limit,
                'pageNum': 1,
                'column': plate,
                'category': '',
                'plate': '',
                'seDate': '',
            }
            
            resp = self._safe_request('post', self.ANNOUNCEMENT_API, data=data, headers=headers)
            
            if resp:
                try:
                    result = resp.json()
                    items = result.get('announcements') or []
                    
                    for item in items[:limit]:
                        ann_id = item.get('announcementId', '')
                        ann_title = item.get('announcementTitle', '')
                        
                        if ann_title:
                            results.append({
                                'title': ann_title,
                                'url': f"http://www.cninfo.com.cn/new/disclosure/detail?announcementId={ann_id}&announcementTime={item.get('announcementTime', '')}" if ann_id else '',
                                'content': ann_title,  # 公告通常没有摘要
                                'source': 'cninfo',
                                'publish_time': item.get('announcementTime', ''),
                                'stock_code': stock_code,
                                'is_announcement': True,
                                'announcement_type': item.get('announcementTypeName', ''),
                            })
                except json.JSONDecodeError:
                    logger.debug(f"[巨潮] JSON解析失败")
        except Exception as e:
            logger.warning(f"[巨潮] 公告失败: {e}")
        
        # 如果API失败，尝试HTML页面
        if not results:
            try:
                from bs4 import BeautifulSoup
                
                # 访问公告列表页
                url = f"{self.DISCLOSURE_PAGE}?stock={stock_code}"
                resp = self._safe_request('get', url, headers={**self.DEFAULT_HEADERS, 'Referer': self.BASE_URL})
                
                if resp:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    # 查找公告列表
                    for item in soup.select('.el-table__row, .ant-table-row, tr.list-item')[:limit]:
                        title_elem = item.select_one('a[title], .title a, td a')
                        time_elem = item.select_one('.time, td:last-child')
                        
                        if title_elem:
                            title = title_elem.get('title', '') or title_elem.get_text(strip=True)
                            href = title_elem.get('href', '')
                            
                            if title:
                                results.append({
                                    'title': title,
                                    'url': href if href.startswith('http') else f"{self.BASE_URL}{href}",
                                    'content': title,
                                    'source': 'cninfo',
                                    'publish_time': time_elem.get_text(strip=True) if time_elem else '',
                                    'stock_code': stock_code,
                                    'is_announcement': True,
                                })
            except Exception as e:
                logger.debug(f"[巨潮] HTML抓取失败: {e}")
        
        if not results:
            logger.debug(f"[巨潮] 未获取到 {stock_code} 的公告")
        
        return results
        
        return results


class SearXNGCrawler(BaseCrawler):
    """SearXNG爬虫（兜底方案）"""
    
    def __init__(self, base_url: str = None, **kwargs):
        super().__init__(**kwargs)
        self.base_url = (base_url or os.getenv('SEARXNG_URL', 'http://localhost:10000')).rstrip('/')
    
    def crawl(self, query: str, task_type: str = 'news', limit: int = 10, **kwargs) -> List[Dict[str, Any]]:
        """通用搜索
        
        Args:
            query: 搜索关键词
            task_type: 任务类型
            limit: 返回数量
        
        Returns:
            搜索结果列表
        """
        results = []
        
        try:
            params = {
                'q': query,
                'format': 'json',
                'categories': 'news' if task_type == 'news' else 'general',
                'time_range': 'week',
                'language': 'zh-CN',
            }
            # Try rotating proxies from SEARXNG_PROXY_POOL if configured
            searx_proxies = os.getenv('SEARXNG_PROXY_POOL', '')
            proxies = None
            if searx_proxies:
                pool = [p.strip() for p in searx_proxies.split(',') if p.strip()]
                if pool:
                    # pick random proxy to distribute load
                    chosen = random.choice(pool)
                    proxies = {'http': chosen, 'https': chosen}

            resp = self._safe_request('get', f"{self.base_url}/search", params=params, proxies=proxies)
            
            if resp:
                data = resp.json()
                
                for item in data.get('results', [])[:limit]:
                    results.append({
                        'title': item.get('title', ''),
                        'url': item.get('url', ''),
                        'content': item.get('content', ''),
                        'source': 'searxng',
                        'publish_time': item.get('publishedDate', ''),
                        'search_query': query,
                    })
        except Exception as e:
            logger.warning(f"[SearXNG] 搜索失败: {e}")
        
        return results
    
    def crawl_stock_news(self, stock_code: str, stock_name: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """搜索个股新闻"""
        query = f'"{stock_name}" 股票' if stock_name else f'{stock_code} 股票'
        results = self.crawl(query, 'news', limit)
        
        # 添加股票代码标记
        for r in results:
            r['stock_code'] = stock_code
        
        return results


class TongHuaShunCrawler(BaseCrawler):
    """同花顺简易爬虫（不登录，仅抓取公开资讯页面）"""

    BASE_URL = 'https://www.10jqka.com.cn'
    NEWS_SEARCH = 'https://search.10jqka.com.cn/search.php'

    def crawl_stock_news(self, stock_code: str, stock_name: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            query = stock_name or stock_code
            params = {'q': query, 'type': 'news'}
            resp = self._safe_request('get', self.NEWS_SEARCH, params=params)
            if resp:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                items = soup.select('.result .item, .news-list li, .search-item')
                for item in items[:limit]:
                    a = item.select_one('a')
                    title = a.get_text(strip=True) if a else item.get_text(strip=True)
                    href = a.get('href', '') if a else ''
                    if title:
                        results.append({
                            'title': title,
                            'url': href if href.startswith('http') else urljoin(self.BASE_URL, href),
                            'content': '',
                            'source': 'tonghuashun',
                            'stock_code': stock_code,
                        })
        except Exception as e:
            logger.debug(f"[同花顺] 抓取失败: {e}")

        return results


class XueqiuCrawler(BaseCrawler):
    """雪球简易爬虫（社区/资讯抓取，避免登录）"""

    BASE_URL = 'https://xueqiu.com'
    SEARCH_API = 'https://xueqiu.com/query/v1/symbol/search.json'

    def crawl_stock_news(self, stock_code: str, stock_name: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            # 尝试使用公开查询接口（部分站点限制）
            params = {'keyword': stock_name or stock_code, 'count': limit}
            resp = self._safe_request('get', self.SEARCH_API, params=params)
            if resp:
                data = resp.json()
                for hit in data.get('list', [])[:limit]:
                    title = hit.get('title') or hit.get('description') or hit.get('text')
                    url = hit.get('source_url') or hit.get('url')
                    if title:
                        results.append({
                            'title': title,
                            'url': url if url and url.startswith('http') else '',
                            'content': hit.get('text', ''),
                            'source': 'xueqiu',
                            'stock_code': stock_code,
                        })
        except Exception as e:
            logger.debug(f"[雪球] 抓取失败: {e}")

        return results


# ===== 爬虫工厂 =====

_crawler_instances: Dict[str, BaseCrawler] = {}


def get_crawler(source: str) -> Optional[BaseCrawler]:
    """获取爬虫实例"""
    global _crawler_instances
    
    if source not in _crawler_instances:
        if source == 'eastmoney':
            _crawler_instances[source] = EastMoneyCrawler()
        elif source == 'sina_finance':
            _crawler_instances[source] = SinaFinanceCrawler()
        elif source == 'cls':
            _crawler_instances[source] = CLSCrawler()
        elif source == 'cninfo':
            _crawler_instances[source] = CNInfoCrawler()
        elif source == 'tonghuashun':
            _crawler_instances[source] = TongHuaShunCrawler()
        elif source == 'xueqiu':
            _crawler_instances[source] = XueqiuCrawler()
        elif source == 'searxng':
            _crawler_instances[source] = SearXNGCrawler()
        else:
            return None
    
    return _crawler_instances.get(source)


def crawl_stock_news_multi(stock_code: str, stock_name: str = '', limit_per_source: int = 5) -> List[Dict[str, Any]]:
    """从多个源抓取股票新闻
    
    优先使用高质量源，失败时自动降级
    """
    all_results = []
    seen_urls = set()
    
    # 按优先级排序的源列表
    sources = ['cls', 'eastmoney', 'sina_finance', 'tonghuashun', 'xueqiu', 'searxng']
    
    for source in sources:
        crawler = get_crawler(source)
        if not crawler:
            continue
        
        try:
            results = crawler.crawl_stock_news(stock_code, stock_name, limit_per_source)
            
            for r in results:
                url = r.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
        except Exception as e:
            logger.warning(f"[多源抓取] {source} 失败: {e}")
            continue
        
        # 如果已经有足够的结果，提前退出
        if len(all_results) >= limit_per_source * 2:
            break
    
    return all_results
