"""
Backfill past 7 days of A-share news using existing search and processing pipeline.

Usage (PowerShell):
  python -m backend.scripts.backfill_week

Environment variables (optional):
  SEARXNG_URL: SearXNG base URL (default http://localhost:10000)
  NEWS_HTTP_PROXY: HTTP proxy URL if needed
  NEWS_USE_LLM: 'true'|'false' to enable/disable LLM (default true)
  BACKFILL_MAX_PER_STOCK: per-stock result cap (default 20)
  BACKFILL_CONCURRENCY: concurrent stocks to process (default 3)
  BACKFILL_DRY_RUN: if 'true', do not write to DB
"""

import asyncio
import os
from datetime import datetime
from typing import List

from sqlalchemy import select

from backend.app.news_service import NewsSearchService, NewsProcessor
from backend.app.models import Watchlist, NewsArticle
from backend.app.db import SessionLocal


async def _collect_for_symbol(symbol: str, name: str, max_per_stock: int) -> List[NewsArticle]:
    search = NewsSearchService()
    processor = NewsProcessor()
    queries = [
        f"{symbol} 股票 新闻 财经",
        f"{name} 公司 新闻 财经" if name else None,
        f"{symbol} 公告 年报 季报",
    ]
    queries = [q for q in queries if q]
    all_results = []
    for q in queries:
        try:
            res = await search.search_news(q, category="general", time_range="week", max_results=max_per_stock)
            all_results.extend(res)
        except Exception as e:
            print(f"[Backfill] Search failed for {symbol}/{name}: {e}")
    # Dedup by URL
    seen = set()
    uniq = []
    for r in all_results:
        u = r.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        uniq.append(r)
        if len(uniq) >= max_per_stock:
            break
    articles = await processor.process_search_results(uniq, related_symbol=symbol)
    return articles


async def main():
    dry_run = os.getenv("BACKFILL_DRY_RUN", "false").lower() in ("1", "true", "yes")
    max_per_stock = int(os.getenv("BACKFILL_MAX_PER_STOCK", "20"))
    concurrency = int(os.getenv("BACKFILL_CONCURRENCY", "3"))

    print(f"[Backfill] Start at {datetime.now():%Y-%m-%d %H:%M:%S}, dry_run={dry_run}, per_stock={max_per_stock}, conc={concurrency}")

    # Load watchlist
    session = SessionLocal()
    try:
        stocks = session.execute(select(Watchlist).where(Watchlist.enabled == True)).scalars().all()
        print(f"[Backfill] Watchlist enabled count: {len(stocks)}")
    finally:
        session.close()

    # Concurrency control
    sem = asyncio.Semaphore(concurrency)
    results: List[NewsArticle] = []

    async def _task(sym: str, name: str):
        async with sem:
            arts = await _collect_for_symbol(sym, name, max_per_stock)
            print(f"[Backfill] {sym} got {len(arts)} articles")
            return arts

    tasks = [asyncio.create_task(_task(s.symbol, s.name)) for s in stocks]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    for b in batches:
        if isinstance(b, Exception):
            print(f"[Backfill] Task error: {b}")
        elif b:
            results.extend(b)

    print(f"[Backfill] Total candidate articles: {len(results)}")

    if dry_run:
        print("[Backfill] Dry run enabled. Skipping DB writes.")
        return

    # Save to DB with duplicate URL check
    session = SessionLocal()
    saved = 0
    try:
        for art in results:
            try:
                exists = session.execute(select(NewsArticle).where(NewsArticle.url == art.url)).scalar_one_or_none()
                if exists:
                    continue
                session.add(art)
                saved += 1
            except Exception as e:
                print(f"[Backfill] Failed to add {art.url}: {e}")
        session.commit()
    finally:
        session.close()

    print(f"[Backfill] Saved new articles: {saved}")


if __name__ == "__main__":
    asyncio.run(main())
