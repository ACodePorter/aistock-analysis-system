"""拉取 CNInfo 附件（PDF）并批量测试 `extract_text_from_pdf` 的抽取效果。
生成报告存为 `temp/pdf_sample_report.json`。
"""
import asyncio
import json
import logging
import os
import sys
import time
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('test_pdf_samples')


CNINFO_API = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'


async def fetch_cninfo_pdfs(symbol: str, limit: int = 30) -> List[str]:
    code = symbol.split('.')[0] if '.' in symbol else symbol
    payload = {
        'pageNum': 1,
        'pageSize': limit,
        'column': 'szse' if symbol.upper().endswith('.SZ') else 'sse',
        'tabName': 'fulltext',
        'stock': code,
        'searchkey': '',
        'seDate': '',
        'category': '',
        'secid': '',
        'sortName': '',
        'sortType': '',
        'isHLtitle': 'true',
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(CNINFO_API, data=payload)
            resp.raise_for_status()
            j = resp.json()
            items = j.get('announcements', []) or []
            pdfs = []
            for it in items:
                adj = it.get('adjunctUrl', '')
                if not adj:
                    continue
                if not adj.lower().endswith('.pdf'):
                    # sometimes adjunctUrl points to a folder or json; skip
                    if '.pdf' not in adj.lower():
                        continue
                if not adj.startswith('http'):
                    adj = f"https://www.cninfo.com.cn/{adj}"
                if adj not in pdfs:
                    pdfs.append(adj)
                if len(pdfs) >= 10:
                    break
            return pdfs
        except Exception as e:
            logger.error('cninfo fetch error: %s', e)
            return []


async def run_sample(symbol: str = '000001.SZ'):
    from app.news.pdf_parser import extract_text_from_pdf

    out = []
    pdf_urls = await fetch_cninfo_pdfs(symbol)
    logger.info('Found %d PDF candidates from CNInfo', len(pdf_urls))
    if not pdf_urls:
        # fallback: try reading temp/cninfo_cache.json if present
        cache_path = os.path.join(os.path.dirname(__file__), '..', '..', 'temp', 'cninfo_cache.json')
        try:
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    j = json.load(f)
                    entries = j.get(symbol, {}).get('results', [])
                    for it in entries:
                        u = it.get('url')
                        if u:
                            if not u.startswith('http'):
                                u = f"https://www.cninfo.com.cn/{u}"
                            if u not in pdf_urls and u.lower().endswith('.pdf'):
                                pdf_urls.append(u)
                        if len(pdf_urls) >= 10:
                            break
        except Exception:
            pass

    if not pdf_urls:
        print('No PDF URLs found from CNInfo for', symbol)
        return

    for url in pdf_urls:
        logger.info('Testing PDF: %s', url)
        t0 = time.time()
        # quick availability check and try alternate static host if 404
        try:
            async with httpx.AsyncClient(timeout=15.0) as _c:
                try:
                    r = await _c.get(url)
                except Exception:
                    r = None
                if not r or r.status_code != 200:
                    # try static host
                    from urllib.parse import urlparse
                    p = urlparse(url)
                    path = p.path.lstrip('/')
                    alt = f"https://static.cninfo.com.cn/{path}"
                    try:
                        r2 = await _c.get(alt)
                        if r2 and r2.status_code == 200:
                            url = alt
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            text = await extract_text_from_pdf(url)
            took = time.time() - t0
            record = {
                'url': url,
                'status': 'ok' if text else 'empty',
                'text_length': len(text) if text else 0,
                'preview': (text[:500] if text else ''),
                'time_s': round(took, 2),
            }
        except Exception as e:
            took = time.time() - t0
            record = {
                'url': url,
                'status': 'error',
                'error': str(e),
                'text_length': 0,
                'preview': '',
                'time_s': round(took, 2),
            }
        out.append(record)

    os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'temp'), exist_ok=True)
    report_path = os.path.join(os.path.dirname(__file__), '..', 'temp', 'pdf_sample_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump({'symbol': symbol, 'results': out}, f, ensure_ascii=False, indent=2)

    print('Wrote report to', report_path)
    for r in out:
        print(f"- {r['status']}: {r['url']} (len={r['text_length']}, time={r['time_s']}s)")


if __name__ == '__main__':
    asyncio.run(run_sample())
