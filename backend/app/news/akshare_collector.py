"""
AKShare 数据采集器封装（公告 / 快讯 / 行业）

特点：
- 使用线程池执行阻塞的 akshare 调用（通过 asyncio loop.run_in_executor）
- 支持批量拉取、重试、简单限速（防止短时并发将源压垮）
- 统一输出字段：title, url, published, source, summary, symbol
"""
import asyncio
import time
from typing import List, Dict, Any, Optional

import akshare as ak
import logging
import os
import json
import traceback
from datetime import datetime
import httpx
from dateutil import parser as date_parser
import pathlib


class AKShareCollector:
    def __init__(self, max_concurrent: int = 3, min_interval_seconds: float = 0.5, retry: int = 2):
        # 控制并发和速率：并发数 + 最小调用间隔
        self._sem = asyncio.Semaphore(max_concurrent)
        self._min_interval = float(min_interval_seconds)
        self._last_call = 0.0
        self._retry = int(retry)

    async def _run_blocking(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        # simple rate limiter: ensure at least _min_interval between calls
        now = time.time()
        wait = max(0, self._min_interval - (now - self._last_call))
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with self._sem:
                res = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        finally:
            self._last_call = time.time()
        return res

    async def _with_retries(self, func, *args, **kwargs):
        last_exc: Optional[Exception] = None
        for attempt in range(self._retry + 1):
            try:
                return await self._run_blocking(func, *args, **kwargs)
            except Exception as e:
                last_exc = e
                await asyncio.sleep(0.5 * (attempt + 1))
        raise last_exc

    async def _safe_ak_call(self, func, *args, **kwargs):
        """Call an akshare function safely: catch JSONDecodeError/KeyError and record error, return None on parse problems."""
        try:
            res = await self._with_retries(func, *args, **kwargs)
            # common akshare helpers sometimes return empty strings or raw text — normalize
            if res is None:
                return None
            # if it's a string, try to parse JSON safely
            if isinstance(res, str):
                s = res.strip()
                if not s:
                    return None
                try:
                    return json.loads(s)
                except Exception:
                    # not JSON; leave as-is and let _records_from_ak_result handle
                    return res
            return res
        except json.JSONDecodeError as jde:
            try:
                self._record_ak_error(getattr(func, '__name__', str(func)), args[0] if args else '', f'JSONDecodeError: {str(jde)}')
            except Exception:
                logging.debug('Failed to write akshare json error')
            return None
        except KeyError as ke:
            try:
                self._record_ak_error(getattr(func, '__name__', str(func)), args[0] if args else '', f'KeyError: {str(ke)}')
            except Exception:
                logging.debug('Failed to write akshare keyerror')
            return None
        except Exception:
            # bubble up other exceptions to calling code which already logs
            raise

    def _normalize_df_records(self, records: List[Dict[str, Any]], default_symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for r in records:
            title = r.get('title') or r.get('标题') or r.get('news_title') or ''
            url = r.get('url') or r.get('link') or r.get('网页链接') or r.get('news_url') or ''
            published = r.get('time') or r.get('pubDate') or r.get('日期') or r.get('date') or r.get('公告日期') or None
            summary = r.get('summary') or r.get('摘要') or r.get('content') or ''
            source = r.get('source') or r.get('来源') or None
            symbol = default_symbol
            # try some common columns
            for k in ('symbol', '代码', 'stock', 'company_code'):
                if k in r and r.get(k):
                    symbol = r.get(k)
                    break

            out.append({
                'title': title,
                'url': url,
                'published': published,
                'summary': summary,
                'source': source,
                'symbol': symbol,
            })
        return out

    def _records_from_ak_result(self, obj) -> List[Dict[str, Any]]:
        """Normalize various akshare/tushare return types into list[dict]."""
        # DataFrame -> records
        try:
            import pandas as pd
            if isinstance(obj, pd.DataFrame):
                try:
                    recs = obj.to_dict('records')
                    return recs if isinstance(recs, list) else []
                except Exception:
                    # try to convert columns to strings
                    return []
        except Exception:
            pass

        # list of dicts
        if isinstance(obj, list):
            # ensure elements are dict-like
            out = []
            for it in obj:
                if isinstance(it, dict):
                    out.append(it)
                else:
                    # try to coerce tuples/lists
                    try:
                        out.append(dict(it))
                    except Exception:
                        continue
            return out

        # dict -> wrap
        if isinstance(obj, dict):
            return [obj]

        # other scalar or None
        return []

    def _candidate_symbol_formats(self, symbol: str) -> List[str]:
        """Generate likely symbol formats for AKShare queries.

        Examples:
        - 600519 -> ['600519', '600519.SH', '600519.SHA', 'sh600519']
        - 000001.SZ -> ['000001', '000001.SZ', '000001.SZ', 'sz000001']
        - keep original if non-numeric
        """
        s = (symbol or '').strip()
        if not s:
            return []
        cand = []
        # strip common separators
        base = s.replace('.', '').upper()
        # if contains letters like SH/SZ suffix, separate
        if '.' in s:
            parts = s.split('.')
            code = parts[0]
            suffix = parts[1].upper() if len(parts) > 1 else ''
            cand.append(s)
            cand.append(code)
            if suffix in ('SH', 'SHA', 'XSHG'):
                # prefer exchange-suffixed formats first
                cand.insert(0, f"{code}.SH")
                cand.insert(0, f"sh{code}")
            if suffix in ('SZ', 'SZA', 'XSHE'):
                cand.insert(0, f"{code}.SZ")
                cand.insert(0, f"sz{code}")
        else:
            cand.append(s)
            # numeric codes -> try exchange suffixes
            if s.isdigit():
                # prefer sh/sz prefixed variants first
                if s.startswith('6'):
                    cand.insert(0, f"{s}.SH")
                    cand.insert(0, f"sh{s}")
                else:
                    cand.insert(0, f"{s}.SZ")
                    cand.insert(0, f"sz{s}")
                cand.append(s)
        # dedupe preserving order
        seen = set()
        out = []
        for x in cand:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    async def get_stock_news(self, symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
        """获取个股相关的新闻/快讯（使用 ak.stock_news_em 或相关接口）"""
        try:
            # Try multiple symbol formats until we get data
            candidates = self._candidate_symbol_formats(symbol)

            # If TUSHARE_TOKEN is provided prefer tushare announcement endpoints first
            import os
            token = os.getenv('TUSHARE_TOKEN')
            if token:
                try:
                    import tushare as ts
                    pro = ts.pro_api(token)
                    pro_names = ['announcement', 'announcements', 'query_announcement', 'query_ann', 'news']
                    for cand in candidates:
                        for pname in pro_names:
                            try:
                                # use pro.query(endpoint, ...) for robustness
                                try:
                                    df = pro.query(pname, ts_code=cand)
                                except TypeError:
                                    try:
                                        df = pro.query(pname, code=cand)
                                    except TypeError:
                                        df = pro.query(pname, cand)
                                if hasattr(df, 'to_dict'):
                                    records = df.to_dict('records')[:limit]
                                    if records:
                                        logging.info(f"AKShareCollector: returned data from tushare.{pname} for {cand}")
                                        return self._normalize_df_records(records, default_symbol=symbol)
                            except Exception:
                                # ignore invalid endpoint names or permission errors
                                continue
                except Exception:
                    # fallback to akshare if tushare not usable
                    logging.debug("AKShareCollector: tushare fallback unavailable or failed")

            # akshare news functions fallback
            news_funcs = [
                'stock_news_em',
                'stock_news_main_sina',
                'stock_zh_a_news',
            ]
            for cand in candidates:
                for fname in news_funcs:
                    if hasattr(ak, fname):
                        try:
                            fn = getattr(ak, fname)
                            df = await self._safe_ak_call(fn, cand)
                            records = self._records_from_ak_result(df)[:limit]
                            if records:
                                logging.info(f"AKShareCollector: returned data from akshare.{fname} for {cand}")
                                return self._normalize_df_records(records, default_symbol=symbol)
                        except Exception:
                            # record error details for debugging
                            try:
                                err_trace = traceback.format_exc()
                                self._record_ak_error(fname, cand, err_trace)
                            except Exception:
                                logging.debug('Failed to write ak error record')
                            continue

            # final fallback: try CNInfo search (some news may be available as announcements)
            try:
                cn_recs = await self._fetch_cninfo_announcements(symbol, limit=limit)
                if cn_recs:
                    return self._normalize_df_records(cn_recs, default_symbol=symbol)
            except Exception:
                try:
                    self._record_ak_error('cninfo.fallback_news', symbol, traceback.format_exc())
                except Exception:
                    logging.debug('Failed to write cninfo fallback error')

            return []
        except Exception:
            return []

    async def get_announcements(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """获取公司公告/年报/季报等（使用 ak.stock_notice_report 或合适接口）"""
        try:
            candidates = self._candidate_symbol_formats(symbol)

            notice_funcs = ['stock_notice_report', 'stock_notice_cninfo', 'stock_notice_em']
            for cand in candidates:
                for fname in notice_funcs:
                    if hasattr(ak, fname):
                        try:
                            fn = getattr(ak, fname)
                            df = await self._safe_ak_call(fn, cand)
                            records = self._records_from_ak_result(df)[:limit]
                            if records:
                                logging.info(f"AKShareCollector: returned announcements from akshare.{fname} for {cand}")
                                return self._normalize_df_records(records, default_symbol=symbol)
                        except Exception:
                            try:
                                err_trace = traceback.format_exc()
                                self._record_ak_error(fname, cand, err_trace)
                            except Exception:
                                logging.debug('Failed to write ak error record')
                            continue

            # prefer tushare for announcements when token available
            import os
            token = os.getenv('TUSHARE_TOKEN')
            if token:
                try:
                    import tushare as ts
                    pro = ts.pro_api(token)
                    pro_names = ['announcement', 'announcements', 'query_announcement', 'query_ann']
                    for cand in candidates:
                        for pname in pro_names:
                            try:
                                try:
                                    df = pro.query(pname, ts_code=cand)
                                except TypeError:
                                    try:
                                        df = pro.query(pname, code=cand)
                                    except TypeError:
                                        df = pro.query(pname, cand)
                                if hasattr(df, 'to_dict'):
                                    records = df.to_dict('records')[:limit]
                                    if records:
                                        logging.info(f"AKShareCollector: returned announcements from tushare.{pname} for {cand}")
                                        return self._normalize_df_records(records, default_symbol=symbol)
                            except Exception:
                                try:
                                    err_trace = traceback.format_exc()
                                    self._record_ak_error(f'tushare.{pname}', cand, err_trace)
                                except Exception:
                                    logging.debug('Failed to write tushare error record')
                                continue
                except Exception:
                    logging.debug("AKShareCollector: tushare announcements unavailable or failed")

            # last-resort fallback: query CNInfo directly
            try:
                cn_recs = await self._fetch_cninfo_announcements(symbol, limit=limit)
                if cn_recs:
                    return self._normalize_df_records(cn_recs, default_symbol=symbol)
            except Exception:
                try:
                    self._record_ak_error('cninfo.fallback', symbol, traceback.format_exc())
                except Exception:
                    logging.debug('Failed to write cninfo error record')

            return []
        except Exception:
            return []

    async def get_financial_news(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取金融类聚合新闻（示例接口）"""
        try:
            df = await self._safe_ak_call(ak.stock_news_main_sina)
            records = []
            if hasattr(df, 'to_dict'):
                records = df.to_dict('records')[:limit]
            return self._normalize_df_records(records)
        except Exception:
            return []

    async def batch_get_announcements(self, symbols: List[str], per_symbol: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        """并行为多个 symbol 拉取公告（有限并发）"""
        tasks = [self.get_announcements(s, limit=per_symbol) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: Dict[str, List[Dict[str, Any]]] = {}
        for s, r in zip(symbols, results):
            if isinstance(r, Exception):
                out[s] = []
            else:
                out[s] = r
        return out

    async def batch_get_stock_news(self, symbols: List[str], per_symbol: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        tasks = [self.get_stock_news(s, limit=per_symbol) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: Dict[str, List[Dict[str, Any]]] = {}
        for s, r in zip(symbols, results):
            if isinstance(r, Exception):
                out[s] = []
            else:
                out[s] = r
        return out

    def _record_ak_error(self, func_name: str, symbol: str, trace: str) -> None:
        """Append ak/tushare error details to a JSONL file under temp/ for debugging."""
        try:
            os.makedirs('temp', exist_ok=True)
            path = os.path.join('temp', 'akshare_errors.jsonl')
            payload = {
                'ts': datetime.utcnow().isoformat() + 'Z',
                'func': func_name,
                'symbol': symbol,
                'trace': trace
            }
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            logging.debug('Failed to write akshare error to file')

    async def _fetch_cninfo_announcements(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Query CNInfo (巨潮资讯) announcement search endpoint as a final fallback.

        This attempts a POST to the public hisAnnouncement/query endpoint and
        normalizes results into a list of dicts with keys similar to AKShare outputs.
        The implementation is defensive: it tolerates JSON or HTML responses.
        """
        out: List[Dict[str, Any]] = []
        # file cache to reduce repeat CNInfo queries
        cache_dir = pathlib.Path('temp')
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / 'cninfo_cache.json'
        cache_ttl = 3600  # seconds

        try:
            if cache_path.exists():
                try:
                    with open(cache_path, 'r', encoding='utf-8') as cf:
                        cache = json.load(cf)
                except Exception:
                    cache = {}
            else:
                cache = {}
        except Exception:
            cache = {}

        try:
            entry = cache.get(symbol)
            if entry:
                ts = float(entry.get('ts', 0))
                if time.time() - ts < cache_ttl:
                    return entry.get('results', [])[:limit]
        except Exception:
            pass

        try:
            url = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
            # try multiple candidate search keys (different symbol formats) and allow empty column for broader search
            candidates = self._candidate_symbol_formats(symbol) or [symbol]
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = None
                j = None
                for cand in candidates:
                    payload = {
                        'pageNum': 1,
                        'pageSize': int(limit),
                        'column': '',
                        'tabName': 'fulltext',
                        'seDate': '',
                        'searchkey': cand,
                    }
                    try:
                        resp = await client.post(url, data=payload)
                    except Exception:
                        resp = None
                    if resp is None:
                        continue
                    text = resp.text
                    try:
                        j = resp.json()
                    except Exception:
                        j = None

                    if isinstance(j, dict):
                        # if we found announcements, proceed; otherwise try next candidate
                        found = False
                        for k in ('announcements', 'records', 'data', 'result'):
                            if k in j and isinstance(j[k], list) and j[k]:
                                found = True
                                break
                        if not found:
                            # try other values
                            for v in j.values():
                                if isinstance(v, list) and v:
                                    found = True
                                    break
                        if not found:
                            # try next candidate
                            continue
                # at this point j/text processed inside loop and we should have j for the successful candidate
                if isinstance(j, dict):
                    # look for common list fields
                    candidates = []
                    for k in ('announcements', 'records', 'data', 'result'):
                        if k in j and isinstance(j[k], list):
                            candidates = j[k]
                            break
                    if not candidates:
                        for v in j.values():
                            if isinstance(v, list):
                                candidates = v
                                break

                    for it in candidates[:limit]:
                        title = it.get('announcementTitle') or it.get('title') or it.get('公告标题') or ''
                        link = it.get('adjunctUrl') or it.get('announcementUrl') or it.get('url') or it.get('href') or ''
                        raw_date = it.get('announcementTime') or it.get('publishTime') or it.get('公告日期') or it.get('date') or None
                        published = None
                        try:
                            if raw_date is not None:
                                if isinstance(raw_date, (int, float)):
                                    # handle ms/seconds
                                    if raw_date > 1e12:
                                        published = datetime.utcfromtimestamp(raw_date / 1000).isoformat() + 'Z'
                                    elif raw_date > 1e9:
                                        published = datetime.utcfromtimestamp(raw_date / 1000).isoformat() + 'Z'
                                    else:
                                        published = datetime.utcfromtimestamp(raw_date).isoformat() + 'Z'
                                else:
                                    try:
                                        dt = date_parser.parse(str(raw_date))
                                        published = dt.isoformat() + 'Z'
                                    except Exception:
                                        published = str(raw_date)
                        except Exception:
                            published = None

                        # richer summary: prefer abstract/summary; if empty, try to fetch adjunctUrl and extract
                        summary = it.get('summary') or it.get('announcementAbstract') or it.get('公告摘要') or ''
                        sec = it.get('secCode') or it.get('stockCode') or symbol
                        # normalize adjunct/link to absolute URL (CNInfo often returns relative paths like 'finalpage/...')
                        base_cninfo = 'https://www.cninfo.com.cn'
                        url_raw = (link or '').strip()
                        if url_raw.startswith('http://') or url_raw.startswith('https://'):
                            url_abs = url_raw
                        elif url_raw:
                            # ensure leading slash
                            if url_raw.startswith('/'):
                                url_abs = base_cninfo + url_raw
                            else:
                                url_abs = base_cninfo + '/' + url_raw
                        else:
                            url_abs = ''

                        rec = {'title': title, 'url': url_abs, 'published': published, 'summary': summary, 'source': 'cninfo', 'symbol': sec}
                        out.append(rec)
                        try:
                            # if it's a PDF, mark and skip HTML extraction (PDF extraction handled separately later)
                            lower = (rec['url'] or '').lower()
                            if not rec['summary'] and rec['url'] and ('.htm' in lower or '.html' in lower or '/announcement/' in lower) and not lower.endswith('.pdf'):
                                async with httpx.AsyncClient(timeout=15.0) as subc:
                                    try:
                                        subr = await subc.get(rec['url'])
                                        html_text = subr.text
                                    except Exception:
                                        html_text = None
                                    if html_text:
                                        try:
                                            import trafilatura
                                            extracted = trafilatura.extract(html_text)
                                            if extracted:
                                                rec['summary'] = extracted[:2000]
                                        except Exception:
                                            try:
                                                from bs4 import BeautifulSoup
                                                soup2 = BeautifulSoup(html_text, 'lxml')
                                                txt = soup2.get_text(separator=' ', strip=True)
                                                rec['summary'] = txt[:2000]
                                            except Exception:
                                                pass
                            else:
                                # if it's a PDF link, flag it so caller can decide how to handle PDFs
                                if rec['url'] and lower.endswith('.pdf'):
                                    rec['is_pdf'] = True
                        except Exception:
                            pass

                    try:
                        cache[symbol] = {'ts': time.time(), 'results': out}
                        with open(cache_path, 'w', encoding='utf-8') as cf:
                            json.dump(cache, cf, ensure_ascii=False)
                    except Exception:
                        pass
                    return out

                # fallback: parse HTML to extract links
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(text, 'lxml')
                    links = soup.select('a')
                    for a in links:
                        href = a.get('href')
                        if not href:
                            continue
                        if 'cninfo' in href or '/announcement/' in href:
                            title = (a.get_text() or '').strip()
                            url_abs = href if href.startswith('http') else str(httpx.URL(url).join(href))
                            out.append({'title': title, 'url': str(url_abs), 'published': None, 'summary': '', 'source': 'cninfo', 'symbol': symbol})
                            if len(out) >= limit:
                                break
                    try:
                        cache[symbol] = {'ts': time.time(), 'results': out}
                        with open(cache_path, 'w', encoding='utf-8') as cf:
                            json.dump(cache, cf, ensure_ascii=False)
                    except Exception:
                        pass
                    return out
                except Exception:
                    return []

        except Exception:
            try:
                self._record_ak_error('cninfo.fetch', symbol, traceback.format_exc())
            except Exception:
                logging.debug('Failed to write cninfo error record')
            return []

