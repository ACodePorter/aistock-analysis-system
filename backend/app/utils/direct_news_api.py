"""
直接新闻API模块 - 绕过SearXNG的独立信源

当SearXNG不可用或引擎被封时，直接调用财经网站API获取新闻数据。
优先级：东方财富 > 同花顺 > 新浪财经 > 雪球

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
from urllib.parse import quote, urljoin
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)

# ============ 配置 ============
DIRECT_API_TIMEOUT = float(os.getenv('DIRECT_API_TIMEOUT', '10'))
DIRECT_API_MAX_RETRIES = int(os.getenv('DIRECT_API_MAX_RETRIES', '2'))
DIRECT_API_ENABLED = os.getenv('DIRECT_API_ENABLED', '1') in ('1', 'true', 'yes')

# User-Agent池
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
]


class DirectNewsAPI:
    """直接财经API调用器
    
    不依赖SearXNG，直接调用各财经网站的公开API获取新闻数据。
    """
    
    def __init__(self):
        self.session = requests.Session()
        self._last_request_time: Dict[str, float] = {}
        self._rate_limits = {
            'eastmoney': 0.5,
            'tonghuashun': 0.8,
            'sina': 0.5,
            'xueqiu': 1.0,
            'cls': 0.5,
            'hexun': 0.5,
            'jrj': 0.5,
        }
        self._source_healthy: Dict[str, bool] = {}
        self._source_last_check: Dict[str, datetime] = {}
        # source priority: higher number => higher priority when sorting
        self._source_priority = {
            'eastmoney_api': 5,
            'eastmoney_headless': 4,
            'tonghuashun_api': 4,
            'cls_api': 4,
            'sina_api': 3,
            'hexun_api': 3,
            'jrj_api': 2,
            'ifeng': 2,
            '163': 2,
            '21jingji': 1,
            'eastmoney_scrape': 2,
            'akshare': 1,
        }
        # 代理池与 cookie 持久化配置
        self._proxy_pool = []
        proxy_env = os.getenv('DIRECT_API_PROXY_POOL', '')
        if proxy_env:
            self._proxy_pool = [p.strip() for p in proxy_env.split(',') if p.strip()]
        self._proxy_index = 0
        self._cookie_file = os.getenv('DIRECT_API_COOKIE_FILE', '')
        if self._cookie_file:
            try:
                self._load_cookies()
            except Exception:
                pass
        # headless cache 初始化
        self._cache_dir = Path(os.getenv('DIRECT_API_HEADLESS_CACHE_DIR', 'var/direct_headless_cache'))
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # cache ttl days
        try:
            self._headless_cache_ttl = int(os.getenv('DIRECT_API_HEADLESS_CACHE_TTL_DAYS', '7'))
        except Exception:
            self._headless_cache_ttl = 7
    
    def _get_headers(self, source: str = 'default') -> Dict[str, str]:
        """获取请求头"""
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        if source == 'eastmoney':
            headers['Referer'] = 'https://www.eastmoney.com/'
            headers['X-Requested-With'] = 'XMLHttpRequest'
            headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
        elif source == 'tonghuashun':
            headers['Referer'] = 'https://www.10jqka.com.cn/'
        elif source == 'sina':
            headers['Referer'] = 'https://finance.sina.com.cn/'
        elif source == 'xueqiu':
            headers['Referer'] = 'https://xueqiu.com/'
            headers['Cookie'] = 'xq_a_token=mock'  # 需要有cookie才能访问
        return headers
    
    def _rate_limit(self, source: str):
        """速率限制"""
        limit = self._rate_limits.get(source, 0.5)
        last = self._last_request_time.get(source, 0)
        elapsed = time.time() - last
        if elapsed < limit:
            time.sleep(limit - elapsed + random.uniform(0.1, 0.3))
        self._last_request_time[source] = time.time()
    
    def _safe_request(self, url: str, source: str, params: Dict = None, timeout: float = None) -> Optional[requests.Response]:
        """安全请求"""
        self._rate_limit(source)
        timeout = timeout or DIRECT_API_TIMEOUT
        # 支持可选全局代理：设置 DIRECT_API_USE_PROXY=1 和 DIRECT_API_PROXY=http://host:port
        use_proxy = os.getenv('DIRECT_API_USE_PROXY', '0') == '1'
        proxies = None
        if use_proxy:
            # 优先使用单一代理配置
            proxy_url = os.getenv('DIRECT_API_PROXY', '')
            if proxy_url:
                proxies = {'http': proxy_url, 'https': proxy_url}
            elif self._proxy_pool:
                # 循环使用代理池
                proxy = self._get_next_proxy()
                proxies = {'http': proxy, 'https': proxy}

        for attempt in range(DIRECT_API_MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, headers=self._get_headers(source), timeout=timeout, proxies=proxies)
                if resp.status_code == 200:
                    # 保存 cookies 到文件（如配置）
                    if self._cookie_file:
                        try:
                            self._save_cookies()
                        except Exception:
                            pass
                    return resp
                logger.debug(f"[direct-api] {source} status={resp.status_code} url={url}")
            except Exception as e:
                logger.debug(f"[direct-api] {source} attempt {attempt+1} failed: {e}")
                if attempt < DIRECT_API_MAX_RETRIES - 1:
                    time.sleep(0.5 * (attempt + 1))
        return None

    def _get_next_proxy(self) -> Optional[str]:
        if not self._proxy_pool:
            return None
        proxy = self._proxy_pool[self._proxy_index % len(self._proxy_pool)]
        self._proxy_index = (self._proxy_index + 1) % len(self._proxy_pool)
        return proxy

    def _load_cookies(self):
        try:
            import pickle
            with open(self._cookie_file, 'rb') as f:
                cj = pickle.load(f)
                # 兼容 requests cookiejar or dict
                try:
                    self.session.cookies.update(cj)
                except Exception:
                    # 如果是 CookieJar
                    self.session.cookies = cj
        except Exception as e:
            logger.debug(f"[cookies] load failed: {e}")

    # ----------------- headless local cache -----------------
    def _cache_path_for_url(self, url: str) -> Path:
        key = hashlib.sha256(url.encode('utf-8')).hexdigest()
        return self._cache_dir / f"{key}.json"

    def _headless_cache_get(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            p = self._cache_path_for_url(url)
            if not p.exists():
                return None
            data = json.loads(p.read_text(encoding='utf-8'))
            ts = data.get('ts')
            if ts:
                try:
                    t = datetime.fromisoformat(ts)
                    if (datetime.utcnow() - t).days > self._headless_cache_ttl:
                        try:
                            p.unlink()
                        except Exception:
                            pass
                        return None
                except Exception:
                    pass
            return data
        except Exception:
            return None

    def _headless_cache_set(self, url: str, payload: Dict[str, Any]) -> None:
        try:
            p = self._cache_path_for_url(url)
            payload = dict(payload)
            payload['ts'] = datetime.utcnow().isoformat()
            tmp = p.with_suffix('.tmp')
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            try:
                tmp.replace(p)
            except Exception:
                try:
                    tmp.rename(p)
                except Exception:
                    pass
        except Exception:
            pass

    def _save_cookies(self):
        try:
            import pickle
            with open(self._cookie_file, 'wb') as f:
                pickle.dump(self.session.cookies, f)
        except Exception as e:
            logger.debug(f"[cookies] save failed: {e}")

    def _try_eastmoney_api_variants(self, url: str, params: Dict = None, timeout: float = None) -> Optional[requests.Response]:
        """为东方财富专门尝试不同UA/头/Cookie/代理组合以恢复API访问。

        优先使用常规 _safe_request，当失败时循环尝试几种头部与cookie组合。
        """
        # 首先一次常规请求
        resp = self._safe_request(url, 'eastmoney', params, timeout)
        if resp:
            return resp

        # 变体尝试
        ualist = [
            USER_AGENTS[0],
            USER_AGENTS[1],
            'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
            'Mozilla/5.0 (Linux; Android 12; SM-G9910) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116 Mobile Safari/537.36',
        ]
        extra_headers = [
            {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json, text/javascript, */*; q=0.01'},
            {'Referer': 'https://www.eastmoney.com/', 'Origin': 'https://www.eastmoney.com'},
            {'Referer': 'https://quote.eastmoney.com/'},
        ]

        for ua in ualist:
            for hdrs in extra_headers:
                try:
                    headers = self._get_headers('eastmoney')
                    headers.update(hdrs)
                    headers['User-Agent'] = ua
                    # 尝试带不同cookie（空或轻量常见cookie）
                    cookies_options = [None, {'EM_Auth': '1'}, {'device': 'mobile'}]
                    for ck in cookies_options:
                        try:
                            resp = self.session.get(url, params=params, headers=headers, timeout=(timeout or DIRECT_API_TIMEOUT))
                            if resp and resp.status_code == 200:
                                return resp
                        except Exception as e:
                            logger.debug(f"[eastmoney-variants] ua={ua} hdrs={hdrs} cookie={ck} fail={e}")
                            time.sleep(0.2)
                except Exception:
                    continue
        return None

    def _decode_content(self, content: bytes, prefer: Optional[str] = None) -> str:
        """尝试以多种编码解码字节内容，选择最合理的文本结果。

        优先尝试 `prefer`，然后 utf-8、gb18030、latin1。
        通过检测中文字符比例选择解码结果。
        """
        if not content:
            return ''
        candidates = []
        if prefer:
            candidates.append(prefer)
        candidates.extend(['utf-8', 'gb18030', 'gbk', 'latin1'])

        def score_text(s: str) -> float:
            # 中文字符比例 + 非替换字符比例
            if not s:
                return 0.0
            chinese = sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff')
            repl = s.count('\ufffd')
            return (chinese / max(1, len(s))) - (repl * 0.01)

        best = ''
        best_score = -999.0
        for enc in candidates:
            try:
                txt = content.decode(enc, errors='replace')
            except Exception:
                continue
            sc = score_text(txt)
            if sc > best_score:
                best_score = sc
                best = txt
            # if we find a clearly good utf-8 with no replacement, prefer it
            if enc == 'utf-8' and '\ufffd' not in txt:
                return txt
        return best
    
    # ============ 东方财富 API ============
    def fetch_eastmoney_stock_news(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取东方财富股票新闻
        
        使用东方财富公开API获取个股相关新闻
        """
        results = []
        
        # 尝试多个API端点
        apis = [
            # 个股新闻API
            {
                'url': 'https://np-listapi.eastmoney.com/comm/wap/getListInfo',
                'params': {
                    'type': 'ZHB',
                    'ps': str(limit),
                    'p': '1',
                    'code': stock_code.replace('.SH', '').replace('.SZ', ''),
                    'plat': 'wap',
                    'version': '1'
                }
            , 'timeout': 12
            },
            # 财经快讯API
            {
                'url': 'https://np-listapi.eastmoney.com/comm/wap/getListInfo',
                'params': {
                    'cb': '',
                    'client': 'wap',
                    'type': 'CFHPL',
                    'ps': str(limit),
                    'p': '1',
                    'spt': 'all',
                    'fields': 'title,summary,url,showtime'
                }
            , 'timeout': 12
            }
        ]
        
        for api in apis:
            try:
                # 优先使用常规请求，若无响应则尝试不同 UA/cookie/头 变体
                resp = self._safe_request(api['url'], 'eastmoney', api.get('params'), timeout=api.get('timeout', None))
                if not resp:
                    resp = self._try_eastmoney_api_variants(api['url'], api.get('params'), timeout=api.get('timeout', None))
                if not resp:
                    continue

                # 处理JSONP响应
                text = resp.text
                if text.startswith('('):
                    text = text[1:-1]
                if text.startswith('callback'):
                    text = re.sub(r'^callback\(|\);?$', '', text)

                try:
                    data = json.loads(text)
                except Exception as _je:
                    logger.debug(f"[eastmoney-api] json parse failed: {_je} snippet={text[:200]}")
                    data = {}

                items = data.get('data', {}).get('list', []) or data.get('data', [])

                for item in items[:limit]:
                    if not isinstance(item, dict):
                        continue

                    title = item.get('title', '') or item.get('Art_Title', '')
                    url = item.get('url', '') or item.get('Art_Url', '')
                    content = item.get('summary', '') or item.get('Art_Content', '') or ''
                    pub_time = item.get('showtime', '') or item.get('Art_ShowTime', '')

                    if title and url:
                        results.append({
                            'title': title.strip(),
                            'url': url if url.startswith('http') else f'https:{url}',
                            'content': content[:500] if content else '',
                            'published_at': pub_time,
                            'source': 'eastmoney_api',
                            'source_name': '东方财富',
                        })

                if results:
                    break
                else:
                    # Log when API returned no usable items for debugging
                    logger.debug(f"[eastmoney-api] no results from {api.get('url')} params={api.get('params')} status={resp.status_code} snippet={text[:200]}")

            except Exception as e:
                logger.debug(f"[eastmoney-api] error: {e}")
        
        # 如果API没有返回结果，尝试HTML抓取作为兜底
        if not results:
            try:
                scraped = self._scrape_eastmoney_stock_page(stock_code, limit=limit)
                if scraped:
                    results.extend(scraped)
                    logger.debug(f"[eastmoney-api] used scrape fallback, added {len(scraped)} items")
            except Exception as _s:
                logger.debug(f"[eastmoney-api] scrape fallback failed: {_s}")

        # 如果仍无结果，尝试使用 headless 深度抓取（仅在环境允许时）
        if not results and os.getenv('DIRECT_API_USE_HEADLESS', '0') == '1' and self._should_run_headless():
            try:
                headless_items = self.fetch_eastmoney_via_headless(stock_code, limit)
                if headless_items:
                    results.extend(headless_items)
                    logger.debug(f"[eastmoney-api] used headless fallback, added {len(headless_items)} items")
            except Exception as _h:
                logger.debug(f"[eastmoney-api] headless fallback failed: {_h}")

        return results[:limit]
    
    def fetch_eastmoney_industry_news(self, industry: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """获取东方财富行业新闻

        如果未指定 `industry`，则回退到通用财经快讯接口以避免调用必须传参导致的错误。
        """
        results = []

        # 行业板块新闻
        url = 'https://np-listapi.eastmoney.com/comm/wap/getListInfo'
        # 如果未提供 industry，则使用通用财经快讯类型，避免必须传参导致调用失败
        if not industry:
            params = {
                'cb': '',
                'client': 'wap',
                'type': 'CFHPL',
                'ps': str(limit),
                'p': '1',
            }
        else:
            params = {
                'cb': '',
                'client': 'wap',
                'type': 'CFHPLSASTOCK',
                'ps': str(limit),
                'p': '1',
                'mession': quote(industry),
            }

        try:
            resp = self._safe_request(url, 'eastmoney', params)
            if resp:
                text = resp.text
                if text.startswith('('):
                    text = text[1:-1]
                try:
                    data = json.loads(text)
                except Exception as _je:
                    logger.debug(f"[eastmoney-industry] json parse failed: {_je} snippet={text[:200]}")
                    data = {}
                items = data.get('data', {}).get('list', []) or []

                for item in items[:limit]:
                    title = item.get('title', '')
                    url = item.get('url', '')
                    if title and url:
                        results.append({
                            'title': title.strip(),
                            'url': url if url.startswith('http') else f'https:{url}',
                            'content': (item.get('summary', '') or '')[:500],
                            'published_at': item.get('showtime', ''),
                            'source': 'eastmoney_api',
                            'source_name': '东方财富',
                            'is_industry_news': True,
                        })
            else:
                logger.debug(f"[eastmoney-industry] no response for params={params}")
        except Exception as e:
            logger.debug(f"[eastmoney-industry] error: {e}")

        if not results:
            logger.debug(f"[eastmoney-industry] returned 0 items params={params}")

        return results

    def _scrape_eastmoney_stock_page(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """HTML抓取东方财富个股页，作为API回退。

        目标页面示例： https://quote.eastmoney.com/{code}.html
        仅做轻量解析（不新增第三方依赖），提取链接与标题作为候选新闻。
        """
        results: List[Dict[str, Any]] = []
        try:
            code = stock_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            url = f"https://quote.eastmoney.com/{code}.html"
            resp = self._safe_request(url, 'eastmoney', params=None, timeout=max(DIRECT_API_TIMEOUT, 12))
            if not resp:
                logger.debug(f"[eastmoney-scrape] no response for {url}")
                return results
            text = resp.text
            # 尝试使用 BeautifulSoup 优先解析（更鲁棒）
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.content, 'html.parser')
                anchors = soup.find_all('a', href=True)
                seen = set()
                for a in anchors:
                    if len(results) >= limit:
                        break
                    h = a['href']
                    t = a.get_text(strip=True)
                    if not t:
                        continue
                    if ('eastmoney.com' not in h) and ('/a/' not in h) and ('/news/' not in h) and not h.startswith('/'):
                        continue
                    if h.startswith('//'):
                        full = 'https:' + h
                    elif h.startswith('/'):
                        full = urljoin('https://www.eastmoney.com', h)
                    elif h.startswith('http'):
                        full = h
                    else:
                        full = urljoin(url, h)
                    if full in seen:
                        continue
                    seen.add(full)
                    results.append({
                        'title': t,
                        'url': full,
                        'content': '',
                        'source': 'eastmoney_scrape',
                        'source_name': '东方财富(抓取)'
                    })
            except Exception:
                # 回退到简单正则解析
                anchors = re.findall(r"<a[^>]+href=[\'\"](?P<h>[^\'\"]+)[\'\"][^>]*>(?P<t>.*?)</a>", text, flags=re.I | re.S)
                seen = set()
                for h, t in anchors:
                    if len(results) >= limit:
                        break
                    if ('eastmoney.com' not in h) and ('/a/' not in h) and ('/news/' not in h) and not h.startswith('/'):
                        continue
                    title = re.sub(r'<[^>]+>', '', t or '').strip()
                    if not title:
                        continue
                    if h.startswith('//'):
                        full = 'https:' + h
                    elif h.startswith('/'):
                        full = urljoin('https://www.eastmoney.com', h)
                    elif h.startswith('http'):
                        full = h
                    else:
                        full = urljoin(url, h)
                    if full in seen:
                        continue
                    seen.add(full)
                    results.append({
                        'title': title,
                        'url': full,
                        'content': '',
                        'source': 'eastmoney_scrape',
                        'source_name': '东方财富(抓取)'
                    })
        except Exception as e:
            logger.debug(f"[eastmoney-scrape] error: {e}")
        return results
    
    # ============ 同花顺 API ============
    def fetch_tonghuashun_news(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取同花顺新闻"""
        results = []
        
        # 同花顺搜索API
        url = 'https://news.10jqka.com.cn/tapp/news/push/stock/'
        params = {
            'page': '1',
            'tag': '',
            'track': 'website',
            'pagesize': str(limit),
        }
        
        try:
            resp = self._safe_request(url, 'tonghuashun', params)
            if resp:
                data = resp.json()
                items = data.get('data', {}).get('list', []) or []
                
                for item in items[:limit]:
                    title = item.get('title', '')
                    url = item.get('url', '') or item.get('link', '')
                    if title and url:
                        results.append({
                            'title': title.strip(),
                            'url': url,
                            'content': (item.get('digest', '') or item.get('summary', '') or '')[:500],
                            'published_at': item.get('ctime', '') or item.get('datetime', ''),
                            'source': 'tonghuashun_api',
                            'source_name': '同花顺',
                        })
        except Exception as e:
            logger.debug(f"[tonghuashun-api] error: {e}")
        
        # 备用：同花顺7x24快讯
        if not results:
            url2 = 'https://news.10jqka.com.cn/tapp/news/push/express/'
            try:
                resp = self._safe_request(url2, 'tonghuashun', {'page': '1', 'pagesize': str(limit)})
                if resp:
                    data = resp.json()
                    items = data.get('data', {}).get('list', []) or []
                    for item in items[:limit]:
                        title = item.get('title', '') or item.get('digest', '')
                        if title:
                            results.append({
                                'title': title.strip()[:200],
                                'url': item.get('url', '') or f"https://news.10jqka.com.cn/{item.get('seq', '')}",
                                'content': (item.get('digest', '') or '')[:500],
                                'published_at': item.get('ctime', ''),
                                'source': 'tonghuashun_api',
                                'source_name': '同花顺快讯',
                            })
            except Exception as e:
                logger.debug(f"[tonghuashun-express] error: {e}")
        
        return results
    
    # ============ 新浪财经 API ============
    def fetch_sina_stock_news(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取新浪财经个股新闻"""
        results = []
        
        # 新浪财经股票新闻API
        code = stock_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        market = 'sh' if stock_code.endswith('.SH') else ('sz' if stock_code.endswith('.SZ') else 'bj')
        
        url = f'https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php'
        params = {
            'symbol': f'{market}{code}',
            'Page': '1',
        }
        
        try:
            resp = self._safe_request(url, 'sina', params, timeout=8)
            if resp:
                # 解析HTML获取新闻列表：先解码再解析以避免编码错乱
                text = self._decode_content(resp.content, prefer=resp.encoding)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(text, 'html.parser')

                links = soup.select('a[href*="finance.sina.com.cn"]')[:limit]
                for link in links:
                    title = link.get_text(strip=True)
                    href = link.get('href', '')
                    if title and href and len(title) > 5:
                        results.append({
                            'title': title,
                            'url': href,
                            'content': '',
                            'source': 'sina_api',
                            'source_name': '新浪财经',
                        })
        except Exception as e:
            logger.debug(f"[sina-stock] error: {e}")
        
        # 备用：新浪财经快讯
        if not results:
            url2 = 'https://feed.mix.sina.com.cn/api/roll/get'
            params2 = {
                'pageid': '153',
                'lid': '2516',
                'num': str(limit),
                'page': '1',
            }
            try:
                resp = self._safe_request(url2, 'sina', params2)
                if resp:
                    data = resp.json()
                    items = data.get('result', {}).get('data', []) or []
                    for item in items[:limit]:
                        title = item.get('title', '')
                        url = item.get('url', '')
                        if title and url:
                            results.append({
                                'title': title.strip(),
                                'url': url,
                                'content': (item.get('intro', '') or '')[:500],
                                'published_at': item.get('ctime', ''),
                                'source': 'sina_api',
                                'source_name': '新浪财经',
                            })
            except Exception as e:
                logger.debug(f"[sina-roll] error: {e}")
        
        return results
    
    # ============ 财联社 API ============
    def fetch_cls_news(self, keyword: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """获取财联社快讯"""
        results = []
        
        # 财联社电报API
        url = 'https://www.cls.cn/nodeapi/updateTelegraphList'
        params = {
            'app': 'CailianpressWeb',
            'os': 'web',
            'sv': '8.4.6',
            'rn': str(limit),
        }
        
        try:
            resp = self._safe_request(url, 'cls', params)
            if resp:
                data = resp.json()
                items = data.get('data', {}).get('roll_data', []) or []
                
                for item in items[:limit]:
                    title = item.get('title', '') or item.get('brief', '') or item.get('content', '')[:100]
                    content = item.get('content', '') or item.get('brief', '')
                    
                    if title:
                        results.append({
                            'title': title.strip()[:200],
                            'url': f"https://www.cls.cn/detail/{item.get('id', '')}",
                            'content': content[:500] if content else '',
                            'published_at': item.get('ctime', ''),
                            'source': 'cls_api',
                            'source_name': '财联社',
                        })
        except Exception as e:
            logger.debug(f"[cls-api] error: {e}")
        
        return results
    
    # ============ 和讯网 API ============
    def fetch_hexun_news(self, keyword: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """获取和讯财经新闻"""
        results = []
        
        # 和讯股票新闻
        url = 'https://open.hexun.com/api/v2/news/getStockNewsList'
        params = {
            'newstype': '1',
            'pagesize': str(limit),
            'pageindex': '1',
        }
        
        try:
            resp = self._safe_request(url, 'hexun', params)
            if resp:
                data = resp.json()
                items = data.get('data', []) or []
                
                for item in items[:limit]:
                    title = item.get('title', '')
                    url = item.get('url', '')
                    if title and url:
                        results.append({
                            'title': title.strip(),
                            'url': url,
                            'content': (item.get('summary', '') or '')[:500],
                            'published_at': item.get('pubtime', ''),
                            'source': 'hexun_api',
                            'source_name': '和讯网',
                        })
        except Exception as e:
            logger.debug(f"[hexun-api] error: {e}")
        
        return results
    
    # ============ 金融界 API ============
    def fetch_jrj_news(self, keyword: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """获取金融界新闻"""
        results = []
        
        # 金融界股票新闻
        url = 'https://stock.jrj.com.cn/tzzs/zdggnews.shtml'
        
        try:
            resp = self._safe_request(url, 'jrj', {}, timeout=8)
            if resp:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.content, 'html.parser')
                
                # 解析新闻列表
                links = soup.select('a[href*="stock.jrj.com.cn"]')[:limit]
                for link in links:
                    title = link.get_text(strip=True)
                    href = link.get('href', '')
                    if title and href and len(title) > 8:
                        results.append({
                            'title': title,
                            'url': href if href.startswith('http') else f'https:{href}',
                            'content': '',
                            'source': 'jrj_api',
                            'source_name': '金融界',
                        })
        except Exception as e:
            logger.debug(f"[jrj-api] error: {e}")
        
        return results

    # ============ 凤凰 / 网易 / 21经济网 抓取 ============
    def fetch_ifeng_news(self, keyword: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """抓取凤凰网财经相关新闻（轻量）"""
        results = []
        try:
            url = 'https://finance.ifeng.com/'
            resp = self._safe_request(url, 'ifeng', {}, timeout=8)
            if not resp:
                return results
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.content, 'html.parser')
                for a in soup.select('a[href*="ifeng.com"][title]')[:limit]:
                    title = a.get('title') or a.get_text(strip=True)
                    href = a.get('href')
                    if title and href:
                        results.append({'title': title.strip(), 'url': href, 'content': '', 'source': 'ifeng', 'source_name': '凤凰财经'})
            except Exception:
                # fallback regex
                anchors = re.findall(r"<a[^>]+href=['\"](?P<h>[^'\"]+)['\"][^>]*>(?P<t>.*?)</a>", resp.text, flags=re.I|re.S)
                seen = set()
                for h, t in anchors:
                    if len(results) >= limit:
                        break
                    if 'ifeng.com' not in h:
                        continue
                    title = re.sub(r'<[^>]+>', '', t).strip()
                    if title and h not in seen:
                        seen.add(h)
                        results.append({'title': title, 'url': h, 'content': '', 'source': 'ifeng', 'source_name': '凤凰财经'})
        except Exception as e:
            logger.debug(f"[ifeng-scrape] error: {e}")
        return results

    def fetch_163_news(self, keyword: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """抓取网易财经（money.163.com）"""
        results = []
        try:
            url = 'https://money.163.com/'
            resp = self._safe_request(url, '163', {}, timeout=8)
            if not resp:
                return results
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.content, 'html.parser')
                for a in soup.select('a[href*="money.163.com"]')[:limit*2]:
                    title = a.get_text(strip=True)
                    href = a.get('href')
                    if title and href and href.startswith('http'):
                        results.append({'title': title, 'url': href, 'content': '', 'source': '163', 'source_name': '网易财经'})
                        if len(results) >= limit:
                            break
            except Exception:
                anchors = re.findall(r"<a[^>]+href=['\"](?P<h>[^'\"]+)['\"][^>]*>(?P<t>.*?)</a>", resp.text, flags=re.I|re.S)
                seen = set()
                for h, t in anchors:
                    if len(results) >= limit:
                        break
                    if 'money.163.com' not in h:
                        continue
                    title = re.sub(r'<[^>]+>', '', t).strip()
                    if title and h not in seen:
                        seen.add(h)
                        results.append({'title': title, 'url': h, 'content': '', 'source': '163', 'source_name': '网易财经'})
        except Exception as e:
            logger.debug(f"[163-scrape] error: {e}")
        return results

    def fetch_21jingji_news(self, keyword: str = '', limit: int = 10) -> List[Dict[str, Any]]:
        """抓取21经济网新闻"""
        results = []
        try:
            url = 'https://www.21jingji.com/'
            resp = self._safe_request(url, '21jingji', {}, timeout=8)
            if not resp:
                return results
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.content, 'html.parser')
                for a in soup.select('a[href*="21jingji.com"]')[:limit*2]:
                    title = a.get_text(strip=True)
                    href = a.get('href')
                    if title and href and href.startswith('http'):
                        results.append({'title': title, 'url': href, 'content': '', 'source': '21jingji', 'source_name': '21经济网'})
                        if len(results) >= limit:
                            break
            except Exception:
                anchors = re.findall(r"<a[^>]+href=['\"](?P<h>[^'\"]+)['\"][^>]*>(?P<t>.*?)</a>", resp.text, flags=re.I|re.S)
                seen = set()
                for h, t in anchors:
                    if len(results) >= limit:
                        break
                    if '21jingji.com' not in h:
                        continue
                    title = re.sub(r'<[^>]+>', '', t).strip()
                    if title and h not in seen:
                        seen.add(h)
                        results.append({'title': title, 'url': h, 'content': '', 'source': '21jingji', 'source_name': '21经济网'})
        except Exception as e:
            logger.debug(f"[21jingji-scrape] error: {e}")
        return results

    # ============ Akshare / Headless 可选回退（按需导入） ============
    def fetch_eastmoney_via_akshare(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """尝试使用 akshare 获取相关新闻（如果 akshare 可用）。

        该方法为可选回退；若未安装 `akshare`，将静默返回空列表。
        """
        try:
            import akshare as ak  # type: ignore
        except Exception:
            logger.debug('[akshare] akshare not available')
            return []
        # akshare 的具体新闻API在不同版本中可能不同，这里尝试通用调用并安全降级
        try:
            # 占位：如果akshare提供新闻接口，可在此处调用并格式化结果
            return []
        except Exception as e:
            logger.debug(f"[akshare] error: {e}")
            return []

    def fetch_eastmoney_via_headless(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """尝试使用无头浏览器渲染页面并抓取（Playwright/Selenium 按需导入）。

        如果运行环境没有这些依赖，函数将优雅地返回空列表。
        """
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception:
            logger.debug('[headless] playwright not available')
            return []
        results = []
        try:
            code = stock_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            url = f'https://quote.eastmoney.com/{code}.html'
            # 深度抓取：先在股票页收集文章链接，再逐篇打开并提取正文
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                try:
                    page.goto(url, timeout=20000)
                except Exception:
                    # 如果首屏导航失败，仍尝试获取静态内容
                    pass

                content = page.content()
                # 提取候选链接
                anchors = re.findall(r"<a[^>]+href=['\"](?P<h>[^'\"]+)['\"][^>]*>(?P<t>.*?)</a>", content, flags=re.I|re.S)
                seen_links = []
                seen = set()
                for h, t in anchors:
                    if ('eastmoney.com' not in h) and ('/a/' not in h) and ('/news/' not in h):
                        continue
                    title = re.sub(r'<[^>]+>', '', t or '').strip()
                    if not title or len(title) < 5:
                        continue
                    if h.startswith('//'):
                        full = 'https:' + h
                    elif h.startswith('/'):
                        full = urljoin('https://www.eastmoney.com', h)
                    elif h.startswith('http'):
                        full = h
                    else:
                        full = urljoin(url, h)
                    if full in seen:
                        continue
                    seen.add(full)
                    seen_links.append((title, full))

                # 打开每个文章链接，提取正文（选择常见文章容器，若无则使用段落合并）
                for title, link in seen_links[: max(limit * 3, limit)]:
                    if len(results) >= limit:
                        break
                    try:
                        # 尝试从本地缓存获取已抓取的正文，优先使用缓存以提升数据质量与稳定性
                        cached = self._headless_cache_get(link)
                        if cached and cached.get('content'):
                            is_rich = bool(cached.get('rich_content'))
                            results.append({'title': cached.get('title', title), 'url': link, 'content': cached.get('content','')[:4000], 'source': 'eastmoney_headless', 'source_name': '东方财富(渲染抓取)', 'rich_content': is_rich})
                            # 如果已达阈值则跳过实际导航
                            if len(results) >= limit:
                                break
                            # else continue to next link (avoid unnecessary re-fetch)
                            continue
                        # 小心导航超时且短暂等待资源加载
                        page.goto(link, timeout=12000)
                        # 等待可能的文章容器出现
                        selectors = [
                            'div.article-content', 'div#Content', 'div.body', 'div.content',
                            'div.article', 'div.artical-main', 'div.module-para', 'article',
                            'div#articleContent', 'div[class*="article"]', 'div[class*="Content"]'
                        ]
                        text_blocks = ''
                        for sel in selectors:
                            try:
                                el = page.query_selector(sel)
                                if el:
                                    text_blocks = (el.inner_text() or '').strip()
                                    if len(text_blocks) > 60:
                                        break
                            except Exception:
                                continue

                        # 如果没有通过选择器得到足够内容，回退到收集所有<p>文本
                        if not text_blocks or len(text_blocks) < 60:
                            try:
                                paras = page.query_selector_all('p')
                                combined = []
                                for p_el in paras:
                                    try:
                                        t = (p_el.inner_text() or '').strip()
                                        if t and len(t) > 20:
                                            combined.append(t)
                                    except Exception:
                                        continue
                                text_blocks = '\n\n'.join(combined)
                            except Exception:
                                text_blocks = ''

                        # 做一次简短清洗，限制长度
                        content_text = (text_blocks or '')
                        if content_text:
                            content_text = re.sub(r'\s{2,}', ' ', content_text).strip()

                        # 标注内容丰富标志（可配置阈值），便于合并时优先使用
                        rich_thresh = int(os.getenv('DIRECT_API_HEADLESS_RICH_THRESH', '300'))
                        is_rich = bool(content_text and len(content_text) >= rich_thresh)
                        item = {'title': title, 'url': link, 'content': content_text[:4000], 'source': 'eastmoney_headless', 'source_name': '东方财富(渲染抓取)', 'rich_content': is_rich}
                        results.append(item)
                        # 存入本地缓存，便于后续复用
                        try:
                            self._headless_cache_set(link, {'title': title, 'url': link, 'content': content_text, 'rich_content': is_rich})
                        except Exception:
                            pass
                        # 避免短时间内大量导航被封锁
                        time.sleep(random.uniform(0.3, 1.0))
                    except Exception as e:
                        logger.debug(f"[headless-deep] article fetch failed {link} -> {e}")
                        continue
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[headless] error: {e}")
        return results

    def _should_run_headless(self) -> bool:
        """根据系统负载与环境变量决定是否运行 headless。

        优先尝试使用 psutil 检测 CPU 利用率；若 psutil 不可用，则依据环境变量 `DIRECT_API_DISABLE_HEADLESS_ON_HIGH_LOAD` 和
        可选模拟负载标志 `DIRECT_API_SIMULATED_HIGH_LOAD` 做出决定。
        """
        try:
            import psutil
            thresh = int(os.getenv('DIRECT_API_HEADLESS_CPU_THRESH', '75'))
            cpu = psutil.cpu_percent(interval=0.5)
            if cpu >= thresh:
                logger.debug(f"[headless-load] skipping headless due to cpu {cpu}% >= {thresh}%")
                return False
            return True
        except Exception:
            # 回退到环境变量控制：若设置了 DIRECT_API_DISABLE_HEADLESS_ON_HIGH_LOAD=1 并且模拟负载标志为1，则跳过
            if os.getenv('DIRECT_API_DISABLE_HEADLESS_ON_HIGH_LOAD', '0') == '1' and os.getenv('DIRECT_API_SIMULATED_HIGH_LOAD', '0') == '1':
                logger.debug('[headless-load] simulated high load, skipping headless')
                return False
            return True
    
    # ============ 聚合查询 ============
    def fetch_all_sources(self, stock_code: str = '', stock_name: str = '', industry: str = '', limit: int = 15) -> List[Dict[str, Any]]:
        """从所有可用信源获取新闻
        
        并行查询多个信源，合并去重返回
        """
        all_results = []
        seen_urls = set()

        # Configurable concurrency and timeouts
        headless_enabled = os.getenv('DIRECT_API_USE_HEADLESS', '0') == '1'
        headless_concurrency = int(os.getenv('DIRECT_API_HEADLESS_CONCURRENCY', '1'))
        headless_timeout = int(os.getenv('DIRECT_API_HEADLESS_TIMEOUT', '12'))
        max_workers = int(os.getenv('DIRECT_API_MAX_WORKERS', '4'))

        # 优先运行轻量级抓取器（HTML/API），使用主线程池
        lightweight_workers = max(2, max_workers - (headless_concurrency if headless_enabled else 0))
        light_tasks = []

        # 股票相关（轻量）
        if stock_code:
            light_tasks.append(('eastmoney_api', lambda: self.fetch_eastmoney_stock_news(stock_code, limit)))
            light_tasks.append(('sina_api', lambda: self.fetch_sina_stock_news(stock_code, limit)))

        # 行业相关
        if industry:
            light_tasks.append(('eastmoney_industry', lambda: self.fetch_eastmoney_industry_news(industry, limit)))

        # 通用快讯与抓取器
        light_tasks.append(('tonghuashun', lambda: self.fetch_tonghuashun_news(stock_name or stock_code, limit)))
        light_tasks.append(('cls', lambda: self.fetch_cls_news(stock_name or '', limit)))
        light_tasks.append(('hexun', lambda: self.fetch_hexun_news('', limit // 2)))
        light_tasks.append(('ifeng', lambda: self.fetch_ifeng_news(stock_name or '', limit // 2)))
        light_tasks.append(('163', lambda: self.fetch_163_news(stock_name or '', limit // 2)))
        light_tasks.append(('21jingji', lambda: self.fetch_21jingji_news(stock_name or '', limit // 3)))

        # 可选 akshare 作为轻量任务
        if os.getenv('DIRECT_API_USE_AKSHARE', '0') == '1':
            light_tasks.append(('akshare', lambda: self.fetch_eastmoney_via_akshare(stock_code, limit // 2)))

        # 运行轻量任务并收集结果
        with ThreadPoolExecutor(max_workers=lightweight_workers) as executor:
            fut_map = {executor.submit(fn): name for name, fn in light_tasks}
            try:
                for future in as_completed(fut_map, timeout=40):
                    try:
                        items = future.result(timeout=20)
                        if items:
                            for item in items:
                                url = item.get('url', '')
                                if url and url not in seen_urls:
                                    seen_urls.add(url)
                                    all_results.append(item)
                    except Exception as e:
                        logger.debug(f"[direct-api] light future error: {e}")
            except Exception as e:
                logger.debug(f"[direct-api] light tasks collection error: {e}")

        # 如果启用了 headless，则单独运行深度渲染抓取，限制并发和超时
        if headless_enabled and stock_code:
            try:
                from concurrent.futures import ThreadPoolExecutor as _TPE
                with _TPE(max_workers=max(1, headless_concurrency)) as h_exec:
                    h_future = h_exec.submit(self.fetch_eastmoney_via_headless, stock_code, limit // 2)
                    try:
                        items = h_future.result(timeout=headless_timeout)
                        if items:
                            for item in items:
                                url = item.get('url', '')
                                if url and url not in seen_urls:
                                    seen_urls.add(url)
                                    all_results.append(item)
                    except Exception as e:
                        logger.debug(f"[direct-api] headless future error: {e}")
            except Exception as e:
                logger.debug(f"[direct-api] headless executor error: {e}")
        
        # 按时间排序（如果有的话）
        def sort_key(x):
            # 综合排序：优先级 + rich_content 标志 -> 有效发布时间 -> 内容长度
            pr = self._source_priority.get(x.get('source', ''), 0)
            # rich_content 提升权重
            rich = 1 if x.get('rich_content') else 0
            pub = x.get('published_at', '')
            pub_dt = datetime.min
            if pub:
                try:
                    pub_dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                except Exception:
                    pub_dt = datetime.min
            content_len = len((x.get('content') or '').strip())
            # 返回元组，sort reverse=True 会按 (priority+rich, time, content_len) 降序
            return (pr + rich, pub_dt, content_len)

        all_results.sort(key=sort_key, reverse=True)
        return all_results[:limit]


# 全局实例
_direct_api_instance: Optional[DirectNewsAPI] = None


def get_direct_api() -> DirectNewsAPI:
    """获取DirectNewsAPI单例"""
    global _direct_api_instance
    if _direct_api_instance is None:
        _direct_api_instance = DirectNewsAPI()
    return _direct_api_instance


def fetch_news_direct(stock_code: str = '', stock_name: str = '', industry: str = '', limit: int = 15) -> List[Dict[str, Any]]:
    """便捷函数：直接获取新闻（绕过SearXNG）
    
    Args:
        stock_code: 股票代码（如 '000001.SZ'）
        stock_name: 股票名称（如 '平安银行'）
        industry: 行业名称（如 '金融'）
        limit: 返回条数上限
    
    Returns:
        新闻列表
    """
    if not DIRECT_API_ENABLED:
        return []
    
    api = get_direct_api()
    return api.fetch_all_sources(stock_code, stock_name, industry, limit)


# 测试
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    api = DirectNewsAPI()
    
    print("=== 东方财富股票新闻 ===")
    news = api.fetch_eastmoney_stock_news('000001.SZ', 5)
    for n in news:
        print(f"  - {n['title'][:50]}...")
    
    print("\n=== 同花顺快讯 ===")
    news = api.fetch_tonghuashun_news('', 5)
    for n in news:
        print(f"  - {n['title'][:50]}...")
    
    print("\n=== 财联社电报 ===")
    news = api.fetch_cls_news('', 5)
    for n in news:
        print(f"  - {n['title'][:50]}...")
    
    print("\n=== 聚合查询 ===")
    all_news = api.fetch_all_sources('000001.SZ', '平安银行', '金融', 10)
    print(f"共获取 {len(all_news)} 条新闻")
    for n in all_news[:5]:
        print(f"  - [{n['source_name']}] {n['title'][:40]}...")
