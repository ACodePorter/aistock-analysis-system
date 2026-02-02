"""
多源财经新闻采集器 - 直接抓取可靠的财经网站

支持的信源：
1. 东方财富 (eastmoney) - 个股新闻、公告
2. 新浪财经 (sina finance) - 个股新闻、研报
3. 同花顺 (10jqka) - 个股资讯
4. 雪球 (xueqiu) - 个股讨论、新闻
5. 巨潮资讯 (cninfo) - 公告原文
6. 证券时报 (stcn) - 财经新闻

特点：
- 直接 HTTP 抓取，不依赖第三方库的不稳定接口
- 支持并发采集
- 自动重试和错误处理
- 统一输出格式
"""

import asyncio
import httpx
import logging
import json
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote

try:
    import trafilatura
except ImportError:
    trafilatura = None

logger = logging.getLogger(__name__)


class MultiSourceCollector:
    """多源财经新闻采集器"""

    # 常用 User-Agent
    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

    def __init__(self, max_concurrent: int = 5, timeout: float = 15.0):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    'User-Agent': self.UA,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate',
                },
                follow_redirects=True
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _normalize_symbol(self, symbol: str) -> Dict[str, str]:
        """将 symbol 标准化为各平台需要的格式"""
        s = symbol.strip().upper()
        # 去掉后缀
        code = re.sub(r'\.(SH|SZ|SHA|SZA|XSHG|XSHE)$', '', s, flags=re.IGNORECASE)
        code = re.sub(r'^(SH|SZ)', '', code, flags=re.IGNORECASE)

        # 判断交易所
        if code.startswith('6') or code.startswith('9'):
            exchange = 'sh'
            suffix = 'SH'
        else:
            exchange = 'sz'
            suffix = 'SZ'

        return {
            'code': code,
            'exchange': exchange,
            'suffix': suffix,
            'full': f"{code}.{suffix}",
            'eastmoney': f"{exchange}{code}",
            'sina': f"{exchange}{code}",
            'xueqiu': f"{suffix}{code}",
        }

    async def _fetch_with_retry(self, url: str, method: str = 'GET',
                                 data: Optional[Dict] = None,
                                 headers: Optional[Dict] = None,
                                 retries: int = 2) -> Optional[httpx.Response]:
        """带重试的 HTTP 请求"""
        client = await self._get_client()
        last_err = None
        for i in range(retries + 1):
            try:
                async with self._sem:
                    if method.upper() == 'POST':
                        resp = await client.post(url, data=data, headers=headers)
                    else:
                        resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        return resp
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.5 * (i + 1))
        if last_err:
            logger.debug(f"Fetch failed after retries: {url} - {last_err}")
        return None

    # ===================== 东方财富 =====================

    async def fetch_eastmoney_news(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        东方财富个股新闻 - 多 API 尝试
        """
        out = []
        sym = self._normalize_symbol(symbol)
        code = sym['code']
        market = 0 if sym['exchange'] == 'sz' else 1  # 0=深, 1=沪

        # API 1: 个股新闻 datacenter
        try:
            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                'reportName': 'RPTA_WEB_STOCKNEWS',
                'columns': 'ALL',
                'filter': f'(SECURITY_CODE="{code}")',
                'pageNumber': 1,
                'pageSize': limit,
                'sortColumns': 'NOTICE_DATE',
                'sortTypes': -1,
                'source': 'WEB',
                'client': 'WEB',
            }
            client = await self._get_client()
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('result', {}).get('data', []) or []
                for it in items[:limit]:
                    title = it.get('TITLE', '') or it.get('ART_TITLE', '')
                    news_url = it.get('ART_URL', '') or it.get('URL', '')
                    pub_time = it.get('NOTICE_DATE', '') or it.get('PUB_DATE', '')
                    summary = it.get('CONTENT', '') or it.get('DIGEST', '') or ''
                    if title:
                        out.append({
                            'title': title.strip(),
                            'url': news_url,
                            'published': pub_time,
                            'summary': summary[:500],
                            'source': 'eastmoney',
                            'symbol': symbol,
                        })
        except Exception as e:
            logger.debug(f"eastmoney datacenter error: {e}")

        # API 2: 股吧讨论帖 (HTML 解析)
        if len(out) < limit:
            try:
                guba_url = f"https://guba.eastmoney.com/list,{code}.html"
                resp = await self._fetch_with_retry(guba_url)
                if resp:
                    soup = BeautifulSoup(resp.text, 'lxml')
                    # 查找所有帖子
                    for row in soup.select('.listitem, .articleh, .normal_post'):
                        # 找标题
                        title_span = row.select_one('.l3 a, span.l3 a, .title a, .post-title a')
                        if title_span:
                            title = title_span.get_text(strip=True)
                            href = title_span.get('href', '')
                            if href and not href.startswith('http'):
                                href = f"https://guba.eastmoney.com{href}"
                            # 找发帖时间
                            time_span = row.select_one('.l6, .update, .pub_time')
                            pub_time = time_span.get_text(strip=True) if time_span else ''
                            # 过滤太短或无意义的标题
                            if title and len(title) > 10 and len(out) < limit:
                                out.append({
                                    'title': title,
                                    'url': href,
                                    'published': pub_time,
                                    'summary': '',
                                    'source': 'eastmoney_guba',
                                    'symbol': symbol,
                                })
            except Exception as e:
                logger.debug(f"eastmoney guba error: {e}")

        # API 3: 研报
        if len(out) < 8:
            try:
                url = "https://reportapi.eastmoney.com/report/list"
                params = {
                    'industryCode': '*',
                    'pageNo': 1,
                    'pageSize': min(limit, 20),
                    'stockCode': code,
                    'stockPoolCode': '*',
                }
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get('data', []) or []
                    for it in items[:limit]:
                        title = it.get('title', '')
                        if title and len(out) < limit:
                            report_url = f"https://data.eastmoney.com/report/info/{it.get('infoCode', '')}.html"
                            out.append({
                                'title': title.strip(),
                                'url': report_url,
                                'published': it.get('publishDate', ''),
                                'summary': it.get('stockName', '') + ' - ' + it.get('orgSName', ''),
                                'source': 'eastmoney_report',
                                'symbol': symbol,
                            })
            except Exception as e:
                logger.debug(f"eastmoney report error: {e}")

        # 备用：股吧讨论帖 - 改进解析
        if len(out) < 5:
            try:
                guba_url = f"https://guba.eastmoney.com/list,{code}.html"
                resp = await self._fetch_with_retry(guba_url)
                if resp:
                    soup = BeautifulSoup(resp.text, 'lxml')
                    # 查找所有帖子行
                    rows = soup.select('div.listitem, tr.listitem, div.articleh')
                    for row in rows:
                        # 寻找标题链接
                        title_a = row.select_one('a[href*="/news,"], a[href*="guba.eastmoney.com"]')
                        if not title_a:
                            # 尝试更宽泛的选择器
                            for a in row.select('a'):
                                href = a.get('href', '')
                                text = a.get_text(strip=True)
                                if text and len(text) > 10 and ('news' in href or 'guba' in href):
                                    title_a = a
                                    break
                        if title_a:
                            title = title_a.get_text(strip=True)
                            href = title_a.get('href', '')
                            if href and not href.startswith('http'):
                                href = urljoin('https://guba.eastmoney.com', href)
                            # 过滤太短的标题和导航链接
                            if title and len(title) > 8 and len(out) < limit:
                                out.append({
                                    'title': title,
                                    'url': href,
                                    'published': None,
                                    'summary': '',
                                    'source': 'eastmoney_guba',
                                    'symbol': symbol,
                                })
            except Exception as e:
                logger.debug(f"eastmoney guba error: {e}")
            except Exception as e:
                logger.debug(f"eastmoney guba error: {e}")

        return out[:limit]

    async def fetch_eastmoney_announcements(self, symbol: str, limit: int = 15) -> List[Dict[str, Any]]:
        """东方财富公告列表 - 使用新版 API"""
        out = []
        sym = self._normalize_symbol(symbol)
        code = sym['code']

        # 使用新版公告 API (np-anotice-stock)
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            'sr': -1,
            'page_size': limit,
            'page_index': 1,
            'ann_type': 'A',
            'stock_list': code,
            'f_node': '0',
            's_node': '0',
        }
        try:
            client = await self._get_client()
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('data', {}).get('list', []) or []
                for it in items[:limit]:
                    title = it.get('title', '').strip()
                    art_code = it.get('art_code', '')
                    ann_url = f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html" if art_code else ''
                    pub_time = it.get('notice_date', '')
                    detected_pdf = False
                    # try to detect direct PDF link in detail page (will be fast for small pages)
                    if ann_url:
                        try:
                            client = await self._get_client()
                            resp = await client.get(ann_url)
                            if resp and resp.status_code == 200:
                                soup = BeautifulSoup(resp.text, 'lxml')
                                # look for direct links to pdf
                                a_pdf = soup.find('a', href=lambda x: x and x.lower().endswith('.pdf'))
                                if a_pdf:
                                    href = a_pdf.get('href')
                                    if href and not href.startswith('http'):
                                        href = urljoin('https://data.eastmoney.com', href)
                                    ann_url = href
                                    detected_pdf = True
                                # look for iframe embedding pdf
                                if not detected_pdf:
                                    iframe = soup.find('iframe', src=lambda x: x and '.pdf' in x.lower())
                                    if iframe:
                                        src = iframe.get('src')
                                        if src and not src.startswith('http'):
                                            src = urljoin('https://data.eastmoney.com', src)
                                        ann_url = src
                                        detected_pdf = True
                                # try to find JS-embedded adjunct url (common pattern)
                                if not detected_pdf:
                                    # search for patterns like "adjunctUrl" or "attachment"
                                    import re
                                    m = re.search(r"adjunctUrl\s*[:=]\s*['\"](https?:\\?/\\?/[^'\"]+\.pdf)['\"]", resp.text)
                                    if m:
                                        href = m.group(1).replace('\\/', '/')
                                        ann_url = href
                                        detected_pdf = True
                        except Exception:
                            # ignore detection errors, fall back to detail page
                            detected_pdf = False
                    if title:
                        out.append({
                            'title': title,
                            'url': ann_url,
                            'published': pub_time,
                            'summary': it.get('columns', [{}])[0].get('column_name', '') if it.get('columns') else '',
                            'source': 'eastmoney_ann',
                            'symbol': symbol,
                            'is_pdf': detected_pdf or (ann_url.lower().endswith('.pdf') if ann_url else False),
                        })
        except Exception as e:
            logger.debug(f"eastmoney announcements new api error: {e}")

        # 如果新 API 失败，尝试旧 API
        if len(out) < 3:
            try:
                url2 = f"https://data.eastmoney.com/notices/getdata.ashx"
                params2 = {
                    'StockCode': code,
                    'CodeType': 1,
                    'PageIndex': 1,
                    'PageSize': limit,
                    'rt': int(time.time() * 1000),
                }
                resp = await client.get(url2, params=params2)
                if resp.status_code == 200:
                    text = resp.text.strip()
                    match = re.search(r'var\s+\w+\s*=\s*(\{.*\})', text, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        items = data.get('data', []) or []
                        for it in items[:limit]:
                            title = it.get('NOTICETITLE', '').strip()
                            ann_url = it.get('Url', '') or ''
                            if not ann_url and it.get('INFOCODE'):
                                ann_url = f"https://data.eastmoney.com/notices/detail/{code}/{it['INFOCODE']}.html"
                            pub_time = it.get('NOTICEDATE', '')
                            if title and len(out) < limit:
                                out.append({
                                    'title': title,
                                    'url': ann_url,
                                    'published': pub_time,
                                    'summary': '',
                                    'source': 'eastmoney_ann',
                                    'symbol': symbol,
                                    'is_pdf': ann_url.lower().endswith('.pdf') if ann_url else False,
                                })
            except Exception as e:
                logger.debug(f"eastmoney announcements old api error: {e}")

        return out[:limit]

    # ===================== 新浪财经 =====================

    async def fetch_sina_news(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """新浪财经个股新闻 - 使用 API"""
        out = []
        sym = self._normalize_symbol(symbol)
        code = sym['code']

        # 新浪个股新闻 JSON API
        try:
            url = f"https://feed.mix.sina.com.cn/api/roll/get"
            params = {
                'pageid': '155',
                'lid': '2516',
                'num': limit,
                'k': code,
                'page': 1,
            }
            client = await self._get_client()
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('result', {}).get('data', []) or []
                for it in items[:limit]:
                    title = it.get('title', '').strip()
                    news_url = it.get('url', '')
                    pub_time = it.get('ctime', '') or it.get('mtime', '')
                    if isinstance(pub_time, int):
                        pub_time = datetime.fromtimestamp(pub_time).isoformat()
                    intro = it.get('intro', '') or it.get('summary', '')
                    if title:
                        out.append({
                            'title': title,
                            'url': news_url,
                            'published': pub_time,
                            'summary': intro[:500] if intro else '',
                            'source': 'sina',
                            'symbol': symbol,
                        })
        except Exception as e:
            logger.debug(f"sina api error: {e}")

        # 备用：新浪股票搜索
        if len(out) < 5:
            try:
                search_url = f"https://cre.mix.sina.com.cn/api/v3/get"
                params = {
                    'format': 'json',
                    'cateid': '1o',
                    'cre': 'financepagepc',
                    'mod': 'f',
                    'statics': '1',
                    'merge': '3',
                    'q': code,
                    'top': '0',
                    'fields': 'url,title,intro,ctime',
                    'length': min(limit, 30),
                }
                resp = await self._fetch_with_retry(search_url + '?' + '&'.join(f"{k}={v}" for k, v in params.items()))
                if resp:
                    data = resp.json()
                    items = data.get('data', []) or []
                    for it in items:
                        title = it.get('title', '').strip()
                        news_url = it.get('url', '')
                        if title and news_url and len(out) < limit:
                            out.append({
                                'title': title,
                                'url': news_url,
                                'published': it.get('ctime'),
                                'summary': it.get('intro', '')[:500],
                                'source': 'sina_search',
                                'symbol': symbol,
                            })
            except Exception as e:
                logger.debug(f"sina search error: {e}")

        return out[:limit]

    # ===================== 同花顺 =====================

    async def fetch_ths_news(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """同花顺个股新闻 - 使用多个 API 尝试"""
        out = []
        sym = self._normalize_symbol(symbol)
        code = sym['code']
        client = await self._get_client()

        # API 1: PC 端个股新闻页面 (GBK 编码)
        try:
            url = f"https://stockpage.10jqka.com.cn/{code}/news/"
            resp = await self._fetch_with_retry(url, headers={'Referer': 'https://stockpage.10jqka.com.cn/'})
            if resp:
                # 同花顺使用 GBK 编码
                try:
                    text = resp.content.decode('gbk', errors='ignore')
                except:
                    text = resp.text
                soup = BeautifulSoup(text, 'lxml')
                for item in soup.select('.news_list li, .news-list-item, .main-text li, .bd li'):
                    a = item.select_one('a')
                    if a:
                        title = a.get_text(strip=True)
                        href = a.get('href', '')
                        if href and not href.startswith('http'):
                            href = f"https://stockpage.10jqka.com.cn{href}"
                        time_el = item.select_one('.arc-time, .time, span')
                        pub_time = time_el.get_text(strip=True) if time_el else ''
                        # 过滤导航链接和太短的标题
                        if title and len(title) > 5 and not href.endswith('javascript:void(0)') and len(out) < limit:
                            out.append({
                                'title': title,
                                'url': href,
                                'published': pub_time,
                                'summary': '',
                                'source': 'ths',
                                'symbol': symbol,
                            })
        except Exception as e:
            logger.debug(f"ths pc page error: {e}")

        # API 2: 问财 搜索 API
        if len(out) < 5:
            try:
                url = "http://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data"
                payload = {
                    'question': f'{code} 最新公告新闻',
                    'perpage': limit,
                    'page': 1,
                    'secondary_intent': 'stock',
                    'log_info': '{"input_type":"typewrite"}',
                }
                resp = await client.post(url, json=payload, headers={
                    'Content-Type': 'application/json',
                    'User-Agent': self.UA,
                })
                if resp.status_code == 200:
                    data = resp.json()
                    answer_data = data.get('data', {}).get('answer', [])
                    for ans in answer_data:
                        txt = ans.get('txt', [])
                        for t in txt:
                            content = t.get('content', {})
                            # 解析表格数据
                            if isinstance(content, dict) and content.get('components'):
                                for comp in content.get('components', []):
                                    if comp.get('data', {}).get('datas'):
                                        for row in comp['data']['datas'][:limit]:
                                            title = row.get('股票简称', '') or row.get('公告标题', '')
                                            if title and len(out) < limit:
                                                out.append({
                                                    'title': str(title),
                                                    'url': '',
                                                    'published': row.get('公告日期', ''),
                                                    'summary': '',
                                                    'source': 'ths_wencai',
                                                    'symbol': symbol,
                                                })
            except Exception as e:
                logger.debug(f"ths wencai error: {e}")

        # API 3: 同花顺个股公告页面 (更可靠)
        if len(out) < 5:
            try:
                url = f"https://stockpage.10jqka.com.cn/{code}/operate/gsgg/"
                resp = await self._fetch_with_retry(url, headers={'Referer': 'https://stockpage.10jqka.com.cn/'})
                if resp:
                    try:
                        text = resp.content.decode('gbk', errors='ignore')
                    except:
                        text = resp.text
                    soup = BeautifulSoup(text, 'lxml')
                    for item in soup.select('.bd li, .m-table tbody tr, .gg_list li'):
                        a = item.select_one('a')
                        if a:
                            title = a.get_text(strip=True)
                            href = a.get('href', '')
                            # 严格过滤：标题要有意义、不是导航、不是JavaScript
                            is_valid = (
                                title and 
                                len(title) > 8 and 
                                not title.startswith('更多') and
                                '###' not in href and
                                'javascript' not in href.lower() and
                                not title.endswith('动态') and
                                not title.endswith('公告') and
                                not title.endswith('研究') and
                                not title.endswith('分析') and
                                not title.endswith('结构')
                            )
                            if is_valid and len(out) < limit:
                                full_url = href if href.startswith('http') else f"https://stockpage.10jqka.com.cn{href}"
                                out.append({
                                    'title': title,
                                    'url': full_url,
                                    'published': None,
                                    'summary': '',
                                    'source': 'ths_gsgg',
                                    'symbol': symbol,
                                })
            except Exception as e:
                logger.debug(f"ths gsgg error: {e}")

        return out[:limit]

    # ===================== 雪球 =====================

    async def fetch_xueqiu_news(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """雪球个股新闻和讨论"""
        out = []
        sym = self._normalize_symbol(symbol)
        xq_symbol = sym['xueqiu']

        # 雪球需要先获取 cookie
        try:
            client = await self._get_client()
            # 访问主页获取 cookie
            await client.get('https://xueqiu.com/')

            # 个股新闻 API
            url = f"https://xueqiu.com/statuses/stock_timeline.json"
            params = {
                'symbol': xq_symbol,
                'count': limit,
                'source': 'all',
            }
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('list', []) or []
                for it in items[:limit]:
                    title = it.get('title', '') or it.get('description', '')[:80]
                    text = it.get('text', '') or it.get('description', '')
                    # 清理 HTML
                    if '<' in text:
                        soup = BeautifulSoup(text, 'lxml')
                        text = soup.get_text(strip=True)
                    created = it.get('created_at', '')
                    if isinstance(created, int):
                        created = datetime.fromtimestamp(created / 1000).isoformat()
                    post_id = it.get('id', '')
                    post_url = f"https://xueqiu.com/{it.get('user_id', '')}/{post_id}" if post_id else ''
                    if title or text:
                        out.append({
                            'title': title[:100] if title else text[:100],
                            'url': post_url,
                            'published': created,
                            'summary': text[:500] if text else '',
                            'source': 'xueqiu',
                            'symbol': symbol,
                        })
        except Exception as e:
            logger.debug(f"xueqiu news error: {e}")

        return out[:limit]

    # ===================== 巨潮资讯 =====================

    async def fetch_cninfo_announcements(self, symbol: str, limit: int = 15) -> List[Dict[str, Any]]:
        """巨潮资讯公告 - 使用更可靠的参数格式"""
        out = []
        sym = self._normalize_symbol(symbol)
        code = sym['code']

        url = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
        # 使用正确的参数格式：不含逗号的 stock 格式
        payload = {
            'pageNum': 1,
            'pageSize': limit,
            'column': 'szse' if sym['exchange'] == 'sz' else 'sse',
            'tabName': 'fulltext',
            'stock': code,  # 只用股票代码
            'searchkey': '',
            'seDate': '',
            'category': '',
            'secid': '',
            'sortName': '',
            'sortType': '',
            'isHLtitle': 'true',
        }
        try:
            client = await self._get_client()
            # 直接发请求避免 retry wrapper 的问题
            resp = await client.post(url, data=payload)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('announcements', []) or []
                for it in items[:limit]:
                    title = it.get('announcementTitle', '').strip()
                    adj_url = it.get('adjunctUrl', '')
                    if adj_url:
                        if not adj_url.startswith('http'):
                            adj_url = f"https://www.cninfo.com.cn/{adj_url}"
                    pub_time = it.get('announcementTime')
                    if isinstance(pub_time, (int, float)):
                        pub_time = datetime.fromtimestamp(pub_time / 1000).isoformat()
                    if title:
                        out.append({
                            'title': title,
                            'url': adj_url,
                            'published': pub_time,
                            'summary': '',
                            'source': 'cninfo',
                            'symbol': symbol,
                            'is_pdf': adj_url.lower().endswith('.pdf') if adj_url else False,
                        })
        except Exception as e:
            logger.debug(f"cninfo error: {e}")

        return out[:limit]

    # ===================== 财经门户聚合 =====================

    async def fetch_cls_telegraph(self, limit: int = 20) -> List[Dict[str, Any]]:
        """财联社电报快讯"""
        out = []
        try:
            # 直接抓取电报页面
            url = 'https://www.cls.cn/telegraph'
            client = await self._get_client()
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'lxml')
                # 提取 __NUXT__ 数据
                scripts = soup.select('script')
                for script in scripts:
                    text = script.get_text()
                    if 'window.__NUXT__' in text:
                        # 解析 JS 对象
                        import re
                        match = re.search(r'rollList:\s*\[(.*?)\]', text, re.DOTALL)
                        if match:
                            # 简化解析
                            pass
                # 回退到 HTML 解析
                for item in soup.select('[class*="telegraph"]'):
                    content = item.get_text(strip=True)
                    if content and len(content) > 10 and len(out) < limit:
                        out.append({
                            'title': content[:100],
                            'url': 'https://www.cls.cn/telegraph',
                            'published': None,
                            'summary': content[:500],
                            'source': 'cls',
                            'symbol': None,
                        })
        except Exception as e:
            logger.debug(f"cls telegraph error: {e}")

        return out[:limit]

    async def fetch_stcn_news(self, limit: int = 20) -> List[Dict[str, Any]]:
        """证券时报快讯"""
        out = []
        try:
            url = 'https://kuaixun.stcn.com/'
            resp = await self._fetch_with_retry(url)
            if resp:
                soup = BeautifulSoup(resp.text, 'lxml')
                for item in soup.select('.kuaixun-list li, .news-item, article'):
                    a = item.select_one('a')
                    if a:
                        title = a.get_text(strip=True)
                        href = a.get('href', '')
                        if href and not href.startswith('http'):
                            href = urljoin('https://kuaixun.stcn.com', href)
                        time_el = item.select_one('.time, time, .date')
                        pub_time = time_el.get_text(strip=True) if time_el else ''
                        if title and len(out) < limit:
                            out.append({
                                'title': title,
                                'url': href,
                                'published': pub_time,
                                'summary': '',
                                'source': 'stcn',
                                'symbol': None,
                            })
        except Exception as e:
            logger.debug(f"stcn error: {e}")
        return out[:limit]

    async def fetch_general_finance_news(self, keywords: Optional[List[str]] = None, limit: int = 30) -> List[Dict[str, Any]]:
        """获取通用财经新闻（不针对特定股票）"""
        out = []
        keywords = keywords or ['A股', '股市', '上市公司']

        # 证券时报
        try:
            url = 'https://www.stcn.com/kuaixun/'
            resp = await self._fetch_with_retry(url)
            if resp:
                soup = BeautifulSoup(resp.text, 'lxml')
                for item in soup.select('.news_list li, .kuaixun_list li'):
                    a = item.select_one('a')
                    if a:
                        title = a.get_text(strip=True)
                        href = a.get('href', '')
                        if href and not href.startswith('http'):
                            href = urljoin('https://www.stcn.com', href)
                        if title and len(out) < limit:
                            out.append({
                                'title': title,
                                'url': href,
                                'published': None,
                                'summary': '',
                                'source': 'stcn',
                                'symbol': None,
                            })
        except Exception as e:
            logger.debug(f"stcn error: {e}")

        # 财联社快讯
        try:
            url = 'https://www.cls.cn/telegraph'
            resp = await self._fetch_with_retry(url)
            if resp:
                soup = BeautifulSoup(resp.text, 'lxml')
                for item in soup.select('.telegraph-list-item, .telegraph-content-box'):
                    content_el = item.select_one('.telegraph-content, .content')
                    if content_el:
                        text = content_el.get_text(strip=True)
                        if text and len(out) < limit:
                            out.append({
                                'title': text[:100],
                                'url': '',
                                'published': None,
                                'summary': text,
                                'source': 'cls',
                                'symbol': None,
                            })
        except Exception as e:
            logger.debug(f"cls error: {e}")

        return out[:limit]

    # ===================== 统一入口 =====================

    async def collect_stock_news(self, symbol: str, limit_per_source: int = 10) -> List[Dict[str, Any]]:
        """
        并行从多个源采集个股新闻
        返回去重后的结果
        """
        tasks = [
            self.fetch_eastmoney_news(symbol, limit_per_source),
            self.fetch_eastmoney_announcements(symbol, limit_per_source),
            self.fetch_sina_news(symbol, limit_per_source),
            self.fetch_ths_news(symbol, limit_per_source),
            self.fetch_xueqiu_news(symbol, limit_per_source),
            self.fetch_cninfo_announcements(symbol, limit_per_source),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        for r in results:
            if isinstance(r, list):
                all_items.extend(r)
            elif isinstance(r, Exception):
                logger.debug(f"Source error: {r}")

        # 去重（基于 title + url）
        seen = set()
        unique = []
        for item in all_items:
            key = (item.get('title', ''), item.get('url', ''))
            if key not in seen and item.get('title'):
                seen.add(key)
                unique.append(item)

        # 按发布时间排序（如果有）
        def sort_key(x):
            pub = x.get('published')
            if pub:
                try:
                    if isinstance(pub, str):
                        return pub
                except:
                    pass
            return '0000-00-00'

        unique.sort(key=sort_key, reverse=True)
        return unique

    async def batch_collect(self, symbols: List[str], limit_per_source: int = 8) -> Dict[str, List[Dict[str, Any]]]:
        """批量采集多个股票的新闻"""
        tasks = [self.collect_stock_news(s, limit_per_source) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = {}
        for s, r in zip(symbols, results):
            if isinstance(r, list):
                out[s] = r
            else:
                out[s] = []
                logger.debug(f"Batch collect error for {s}: {r}")
        return out

    async def extract_content(self, url: str) -> Optional[str]:
        """提取网页正文内容"""
        if not url:
            return None
        try:
            resp = await self._fetch_with_retry(url)
            if resp:
                html = resp.text
                # 优先使用 trafilatura
                if trafilatura:
                    content = trafilatura.extract(html)
                    if content:
                        return content[:5000]
                # 回退到 BeautifulSoup
                soup = BeautifulSoup(html, 'lxml')
                # 移除脚本和样式
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    tag.decompose()
                # 尝试找主内容区
                main = soup.select_one('article, .article, .content, .main-content, #content')
                if main:
                    return main.get_text(separator='\n', strip=True)[:5000]
                return soup.get_text(separator='\n', strip=True)[:5000]
        except Exception as e:
            logger.debug(f"Content extraction error: {e}")
        return None


# 测试入口
async def test_collector():
    collector = MultiSourceCollector()
    try:
        print("Testing multi-source collector for 000001.SZ (平安银行)...")
        results = await collector.collect_stock_news('000001.SZ', limit_per_source=5)
        print(f"\nCollected {len(results)} unique items from all sources:")
        for i, item in enumerate(results[:15], 1):
            print(f"\n{i}. [{item['source']}] {item['title'][:60]}")
            if item['url']:
                print(f"   URL: {item['url'][:80]}")
            if item['published']:
                print(f"   Published: {item['published']}")

        print("\n\n--- General finance news ---")
        general = await collector.fetch_general_finance_news(limit=10)
        for i, item in enumerate(general[:5], 1):
            print(f"{i}. [{item['source']}] {item['title'][:60]}")

    finally:
        await collector.close()


if __name__ == '__main__':
    asyncio.run(test_collector())
