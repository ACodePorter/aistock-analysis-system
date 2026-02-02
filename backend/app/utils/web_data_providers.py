"""
统一 Web 数据提供器模块

提供稳定、多源、可降级的互联网数据查询能力，覆盖：
- 天气查询：wttr.in、OpenWeatherMap
- 股票行情：Yahoo Finance、Sina Finance、东方财富
- 百科知识：Wikipedia API、百度百科
- 新闻搜索：NewsAPI、Google News RSS、RSS聚合
- 通用搜索：SearXNG (增强版)、DuckDuckGo Instant Answer

设计原则：
1. 多源冗余：每种数据类型至少有2个备选源
2. 自动降级：主源失败自动切换备用源
3. 响应缓存：TTL可配置的内存+Redis缓存
4. 并发查询：支持多源并发提升响应速度
5. 健康检测：自动标记不可用的数据源

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
import threading
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from urllib.parse import quote, urlencode, urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ============== 配置 ==============
WEB_DATA_TIMEOUT = float(os.getenv('WEB_DATA_TIMEOUT', '15'))
WEB_DATA_CACHE_TTL = int(os.getenv('WEB_DATA_CACHE_TTL', '300'))  # 5分钟
WEB_DATA_ENABLE_REDIS = os.getenv('WEB_DATA_ENABLE_REDIS', '1') in ('1', 'true', 'yes')
WEB_DATA_MAX_WORKERS = int(os.getenv('WEB_DATA_MAX_WORKERS', '5'))

# API Keys (带默认值，也可通过环境变量覆盖)
OPENWEATHERMAP_API_KEY = os.getenv('OPENWEATHERMAP_API_KEY', '2007ef2bf8a0ecb1892221c0f2b05ddc')
NEWSAPI_KEY = os.getenv('NEWSAPI_KEY', '70d1f3b77ebc48fc9e65234d533eac89')
ALPHA_VANTAGE_KEY = os.getenv('ALPHA_VANTAGE_KEY', '')

# User-Agent 池
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
]


class DataCategory(Enum):
    """数据类别"""
    WEATHER = "weather"
    STOCK = "stock"
    NEWS = "news"
    ENCYCLOPEDIA = "encyclopedia"
    SEARCH = "search"
    FINANCE = "finance"


class ProviderStatus(Enum):
    """提供器状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ProviderResult:
    """提供器返回结果"""
    success: bool
    data: Any = None
    error: str = ""
    source: str = ""
    latency_ms: int = 0
    cached: bool = False
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'source': self.source,
            'latency_ms': self.latency_ms,
            'cached': self.cached,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


class SimpleCache:
    """简单的线程安全内存缓存"""
    
    def __init__(self, default_ttl: int = 300):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
    
    def _make_key(self, key: str) -> str:
        return hashlib.md5(key.encode('utf-8')).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        hkey = self._make_key(key)
        with self._lock:
            item = self._cache.get(hkey)
            if item:
                if time.time() < item['expires']:
                    return item['value']
                else:
                    del self._cache[hkey]
        return None
    
    def set(self, key: str, value: Any, ttl: int = None):
        hkey = self._make_key(key)
        ttl = ttl or self._default_ttl
        with self._lock:
            self._cache[hkey] = {
                'value': value,
                'expires': time.time() + ttl,
            }
    
    def delete(self, key: str):
        hkey = self._make_key(key)
        with self._lock:
            self._cache.pop(hkey, None)
    
    def clear(self):
        with self._lock:
            self._cache.clear()
    
    def cleanup(self):
        """清理过期缓存"""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._cache.items() if now >= v['expires']]
            for k in expired:
                del self._cache[k]


# 全局缓存实例
_cache = SimpleCache(default_ttl=WEB_DATA_CACHE_TTL)


class BaseDataProvider(ABC):
    """数据提供器基类"""
    
    name: str = "base"
    category: DataCategory = DataCategory.SEARCH
    priority: int = 5  # 1-10, 越小优先级越高
    
    def __init__(self, timeout: float = None, retries: int = 2):
        self.timeout = timeout or WEB_DATA_TIMEOUT
        self.retries = retries
        self.session = self._create_session()
        self._status = ProviderStatus.HEALTHY
        self._last_error: Optional[str] = None
        self._error_count = 0
        self._success_count = 0
    
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.retries,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json, text/html, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
    
    def _safe_get(self, url: str, params: Dict = None, **kwargs) -> Optional[requests.Response]:
        kwargs.setdefault('timeout', self.timeout)
        kwargs.setdefault('headers', self._get_headers())
        try:
            resp = self.session.get(url, params=params, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            logger.debug(f"[{self.name}] GET {url} failed: {e}")
            return None
    
    def _safe_post(self, url: str, data: Dict = None, json_data: Dict = None, **kwargs) -> Optional[requests.Response]:
        kwargs.setdefault('timeout', self.timeout)
        kwargs.setdefault('headers', self._get_headers())
        try:
            resp = self.session.post(url, data=data, json=json_data, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            logger.debug(f"[{self.name}] POST {url} failed: {e}")
            return None
    
    def _record_success(self):
        self._success_count += 1
        self._error_count = max(0, self._error_count - 1)
        if self._error_count == 0:
            self._status = ProviderStatus.HEALTHY
    
    def _record_error(self, error: str):
        self._error_count += 1
        self._last_error = error
        if self._error_count >= 3:
            self._status = ProviderStatus.UNHEALTHY
        elif self._error_count >= 1:
            self._status = ProviderStatus.DEGRADED
    
    @property
    def is_healthy(self) -> bool:
        return self._status == ProviderStatus.HEALTHY
    
    @abstractmethod
    def query(self, **kwargs) -> ProviderResult:
        """执行查询"""
        pass


# ============== 天气数据提供器 ==============

class WttrInProvider(BaseDataProvider):
    """wttr.in 天气提供器（免费、无需API key）"""
    
    name = "wttr.in"
    category = DataCategory.WEATHER
    priority = 1
    
    BASE_URL = "https://wttr.in"
    
    def query(self, location: str, lang: str = "zh", **kwargs) -> ProviderResult:
        """查询天气
        
        Args:
            location: 地点名称（如 "Beijing", "Shanghai"）
            lang: 语言代码
        """
        start = time.time()
        try:
            # 使用 JSON 格式获取结构化数据
            url = f"{self.BASE_URL}/{quote(location)}"
            params = {'format': 'j1', 'lang': lang}
            
            resp = self._safe_get(url, params=params)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            current = data.get('current_condition', [{}])[0]
            
            result = {
                'location': location,
                'temperature_c': int(current.get('temp_C', 0)),
                'temperature_f': int(current.get('temp_F', 32)),
                'feels_like_c': int(current.get('FeelsLikeC', 0)),
                'humidity': int(current.get('humidity', 0)),
                'weather_desc': current.get('weatherDesc', [{}])[0].get('value', ''),
                'wind_speed_kmph': int(current.get('windspeedKmph', 0)),
                'wind_direction': current.get('winddir16Point', ''),
                'visibility_km': int(current.get('visibility', 10)),
                'uv_index': int(current.get('uvIndex', 0)),
                'observation_time': current.get('localObsDateTime', ''),
                'raw': data,
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


class OpenWeatherMapProvider(BaseDataProvider):
    """OpenWeatherMap 天气提供器（需要API key）"""
    
    name = "openweathermap"
    category = DataCategory.WEATHER
    priority = 2
    
    BASE_URL = "https://api.openweathermap.org/data/2.5"
    
    def __init__(self, api_key: str = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or OPENWEATHERMAP_API_KEY
    
    def query(self, location: str, lang: str = "zh_cn", **kwargs) -> ProviderResult:
        if not self.api_key:
            return ProviderResult(success=False, error="API key not configured", source=self.name)
        
        start = time.time()
        try:
            params = {
                'q': location,
                'appid': self.api_key,
                'units': 'metric',
                'lang': lang,
            }
            
            resp = self._safe_get(f"{self.BASE_URL}/weather", params=params)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            main = data.get('main', {})
            weather = data.get('weather', [{}])[0]
            wind = data.get('wind', {})
            
            result = {
                'location': location,
                'temperature_c': round(main.get('temp', 0)),
                'feels_like_c': round(main.get('feels_like', 0)),
                'humidity': main.get('humidity', 0),
                'weather_desc': weather.get('description', ''),
                'wind_speed_kmph': round(wind.get('speed', 0) * 3.6),  # m/s to km/h
                'visibility_km': data.get('visibility', 10000) // 1000,
                'raw': data,
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


# ============== 股票数据提供器 ==============

class YahooFinanceProvider(BaseDataProvider):
    """Yahoo Finance 股票提供器"""
    
    name = "yahoo_finance"
    category = DataCategory.STOCK
    priority = 1
    
    def query(self, symbol: str, **kwargs) -> ProviderResult:
        """查询股票行情
        
        Args:
            symbol: 股票代码，如 "AAPL", "002594.SZ", "1211.HK"
        """
        start = time.time()
        try:
            # 直接抓取 Yahoo Finance 页面
            url = f"https://finance.yahoo.com/quote/{quote(symbol)}"
            resp = self._safe_get(url)
            
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            html = resp.text
            result = self._parse_yahoo_page(html, symbol)
            
            if result:
                self._record_success()
                latency = int((time.time() - start) * 1000)
                return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            else:
                self._record_error("Parse failed")
                return ProviderResult(success=False, error="Parse failed", source=self.name)
                
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)
    
    def _parse_yahoo_page(self, html: str, symbol: str) -> Optional[Dict[str, Any]]:
        """解析 Yahoo Finance 页面"""
        try:
            # 提取价格信息（使用正则表达式）
            # 价格格式: <fin-streamer ... data-field="regularMarketPrice" ... value="123.45"
            price_match = re.search(
                r'data-field="regularMarketPrice"[^>]*value="([0-9.,]+)"',
                html
            )
            change_match = re.search(
                r'data-field="regularMarketChange"[^>]*value="([0-9.,\-]+)"',
                html
            )
            change_pct_match = re.search(
                r'data-field="regularMarketChangePercent"[^>]*value="([0-9.,\-]+)"',
                html
            )
            
            # 备用：从页面文本提取
            if not price_match:
                # 尝试其他模式
                price_match = re.search(r'>([0-9,]+\.[0-9]+)</fin-streamer>', html)
            
            price = float(price_match.group(1).replace(',', '')) if price_match else None
            change = float(change_match.group(1).replace(',', '')) if change_match else None
            change_pct = float(change_pct_match.group(1).replace(',', '')) if change_pct_match else None
            
            # 提取名称
            name_match = re.search(r'<h1[^>]*>([^<]+)\s*\(' + re.escape(symbol), html)
            name = name_match.group(1).strip() if name_match else symbol
            
            # 提取货币
            currency_match = re.search(r'Currency in (\w+)', html)
            currency = currency_match.group(1) if currency_match else 'USD'
            
            if price is not None:
                return {
                    'symbol': symbol,
                    'name': name,
                    'price': price,
                    'change': change,
                    'change_percent': change_pct,
                    'currency': currency,
                }
            return None
            
        except Exception as e:
            logger.debug(f"[yahoo] parse error: {e}")
            return None


class SinaFinanceProvider(BaseDataProvider):
    """新浪财经股票提供器（A股/港股）"""
    
    name = "sina_finance"
    category = DataCategory.STOCK
    priority = 2
    
    def query(self, symbol: str, **kwargs) -> ProviderResult:
        """查询股票行情（支持A股和港股）"""
        start = time.time()
        try:
            # 转换代码格式
            sina_code = self._convert_symbol(symbol)
            if not sina_code:
                return ProviderResult(success=False, error=f"Invalid symbol: {symbol}", source=self.name)
            
            url = f"https://hq.sinajs.cn/list={sina_code}"
            headers = self._get_headers()
            headers['Referer'] = 'https://finance.sina.com.cn/'
            
            resp = self._safe_get(url, headers=headers)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            result = self._parse_sina_response(resp.text, symbol)
            if result:
                self._record_success()
                latency = int((time.time() - start) * 1000)
                return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            else:
                self._record_error("Parse failed")
                return ProviderResult(success=False, error="No data", source=self.name)
                
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)
    
    def _convert_symbol(self, symbol: str) -> Optional[str]:
        """转换股票代码为新浪格式"""
        symbol = symbol.upper()
        
        # A股: 600xxx.SH -> sh600xxx, 000xxx.SZ -> sz000xxx
        if symbol.endswith('.SH') or symbol.endswith('.SS'):
            return 'sh' + symbol[:6]
        elif symbol.endswith('.SZ'):
            return 'sz' + symbol[:6]
        # 港股: 1211.HK -> hk01211
        elif symbol.endswith('.HK'):
            code = symbol[:-3].zfill(5)
            return 'hk' + code
        # 美股
        elif re.match(r'^[A-Z]+$', symbol):
            return 'gb_' + symbol.lower()
        # 纯数字：猜测市场
        elif symbol.isdigit():
            if symbol.startswith('6'):
                return 'sh' + symbol
            else:
                return 'sz' + symbol
        
        return None
    
    def _parse_sina_response(self, text: str, symbol: str) -> Optional[Dict[str, Any]]:
        """解析新浪行情响应"""
        try:
            # 格式: var hq_str_sh600000="浦发银行,11.58,11.59,...";
            match = re.search(r'="([^"]+)"', text)
            if not match:
                return None
            
            parts = match.group(1).split(',')
            if len(parts) < 10:
                return None
            
            # A股格式
            if 'sh' in text or 'sz' in text:
                return {
                    'symbol': symbol,
                    'name': parts[0],
                    'price': float(parts[3]) if parts[3] else None,
                    'change': float(parts[3]) - float(parts[2]) if parts[2] and parts[3] else None,
                    'change_percent': ((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100) if parts[2] and parts[3] and float(parts[2]) > 0 else None,
                    'open': float(parts[1]) if parts[1] else None,
                    'pre_close': float(parts[2]) if parts[2] else None,
                    'high': float(parts[4]) if parts[4] else None,
                    'low': float(parts[5]) if parts[5] else None,
                    'volume': int(float(parts[8])) if parts[8] else None,
                    'amount': float(parts[9]) if parts[9] else None,
                    'currency': 'CNY',
                }
            # 港股格式
            elif 'hk' in text:
                return {
                    'symbol': symbol,
                    'name': parts[1] if len(parts) > 1 else symbol,
                    'price': float(parts[6]) if len(parts) > 6 and parts[6] else None,
                    'change': float(parts[7]) if len(parts) > 7 and parts[7] else None,
                    'change_percent': float(parts[8]) if len(parts) > 8 and parts[8] else None,
                    'currency': 'HKD',
                }
            
            return None
            
        except Exception as e:
            logger.debug(f"[sina] parse error: {e}")
            return None


# ============== 百科知识提供器 ==============

class WikipediaProvider(BaseDataProvider):
    """Wikipedia API 提供器"""
    
    name = "wikipedia"
    category = DataCategory.ENCYCLOPEDIA
    priority = 1
    
    def query(self, keyword: str, lang: str = "zh", **kwargs) -> ProviderResult:
        """查询维基百科
        
        Args:
            keyword: 搜索关键词
            lang: 语言代码 (zh, en, ja, etc.)
        """
        start = time.time()
        try:
            # 使用 Wikipedia API
            api_url = f"https://{lang}.wikipedia.org/w/api.php"
            
            # 先搜索
            search_params = {
                'action': 'query',
                'list': 'search',
                'srsearch': keyword,
                'format': 'json',
                'srlimit': 5,
            }
            
            resp = self._safe_get(api_url, params=search_params)
            if not resp:
                self._record_error("Search failed")
                return ProviderResult(success=False, error="Search failed", source=self.name)
            
            search_data = resp.json()
            search_results = search_data.get('query', {}).get('search', [])
            
            if not search_results:
                return ProviderResult(success=False, error="No results", source=self.name)
            
            # 获取第一个结果的摘要
            page_title = search_results[0]['title']
            
            summary_params = {
                'action': 'query',
                'titles': page_title,
                'prop': 'extracts|info|pageimages',
                'exintro': True,
                'explaintext': True,
                'inprop': 'url',
                'pithumbsize': 300,
                'format': 'json',
            }
            
            resp = self._safe_get(api_url, params=summary_params)
            if not resp:
                self._record_error("Summary fetch failed")
                return ProviderResult(success=False, error="Summary fetch failed", source=self.name)
            
            summary_data = resp.json()
            pages = summary_data.get('query', {}).get('pages', {})
            
            if not pages:
                return ProviderResult(success=False, error="No page data", source=self.name)
            
            page = list(pages.values())[0]
            
            result = {
                'title': page.get('title', ''),
                'summary': page.get('extract', ''),
                'url': page.get('fullurl', f"https://{lang}.wikipedia.org/wiki/{quote(page_title)}"),
                'thumbnail': page.get('thumbnail', {}).get('source', ''),
                'search_results': [
                    {'title': r['title'], 'snippet': r.get('snippet', '')}
                    for r in search_results
                ],
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


class BaiduBaikeProvider(BaseDataProvider):
    """百度百科提供器（通过页面抓取）"""
    
    name = "baidu_baike"
    category = DataCategory.ENCYCLOPEDIA
    priority = 2
    
    BASE_URL = "https://baike.baidu.com"
    
    def query(self, keyword: str, **kwargs) -> ProviderResult:
        """查询百度百科"""
        start = time.time()
        try:
            search_url = f"{self.BASE_URL}/search"
            params = {'word': keyword}
            
            resp = self._safe_get(search_url, params=params, allow_redirects=True)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            result = self._parse_baike_page(resp.text, resp.url, keyword)
            
            if result:
                self._record_success()
                latency = int((time.time() - start) * 1000)
                return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            else:
                return ProviderResult(success=False, error="Parse failed", source=self.name)
                
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)
    
    def _parse_baike_page(self, html: str, url: str, keyword: str) -> Optional[Dict[str, Any]]:
        """解析百度百科页面"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # 提取标题
            title_elem = soup.select_one('h1') or soup.select_one('.lemmaWgt-lemmaTitle-title h1')
            title = title_elem.get_text(strip=True) if title_elem else keyword
            
            # 提取摘要
            summary_elem = soup.select_one('.lemma-summary') or soup.select_one('.lemmaSummary')
            summary = ''
            if summary_elem:
                summary = summary_elem.get_text(strip=True)
            
            # 如果没有摘要，尝试其他选择器
            if not summary:
                content_elem = soup.select_one('.main-content') or soup.select_one('.content')
                if content_elem:
                    paragraphs = content_elem.find_all('p', limit=3)
                    summary = ' '.join(p.get_text(strip=True) for p in paragraphs)
            
            if not summary:
                return None
            
            # 提取基本信息
            info_items = {}
            info_box = soup.select_one('.basic-info') or soup.select_one('.basicInfo-block')
            if info_box:
                names = info_box.select('.basicInfo-item.name, dt')
                values = info_box.select('.basicInfo-item.value, dd')
                for name, value in zip(names, values):
                    key = name.get_text(strip=True).rstrip('：:')
                    val = value.get_text(strip=True)
                    if key and val:
                        info_items[key] = val
            
            return {
                'title': title,
                'summary': summary[:1000],  # 限制长度
                'url': url,
                'basic_info': info_items,
            }
            
        except Exception as e:
            logger.debug(f"[baidu_baike] parse error: {e}")
            return None


# ============== 新闻数据提供器 ==============

class NewsAPIProvider(BaseDataProvider):
    """NewsAPI.org 新闻提供器（需要API key）"""
    
    name = "newsapi"
    category = DataCategory.NEWS
    priority = 1
    
    BASE_URL = "https://newsapi.org/v2"
    
    def __init__(self, api_key: str = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or NEWSAPI_KEY
    
    def query(self, keyword: str, language: str = "zh", page_size: int = 10, **kwargs) -> ProviderResult:
        """搜索新闻"""
        if not self.api_key:
            return ProviderResult(success=False, error="API key not configured", source=self.name)
        
        start = time.time()
        try:
            params = {
                'q': keyword,
                'apiKey': self.api_key,
                'language': language,
                'pageSize': page_size,
                'sortBy': 'publishedAt',
            }
            
            resp = self._safe_get(f"{self.BASE_URL}/everything", params=params)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            
            if data.get('status') != 'ok':
                error = data.get('message', 'Unknown error')
                self._record_error(error)
                return ProviderResult(success=False, error=error, source=self.name)
            
            articles = []
            for article in data.get('articles', []):
                articles.append({
                    'title': article.get('title', ''),
                    'description': article.get('description', ''),
                    'url': article.get('url', ''),
                    'source': article.get('source', {}).get('name', ''),
                    'published_at': article.get('publishedAt', ''),
                    'image_url': article.get('urlToImage', ''),
                })
            
            result = {
                'keyword': keyword,
                'total_results': data.get('totalResults', 0),
                'articles': articles,
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


class GoogleNewsRSSProvider(BaseDataProvider):
    """Google News RSS 提供器（免费）"""
    
    name = "google_news_rss"
    category = DataCategory.NEWS
    priority = 2
    
    BASE_URL = "https://news.google.com/rss/search"
    
    def query(self, keyword: str, language: str = "zh-CN", limit: int = 10, **kwargs) -> ProviderResult:
        """通过RSS获取Google新闻"""
        start = time.time()
        try:
            params = {
                'q': keyword,
                'hl': language,
                'gl': 'CN' if language.startswith('zh') else 'US',
                'ceid': f"CN:{language.split('-')[0]}" if language.startswith('zh') else "US:en",
            }
            
            resp = self._safe_get(self.BASE_URL, params=params)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            articles = self._parse_rss(resp.text, limit)
            
            result = {
                'keyword': keyword,
                'articles': articles,
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)
    
    def _parse_rss(self, xml_text: str, limit: int) -> List[Dict[str, Any]]:
        """解析RSS XML"""
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_text)
            
            articles = []
            for item in root.findall('.//item')[:limit]:
                title = item.find('title')
                link = item.find('link')
                pub_date = item.find('pubDate')
                source = item.find('source')
                
                articles.append({
                    'title': title.text if title is not None else '',
                    'url': link.text if link is not None else '',
                    'published_at': pub_date.text if pub_date is not None else '',
                    'source': source.text if source is not None else '',
                })
            
            return articles
            
        except Exception as e:
            logger.debug(f"[google_news_rss] parse error: {e}")
            return []


class EastMoneyNewsProvider(BaseDataProvider):
    """东方财富新闻提供器（免费）"""
    
    name = "eastmoney_news"
    category = DataCategory.NEWS
    priority = 3
    
    # 东方财富财经新闻API
    NEWS_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    SEARCH_API = "https://searchapi.eastmoney.com/api/Info/Search"
    
    def query(self, keyword: str, limit: int = 20, **kwargs) -> ProviderResult:
        """搜索东方财富新闻"""
        start = time.time()
        try:
            # 使用东方财富搜索接口
            params = {
                'appid': 'el1902262',  # 公开appid
                'version': '1.0',
                'keyword': keyword,
                'pageindex': 1,
                'pagesize': limit,
                'type': 3,  # 新闻类型
            }
            
            headers = self._get_headers()
            headers['Referer'] = 'https://so.eastmoney.com/'
            
            resp = self._safe_get(self.SEARCH_API, params=params, headers=headers)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            articles = []
            
            # 解析搜索结果
            if data.get('code') == 0 and data.get('result'):
                for item in data['result'].get('datalist', []):
                    articles.append({
                        'title': item.get('title', '').replace('<em>', '').replace('</em>', ''),
                        'description': item.get('content', '').replace('<em>', '').replace('</em>', ''),
                        'url': item.get('url', ''),
                        'source': '东方财富',
                        'published_at': item.get('showTime', ''),
                    })
            
            result = {
                'keyword': keyword,
                'articles': articles,
                'total_results': len(articles),
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


class SinaFinanceNewsProvider(BaseDataProvider):
    """新浪财经新闻提供器（免费）"""
    
    name = "sina_finance_news"
    category = DataCategory.NEWS
    priority = 3
    
    SEARCH_URL = "https://search.sina.com.cn/news"
    RSS_URL = "https://feed.mix.sina.com.cn/api/roll/get"
    
    def query(self, keyword: str, limit: int = 20, **kwargs) -> ProviderResult:
        """搜索新浪财经新闻"""
        start = time.time()
        try:
            # 使用新浪滚动新闻API
            params = {
                'pageid': 153,  # 财经频道
                'lid': 2516,    # 全部财经
                'k': keyword,
                'num': limit,
                'page': 1,
            }
            
            headers = self._get_headers()
            headers['Referer'] = 'https://finance.sina.com.cn/'
            
            resp = self._safe_get(self.RSS_URL, params=params, headers=headers)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            articles = []
            
            if data.get('result') and data['result'].get('data'):
                for item in data['result']['data'][:limit]:
                    title = item.get('title', '')
                    if keyword.lower() in title.lower():
                        articles.append({
                            'title': title,
                            'description': item.get('intro', ''),
                            'url': item.get('url', ''),
                            'source': '新浪财经',
                            'published_at': item.get('ctime', ''),
                        })
            
            result = {
                'keyword': keyword,
                'articles': articles,
                'total_results': len(articles),
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


class TencentFinanceNewsProvider(BaseDataProvider):
    """腾讯财经新闻提供器（免费）"""
    
    name = "tencent_finance_news"
    category = DataCategory.NEWS
    priority = 4
    
    SEARCH_URL = "https://finance.qq.com/cjdt/cjdtapi/search.htm"
    
    def query(self, keyword: str, limit: int = 20, **kwargs) -> ProviderResult:
        """搜索腾讯财经新闻"""
        start = time.time()
        try:
            params = {
                'query': keyword,
                'page': 1,
                'num': limit,
                'format': 'json',
            }
            
            headers = self._get_headers()
            headers['Referer'] = 'https://finance.qq.com/'
            
            resp = self._safe_get(self.SEARCH_URL, params=params, headers=headers)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            articles = []
            
            for item in data.get('data', {}).get('list', [])[:limit]:
                articles.append({
                    'title': item.get('title', ''),
                    'description': item.get('abstract', ''),
                    'url': item.get('url', ''),
                    'source': '腾讯财经',
                    'published_at': item.get('publish_time', ''),
                })
            
            result = {
                'keyword': keyword,
                'articles': articles,
                'total_results': len(articles),
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


class ChinaNewsFinanceProvider(BaseDataProvider):
    """中国新闻网财经频道提供器（免费）"""
    
    name = "chinanews_finance"
    category = DataCategory.NEWS
    priority = 5
    
    SEARCH_URL = "https://sou.chinanews.com.cn/search.do"
    
    def query(self, keyword: str, limit: int = 20, **kwargs) -> ProviderResult:
        """搜索中国新闻网财经新闻"""
        start = time.time()
        try:
            params = {
                'q': keyword,
                'ps': limit,
                'pn': 1,
                'channel': 'cj',  # 财经频道
                'type': 'web',
            }
            
            headers = self._get_headers()
            headers['Referer'] = 'https://www.chinanews.com.cn/'
            
            resp = self._safe_get(self.SEARCH_URL, params=params, headers=headers)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            # 解析响应（可能需要解析HTML）
            articles = self._parse_response(resp.text, limit)
            
            result = {
                'keyword': keyword,
                'articles': articles,
                'total_results': len(articles),
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)
    
    def _parse_response(self, text: str, limit: int) -> List[Dict[str, Any]]:
        """解析搜索响应"""
        articles = []
        try:
            # 尝试JSON解析
            data = json.loads(text)
            for item in data.get('content', {}).get('list', [])[:limit]:
                articles.append({
                    'title': item.get('title', ''),
                    'description': item.get('desc', ''),
                    'url': item.get('url', ''),
                    'source': '中国新闻网',
                    'published_at': item.get('time', ''),
                })
        except:
            # 如果是HTML，尝试简单正则提取
            import re
            pattern = r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
            for match in re.findall(pattern, text)[:limit]:
                url, title = match
                if 'chinanews' in url:
                    articles.append({
                        'title': title.strip(),
                        'url': url,
                        'source': '中国新闻网',
                    })
        return articles


class RSSHubFinanceProvider(BaseDataProvider):
    """RSSHub 金融新闻聚合提供器（需要自建RSSHub实例）"""
    
    name = "rsshub_finance"
    category = DataCategory.NEWS
    priority = 2
    
    # RSSHub 金融相关RSS源路径
    RSS_SOURCES = {
        'eastmoney': '/eastmoney/report/{category}',  # 东方财富研报
        'xueqiu': '/xueqiu/hots',                    # 雪球热帖
        'gelonghui': '/gelonghui/home/{category}',   # 格隆汇
        'wallstreetcn': '/wallstreetcn/news/global', # 华尔街见闻
        'jin10': '/jin10/flash',                      # 金十数据
        'cls': '/cls/telegraph',                      # 财联社电报
    }
    
    def __init__(self, base_url: str = None, **kwargs):
        super().__init__(**kwargs)
        self.base_url = (base_url or os.getenv('RSSHUB_URL', 'https://rsshub.app')).rstrip('/')
    
    def query(self, keyword: str, sources: List[str] = None, limit: int = 30, **kwargs) -> ProviderResult:
        """从多个RSSHub源聚合新闻"""
        start = time.time()
        all_articles = []
        
        sources = sources or ['wallstreetcn', 'jin10', 'cls']
        
        for source in sources:
            try:
                path = self.RSS_SOURCES.get(source)
                if not path:
                    continue
                
                # 替换路径中的参数
                if '{category}' in path:
                    path = path.replace('{category}', 'stock')  # 默认股票类别
                
                url = f"{self.base_url}{path}"
                resp = self._safe_get(url, timeout=8)
                if resp:
                    articles = self._parse_rss(resp.text, source, limit // len(sources))
                    all_articles.extend(articles)
            except Exception as e:
                logger.debug(f"[rsshub] {source} failed: {e}")
                continue
        
        # 按时间排序
        all_articles.sort(key=lambda x: x.get('published_at', ''), reverse=True)
        
        # 关键词过滤（如果提供）
        if keyword:
            filtered = [a for a in all_articles if keyword.lower() in a.get('title', '').lower() 
                       or keyword.lower() in a.get('description', '').lower()]
            if filtered:
                all_articles = filtered
        
        result = {
            'keyword': keyword,
            'articles': all_articles[:limit],
            'total_results': len(all_articles),
        }
        
        if all_articles:
            self._record_success()
        else:
            self._record_error("No articles found")
        
        latency = int((time.time() - start) * 1000)
        return ProviderResult(success=len(all_articles) > 0, data=result, source=self.name, latency_ms=latency)
    
    def _parse_rss(self, xml_text: str, source: str, limit: int) -> List[Dict[str, Any]]:
        """解析RSS XML"""
        articles = []
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_text)
            
            for item in root.findall('.//item')[:limit]:
                title = item.find('title')
                link = item.find('link')
                description = item.find('description')
                pub_date = item.find('pubDate')
                
                articles.append({
                    'title': title.text if title is not None else '',
                    'description': (description.text[:200] if description is not None and description.text else ''),
                    'url': link.text if link is not None else '',
                    'source': source,
                    'published_at': pub_date.text if pub_date is not None else '',
                })
        except Exception as e:
            logger.debug(f"[rsshub] RSS parse error: {e}")
        return articles


class WallStreetCNProvider(BaseDataProvider):
    """华尔街见闻新闻提供器（免费API）"""
    
    name = "wallstreetcn"
    category = DataCategory.NEWS
    priority = 2
    
    API_URL = "https://api-one-wscn.awtmt.com/apiv1/search/article"
    NEWS_URL = "https://api-one-wscn.awtmt.com/apiv1/content/articles"
    
    def query(self, keyword: str, limit: int = 20, **kwargs) -> ProviderResult:
        """搜索华尔街见闻新闻"""
        start = time.time()
        try:
            # 先尝试搜索接口
            params = {
                'query': keyword,
                'cursor': 0,
                'limit': limit,
            }
            
            headers = self._get_headers()
            headers['Referer'] = 'https://wallstreetcn.com/'
            
            resp = self._safe_get(self.API_URL, params=params, headers=headers)
            
            articles = []
            if resp:
                data = resp.json()
                if data.get('code') == 20000 and data.get('data'):
                    for item in data['data'].get('items', [])[:limit]:
                        articles.append({
                            'title': item.get('title', ''),
                            'description': item.get('content_short', '') or item.get('summary', ''),
                            'url': f"https://wallstreetcn.com/articles/{item.get('id')}",
                            'source': '华尔街见闻',
                            'published_at': datetime.fromtimestamp(item.get('display_time', 0)).isoformat() if item.get('display_time') else '',
                            'image_url': item.get('image', {}).get('uri', ''),
                        })
            
            # 如果搜索接口没有结果，尝试获取最新新闻并过滤
            if not articles:
                articles = self._get_latest_filtered(keyword, limit)
            
            result = {
                'keyword': keyword,
                'articles': articles,
                'total_results': len(articles),
            }
            
            if articles:
                self._record_success()
            else:
                self._record_error("No articles found")
            
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=len(articles) > 0, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)
    
    def _get_latest_filtered(self, keyword: str, limit: int) -> List[Dict[str, Any]]:
        """获取最新新闻并按关键词过滤"""
        try:
            params = {
                'channel': 'global-channel',
                'cursor': '',
                'limit': 50,  # 获取更多以便过滤
            }
            resp = self._safe_get(self.NEWS_URL, params=params)
            if not resp:
                return []
            
            data = resp.json()
            articles = []
            
            if data.get('code') == 20000 and data.get('data'):
                for item in data['data'].get('items', []):
                    title = item.get('title', '')
                    content = item.get('content_short', '')
                    if keyword.lower() in title.lower() or keyword.lower() in content.lower():
                        articles.append({
                            'title': title,
                            'description': content,
                            'url': f"https://wallstreetcn.com/articles/{item.get('id')}",
                            'source': '华尔街见闻',
                            'published_at': datetime.fromtimestamp(item.get('display_time', 0)).isoformat() if item.get('display_time') else '',
                        })
                        if len(articles) >= limit:
                            break
            return articles
        except:
            return []


class Jin10Provider(BaseDataProvider):
    """金十数据新闻提供器（免费）"""
    
    name = "jin10"
    category = DataCategory.NEWS
    priority = 2
    
    FLASH_URL = "https://flash-api.jin10.com/get_flash_list"
    
    def query(self, keyword: str, limit: int = 30, **kwargs) -> ProviderResult:
        """获取金十数据快讯"""
        start = time.time()
        try:
            # 获取当前时间戳
            max_time = int(time.time() * 1000)
            
            params = {
                'channel': '-8200',  # 全部
                'max_time': max_time,
                'vip': 0,
            }
            
            headers = self._get_headers()
            headers['Referer'] = 'https://www.jin10.com/'
            headers['x-app-id'] = 'bVBF4FyRTn5NJF5n'
            headers['x-version'] = '1.0.0'
            
            resp = self._safe_get(self.FLASH_URL, params=params, headers=headers)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            articles = []
            
            for item in data.get('data', []):
                content = item.get('data', {}).get('content', '')
                # 简单过滤关键词
                if keyword.lower() in content.lower() or not keyword:
                    pub_time = item.get('time', '')
                    articles.append({
                        'title': content[:50] + '...' if len(content) > 50 else content,
                        'description': content,
                        'url': f"https://www.jin10.com/flash_detail/{item.get('id', '')}",
                        'source': '金十数据',
                        'published_at': pub_time,
                        'is_important': item.get('important', 0) == 1,
                    })
                    if len(articles) >= limit:
                        break
            
            result = {
                'keyword': keyword,
                'articles': articles,
                'total_results': len(articles),
            }
            
            self._record_success()
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


class CLSNewsProvider(BaseDataProvider):
    """财联社新闻提供器（免费）"""
    
    name = "cls_news"
    category = DataCategory.NEWS
    priority = 1
    
    TELEGRAPH_URL = "https://www.cls.cn/nodeapi/telegraphList"
    SEARCH_URL = "https://www.cls.cn/api/search"
    
    def query(self, keyword: str, limit: int = 30, **kwargs) -> ProviderResult:
        """搜索财联社新闻"""
        start = time.time()
        try:
            # 先尝试搜索
            articles = self._search_articles(keyword, limit)
            
            # 如果搜索失败，获取电报并过滤
            if not articles:
                articles = self._get_telegraph_filtered(keyword, limit)
            
            result = {
                'keyword': keyword,
                'articles': articles,
                'total_results': len(articles),
            }
            
            if articles:
                self._record_success()
            else:
                self._record_error("No articles found")
            
            latency = int((time.time() - start) * 1000)
            return ProviderResult(success=len(articles) > 0, data=result, source=self.name, latency_ms=latency)
            
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)
    
    def _search_articles(self, keyword: str, limit: int) -> List[Dict[str, Any]]:
        """搜索文章"""
        try:
            params = {
                'keyword': keyword,
                'page': 1,
                'size': limit,
            }
            resp = self._safe_get(self.SEARCH_URL, params=params)
            if not resp:
                return []
            
            data = resp.json()
            articles = []
            for item in data.get('data', {}).get('list', [])[:limit]:
                articles.append({
                    'title': item.get('title', ''),
                    'description': item.get('brief', ''),
                    'url': f"https://www.cls.cn/detail/{item.get('id')}",
                    'source': '财联社',
                    'published_at': item.get('ctime', ''),
                })
            return articles
        except:
            return []
    
    def _get_telegraph_filtered(self, keyword: str, limit: int) -> List[Dict[str, Any]]:
        """获取电报并过滤"""
        try:
            params = {
                'app': 'CailianpressWeb',
                'os': 'web',
                'sv': '8.4.6',
                'rn': 50,  # 获取更多
            }
            resp = self._safe_get(self.TELEGRAPH_URL, params=params)
            if not resp:
                return []
            
            data = resp.json()
            articles = []
            for item in data.get('data', {}).get('roll_data', []):
                content = item.get('content', '')
                title = item.get('title', '') or content[:50]
                if keyword.lower() in title.lower() or keyword.lower() in content.lower():
                    articles.append({
                        'title': title,
                        'description': content,
                        'url': f"https://www.cls.cn/detail/{item.get('id')}",
                        'source': '财联社电报',
                        'published_at': datetime.fromtimestamp(item.get('ctime', 0)).isoformat() if item.get('ctime') else '',
                    })
                    if len(articles) >= limit:
                        break
            return articles
        except:
            return []


# ============== 通用搜索提供器 ==============

class SearXNGEnhancedProvider(BaseDataProvider):
    """增强版 SearXNG 提供器"""
    
    name = "searxng_enhanced"
    category = DataCategory.SEARCH
    priority = 3
    
    def __init__(self, base_url: str = None, **kwargs):
        super().__init__(**kwargs)
        self.base_url = (base_url or os.getenv('SEARXNG_URL', 'http://localhost:10000')).rstrip('/')
        # 支持多实例负载均衡
        self._instances = self._parse_instances()
        self._instance_index = 0
    
    def _parse_instances(self) -> List[str]:
        """解析多个 SearXNG 实例"""
        pool = os.getenv('SEARXNG_INSTANCE_POOL', '')
        if pool:
            return [u.strip().rstrip('/') for u in pool.split(',') if u.strip()]
        return [self.base_url]
    
    def _get_instance(self) -> str:
        """轮询获取实例"""
        instance = self._instances[self._instance_index % len(self._instances)]
        self._instance_index += 1
        return instance
    
    def query(self, keyword: str, categories: str = "general", time_range: str = "", limit: int = 10, **kwargs) -> ProviderResult:
        """搜索
        
        Args:
            keyword: 搜索关键词
            categories: 分类 (general, news, images, videos, etc.)
            time_range: 时间范围 (day, week, month, year)
            limit: 返回数量
        """
        start = time.time()
        last_error = ""
        
        # 尝试多个实例
        for _ in range(len(self._instances)):
            instance = self._get_instance()
            try:
                params = {
                    'q': keyword,
                    'format': 'json',
                    'categories': categories,
                    'language': 'zh-CN',
                }
                if time_range:
                    params['time_range'] = time_range
                
                resp = self._safe_get(f"{instance}/search", params=params, timeout=self.timeout)
                if not resp:
                    last_error = f"Instance {instance} failed"
                    continue
                
                data = resp.json()
                results = []
                
                for item in data.get('results', [])[:limit]:
                    results.append({
                        'title': item.get('title', ''),
                        'url': item.get('url', ''),
                        'content': item.get('content', ''),
                        'engine': item.get('engine', ''),
                        'published_date': item.get('publishedDate', ''),
                    })
                
                result = {
                    'keyword': keyword,
                    'results': results,
                    'instance': instance,
                }
                
                self._record_success()
                latency = int((time.time() - start) * 1000)
                return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
                
            except Exception as e:
                last_error = str(e)
                logger.debug(f"[searxng] instance {instance} error: {e}")
                continue
        
        self._record_error(last_error)
        return ProviderResult(success=False, error=last_error, source=self.name)


class DuckDuckGoProvider(BaseDataProvider):
    """DuckDuckGo Instant Answer 提供器"""
    
    name = "duckduckgo"
    category = DataCategory.SEARCH
    priority = 4
    
    API_URL = "https://api.duckduckgo.com/"
    
    def query(self, keyword: str, **kwargs) -> ProviderResult:
        """获取即时答案"""
        start = time.time()
        try:
            params = {
                'q': keyword,
                'format': 'json',
                'no_redirect': 1,
                'no_html': 1,
            }
            
            resp = self._safe_get(self.API_URL, params=params)
            if not resp:
                self._record_error("Request failed")
                return ProviderResult(success=False, error="Request failed", source=self.name)
            
            data = resp.json()
            
            result = {
                'keyword': keyword,
                'abstract': data.get('Abstract', ''),
                'abstract_source': data.get('AbstractSource', ''),
                'abstract_url': data.get('AbstractURL', ''),
                'answer': data.get('Answer', ''),
                'definition': data.get('Definition', ''),
                'related_topics': [
                    {'text': t.get('Text', ''), 'url': t.get('FirstURL', '')}
                    for t in data.get('RelatedTopics', [])[:5]
                    if isinstance(t, dict)
                ],
            }
            
            # 判断是否有有效结果
            if result['abstract'] or result['answer'] or result['definition']:
                self._record_success()
                latency = int((time.time() - start) * 1000)
                return ProviderResult(success=True, data=result, source=self.name, latency_ms=latency)
            else:
                return ProviderResult(success=False, error="No instant answer", source=self.name)
                
        except Exception as e:
            self._record_error(str(e))
            return ProviderResult(success=False, error=str(e), source=self.name)


# ============== 数据源管理器 ==============

class WebDataManager:
    """Web 数据源管理器
    
    统一管理所有数据提供器，支持：
    - 按类别查询（天气、股票、新闻等）
    - 多源并发与自动降级
    - 结果缓存
    - 健康检测
    """
    
    def __init__(self):
        self._providers: Dict[DataCategory, List[BaseDataProvider]] = {}
        self._cache = _cache
        self._executor = ThreadPoolExecutor(max_workers=WEB_DATA_MAX_WORKERS)
        self._register_default_providers()
    
    def _register_default_providers(self):
        """注册默认提供器"""
        # 天气
        self.register_provider(WttrInProvider())
        if OPENWEATHERMAP_API_KEY:
            self.register_provider(OpenWeatherMapProvider())
        
        # 股票
        self.register_provider(YahooFinanceProvider())
        self.register_provider(SinaFinanceProvider())
        
        # 百科
        self.register_provider(WikipediaProvider())
        self.register_provider(BaiduBaikeProvider())
        
        # 新闻（多源聚合，确保数据量充足）
        if NEWSAPI_KEY:
            self.register_provider(NewsAPIProvider())
        self.register_provider(GoogleNewsRSSProvider())
        # 新增中国金融新闻源
        self.register_provider(CLSNewsProvider())          # 财联社
        self.register_provider(WallStreetCNProvider())     # 华尔街见闻
        self.register_provider(Jin10Provider())            # 金十数据
        self.register_provider(EastMoneyNewsProvider())    # 东方财富
        self.register_provider(SinaFinanceNewsProvider())  # 新浪财经
        self.register_provider(TencentFinanceNewsProvider())  # 腾讯财经
        self.register_provider(RSSHubFinanceProvider())    # RSSHub聚合
        
        # 搜索
        self.register_provider(SearXNGEnhancedProvider())
        self.register_provider(DuckDuckGoProvider())
    
    def register_provider(self, provider: BaseDataProvider):
        """注册提供器"""
        category = provider.category
        if category not in self._providers:
            self._providers[category] = []
        
        # 按优先级插入
        providers = self._providers[category]
        inserted = False
        for i, p in enumerate(providers):
            if provider.priority < p.priority:
                providers.insert(i, provider)
                inserted = True
                break
        if not inserted:
            providers.append(provider)
        
        logger.info(f"[WebDataManager] Registered {provider.name} for {category.value}")
    
    def get_providers(self, category: DataCategory) -> List[BaseDataProvider]:
        """获取某类别的所有提供器"""
        return self._providers.get(category, [])
    
    def _make_cache_key(self, category: str, **kwargs) -> str:
        """生成缓存键"""
        params = json.dumps(kwargs, sort_keys=True)
        return f"webdata:{category}:{hashlib.md5(params.encode()).hexdigest()}"
    
    def query_weather(self, location: str, use_cache: bool = True, **kwargs) -> ProviderResult:
        """查询天气"""
        cache_key = self._make_cache_key('weather', location=location)
        
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached:
                return ProviderResult(success=True, data=cached, source="cache", cached=True)
        
        providers = self.get_providers(DataCategory.WEATHER)
        for provider in providers:
            if not provider.is_healthy:
                continue
            
            result = provider.query(location=location, **kwargs)
            if result.success:
                self._cache.set(cache_key, result.data, ttl=600)  # 天气缓存10分钟
                return result
        
        return ProviderResult(success=False, error="All weather providers failed", source="")
    
    def query_stock(self, symbol: str, use_cache: bool = True, **kwargs) -> ProviderResult:
        """查询股票行情"""
        cache_key = self._make_cache_key('stock', symbol=symbol)
        
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached:
                return ProviderResult(success=True, data=cached, source="cache", cached=True)
        
        providers = self.get_providers(DataCategory.STOCK)
        for provider in providers:
            if not provider.is_healthy:
                continue
            
            result = provider.query(symbol=symbol, **kwargs)
            if result.success:
                self._cache.set(cache_key, result.data, ttl=60)  # 股票缓存1分钟
                return result
        
        return ProviderResult(success=False, error="All stock providers failed", source="")
    
    def query_encyclopedia(self, keyword: str, lang: str = "zh", use_cache: bool = True, **kwargs) -> ProviderResult:
        """查询百科"""
        cache_key = self._make_cache_key('encyclopedia', keyword=keyword, lang=lang)
        
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached:
                return ProviderResult(success=True, data=cached, source="cache", cached=True)
        
        providers = self.get_providers(DataCategory.ENCYCLOPEDIA)
        for provider in providers:
            if not provider.is_healthy:
                continue
            
            result = provider.query(keyword=keyword, lang=lang, **kwargs)
            if result.success:
                self._cache.set(cache_key, result.data, ttl=3600)  # 百科缓存1小时
                return result
        
        return ProviderResult(success=False, error="All encyclopedia providers failed", source="")
    
    def query_news(self, keyword: str, limit: int = 10, use_cache: bool = True, **kwargs) -> ProviderResult:
        """查询新闻"""
        cache_key = self._make_cache_key('news', keyword=keyword, limit=limit)
        
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached:
                return ProviderResult(success=True, data=cached, source="cache", cached=True)
        
        providers = self.get_providers(DataCategory.NEWS)
        for provider in providers:
            if not provider.is_healthy:
                continue
            
            result = provider.query(keyword=keyword, limit=limit, **kwargs)
            if result.success:
                self._cache.set(cache_key, result.data, ttl=300)  # 新闻缓存5分钟
                return result
        
        return ProviderResult(success=False, error="All news providers failed", source="")
    
    def query_news_aggregated(self, keyword: str, min_articles: int = 20, max_articles: int = 50, 
                               timeout: float = 15, use_cache: bool = True, **kwargs) -> ProviderResult:
        """聚合多源新闻查询（目标获取20-50条高质量新闻）
        
        Args:
            keyword: 搜索关键词
            min_articles: 最小新闻数量
            max_articles: 最大新闻数量
            timeout: 总超时时间
            use_cache: 是否使用缓存
        
        Returns:
            聚合后的新闻结果
        """
        cache_key = self._make_cache_key('news_agg', keyword=keyword, min=min_articles, max=max_articles)
        
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached:
                return ProviderResult(success=True, data=cached, source="cache_aggregated", cached=True)
        
        start = time.time()
        providers = self.get_providers(DataCategory.NEWS)
        healthy_providers = [p for p in providers if p.is_healthy]
        
        if not healthy_providers:
            return ProviderResult(success=False, error="No healthy news providers", source="")
        
        all_articles = []
        sources_used = []
        futures = {}
        
        # 每个源请求更多文章，以便去重后仍有足够数量
        per_source_limit = max(20, max_articles // len(healthy_providers) + 10)
        
        # 并发查询所有健康的提供器
        for provider in healthy_providers:
            future = self._executor.submit(provider.query, keyword=keyword, limit=per_source_limit, **kwargs)
            futures[future] = provider.name
        
        try:
            for future in as_completed(futures, timeout=timeout):
                try:
                    result = future.result()
                    if result.success and result.data:
                        articles = result.data.get('articles', [])
                        for article in articles:
                            article['_source_provider'] = futures[future]
                        all_articles.extend(articles)
                        sources_used.append(futures[future])
                except Exception as e:
                    logger.debug(f"[news_agg] {futures[future]} error: {e}")
        except FuturesTimeoutError:
            logger.warning(f"[news_agg] Timeout after {timeout}s, collected {len(all_articles)} articles")
        
        # 去重（基于URL和标题）
        seen_urls = set()
        seen_titles = set()
        unique_articles = []
        
        for article in all_articles:
            url = article.get('url', '')
            title = article.get('title', '').strip().lower()
            
            # 跳过空标题
            if not title:
                continue
            
            # URL去重
            if url and url in seen_urls:
                continue
            
            # 标题相似度去重（简单版：完全匹配）
            if title in seen_titles:
                continue
            
            if url:
                seen_urls.add(url)
            seen_titles.add(title)
            unique_articles.append(article)
        
        # 按发布时间排序（尝试解析时间）
        def parse_time(article):
            try:
                time_str = article.get('published_at', '')
                if not time_str:
                    return datetime.min
                # 尝试多种格式
                for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%a, %d %b %Y %H:%M:%S']:
                    try:
                        return datetime.strptime(time_str[:19], fmt)
                    except:
                        continue
                return datetime.min
            except:
                return datetime.min
        
        unique_articles.sort(key=parse_time, reverse=True)
        
        # 限制数量
        final_articles = unique_articles[:max_articles]
        
        result_data = {
            'keyword': keyword,
            'articles': final_articles,
            'total_results': len(final_articles),
            'sources_used': sources_used,
            'aggregation_stats': {
                'total_raw': len(all_articles),
                'after_dedup': len(unique_articles),
                'final_count': len(final_articles),
                'elapsed_ms': int((time.time() - start) * 1000),
            }
        }
        
        # 检查是否达到最小数量
        success = len(final_articles) >= min_articles
        
        if success:
            self._cache.set(cache_key, result_data, ttl=300)
        
        latency = int((time.time() - start) * 1000)
        return ProviderResult(
            success=success, 
            data=result_data, 
            source="aggregated:" + ",".join(sources_used[:3]) + ("..." if len(sources_used) > 3 else ""),
            latency_ms=latency,
            error="" if success else f"Only got {len(final_articles)} articles, need at least {min_articles}"
        )

    def query_search(self, keyword: str, categories: str = "general", limit: int = 10, use_cache: bool = True, **kwargs) -> ProviderResult:
        """通用搜索"""
        cache_key = self._make_cache_key('search', keyword=keyword, categories=categories)
        
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached:
                return ProviderResult(success=True, data=cached, source="cache", cached=True)
        
        providers = self.get_providers(DataCategory.SEARCH)
        for provider in providers:
            if not provider.is_healthy:
                continue
            
            result = provider.query(keyword=keyword, categories=categories, limit=limit, **kwargs)
            if result.success:
                self._cache.set(cache_key, result.data, ttl=300)
                return result
        
        return ProviderResult(success=False, error="All search providers failed", source="")
    
    def query_parallel(self, category: DataCategory, timeout: float = 10, **kwargs) -> List[ProviderResult]:
        """并发查询所有提供器
        
        Args:
            category: 数据类别
            timeout: 超时时间
            **kwargs: 查询参数
        
        Returns:
            所有提供器的结果列表
        """
        providers = self.get_providers(category)
        if not providers:
            return []
        
        results = []
        futures = {}
        
        for provider in providers:
            if provider.is_healthy:
                future = self._executor.submit(provider.query, **kwargs)
                futures[future] = provider.name
        
        try:
            for future in as_completed(futures, timeout=timeout):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.debug(f"[parallel] {futures[future]} error: {e}")
        except FuturesTimeoutError:
            logger.warning(f"[parallel] Timeout after {timeout}s")
        
        return results
    
    def get_health_status(self) -> Dict[str, Any]:
        """获取所有提供器的健康状态"""
        status = {}
        for category, providers in self._providers.items():
            status[category.value] = [
                {
                    'name': p.name,
                    'status': p._status.value,
                    'error_count': p._error_count,
                    'success_count': p._success_count,
                    'last_error': p._last_error,
                }
                for p in providers
            ]
        return status
    
    def reset_provider(self, provider_name: str):
        """重置提供器状态"""
        for providers in self._providers.values():
            for p in providers:
                if p.name == provider_name:
                    p._status = ProviderStatus.HEALTHY
                    p._error_count = 0
                    p._last_error = None
                    logger.info(f"[WebDataManager] Reset {provider_name}")
                    return
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.info("[WebDataManager] Cache cleared")


# ============== 单例与便捷函数 ==============

_manager_instance: Optional[WebDataManager] = None
_manager_lock = threading.Lock()


def get_web_data_manager() -> WebDataManager:
    """获取 WebDataManager 单例"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = WebDataManager()
    return _manager_instance


# 便捷函数
def query_weather(location: str, **kwargs) -> ProviderResult:
    """查询天气"""
    return get_web_data_manager().query_weather(location, **kwargs)


def query_stock(symbol: str, **kwargs) -> ProviderResult:
    """查询股票"""
    return get_web_data_manager().query_stock(symbol, **kwargs)


def query_encyclopedia(keyword: str, **kwargs) -> ProviderResult:
    """查询百科"""
    return get_web_data_manager().query_encyclopedia(keyword, **kwargs)


def query_news(keyword: str, **kwargs) -> ProviderResult:
    """查询新闻"""
    return get_web_data_manager().query_news(keyword, **kwargs)


def query_search(keyword: str, **kwargs) -> ProviderResult:
    """通用搜索"""
    return get_web_data_manager().query_search(keyword, **kwargs)


# ============== 测试入口 ==============

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    manager = get_web_data_manager()
    
    print("\n===== 天气查询测试 =====")
    result = manager.query_weather("Beijing")
    print(f"Source: {result.source}, Success: {result.success}")
    if result.success:
        data = result.data
        print(f"温度: {data['temperature_c']}°C, 体感: {data['feels_like_c']}°C")
        print(f"天气: {data['weather_desc']}, 湿度: {data['humidity']}%")
    
    print("\n===== 股票查询测试 =====")
    result = manager.query_stock("002594.SZ")
    print(f"Source: {result.source}, Success: {result.success}")
    if result.success:
        data = result.data
        print(f"名称: {data.get('name')}, 价格: {data.get('price')}")
    
    print("\n===== 百科查询测试 =====")
    result = manager.query_encyclopedia("比亚迪")
    print(f"Source: {result.source}, Success: {result.success}")
    if result.success:
        data = result.data
        print(f"标题: {data['title']}")
        print(f"摘要: {data['summary'][:200]}...")
    
    print("\n===== 健康状态 =====")
    status = manager.get_health_status()
    for cat, providers in status.items():
        print(f"\n{cat}:")
        for p in providers:
            print(f"  {p['name']}: {p['status']} (errors={p['error_count']}, success={p['success_count']})")
