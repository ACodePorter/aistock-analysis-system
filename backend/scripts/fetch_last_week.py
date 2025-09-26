#!/usr/bin/env python3
"""
Fetch and ingest news for the past 7 days with higher breadth.
- Pulls for all enabled watchlist symbols (symbol and company name queries)
- Optionally pulls for a set of market/industry topics
- Uses SearXNG time_range=week and a higher per-query limit
- Processes and persists using existing NewsProcessor logic

Usage (examples):
  python backend/scripts/fetch_last_week.py --max-per-query 30
  python backend/scripts/fetch_last_week.py --max-per-query 40 --include-industries
  python backend/scripts/fetch_last_week.py --industries 新能源,半导体,医药,券商,白酒,地产
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List, Optional, Set

# Ensure backend/app is importable when running this script directly
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.db import SessionLocal  # type: ignore
from app.models import NewsArticle, Watchlist  # type: ignore
from app.news_service import NewsSearchService, NewsProcessor  # type: ignore
from sqlalchemy import select


async def fetch_for_watchlist(search: NewsSearchService, max_per_query: int) -> List[Dict[str, Any]]:
    """Fetch last-week news for all enabled watchlist entries with a higher per-query cap."""
    results: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    with SessionLocal() as session:
        stocks = session.execute(select(Watchlist).where(Watchlist.enabled == True)).scalars().all()

    for stock in stocks:
        queries = [q for q in [stock.symbol, stock.name] if q]
        for q in queries:
            try:
                r = await search.search_news(
                    query=f"{q} 股票 财经",
                    category="general",
                    time_range="week",
                    max_results=max_per_query,
                )
                for item in r:
                    u = item.get("url")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        results.append(item)
            except Exception as e:
                print(f"Search failed for '{q}': {e}")
    return results


async def fetch_for_industries(search: NewsSearchService, industries: List[str], max_per_query: int) -> List[Dict[str, Any]]:
    """Fetch last-week industry/policy/market topic news with higher cap."""
    results: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    base_keywords = ["行业", "政策", "A股", "板块", "ETF", "指数", "资金流向"]

    for ind in industries:
        query = f"{ind} {' '.join(base_keywords)}"
        try:
            r = await search.search_news(
                query=query,
                category="general",
                time_range="week",
                max_results=max_per_query,
            )
            for item in r:
                u = item.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    results.append(item)
        except Exception as e:
            print(f"Industry search failed for '{ind}': {e}")
    return results


async def main_async(args: argparse.Namespace) -> None:
    search = NewsSearchService()
    processor = NewsProcessor()

    aggregated: List[Dict[str, Any]] = []

    wl_results = await fetch_for_watchlist(search, max_per_query=args.max_per_query)
    print(f"Watchlist queries returned {len(wl_results)} unique results")
    aggregated.extend(wl_results)

    if args.include_industries or args.industries:
        industries = [s.strip() for s in (args.industries.split(',') if args.industries else []) if s.strip()]
        if not industries:
            industries = [
                "A股", "新能源", "半导体", "医药", "券商", "白酒", "地产", "光伏", "TMT", "通信", "汽车", "AI"
            ]
        ind_results = await fetch_for_industries(search, industries, max_per_query=args.max_per_query)
        print(f"Industry queries returned {len(ind_results)} unique results")
        aggregated.extend(ind_results)

    # Dedup across aggregated by URL
    seen: Set[str] = set()
    unique_results: List[Dict[str, Any]] = []
    for it in aggregated:
        u = it.get("url")
        if u and u not in seen:
            seen.add(u)
            unique_results.append(it)

    print(f"Total unique search results to process: {len(unique_results)}")

    # Process through existing pipeline
    articles = await processor.process_search_results(unique_results)
    print(f"Articles created after processing/filtering: {len(articles)}")

    # Persist
    saved = 0
    updated = 0
    with SessionLocal() as session:
        for a in articles:
            try:
                existing = session.execute(select(NewsArticle).where(NewsArticle.url == a.url)).scalar_one_or_none()
                if not existing:
                    session.add(a)
                    saved += 1
                else:
                    # Optional: update fields if new analysis richer
                    updated += 0
            except Exception as e:
                print(f"Save failed for {a.url}: {e}")
        session.commit()

    print("\nIngestion summary:")
    print(f"  Processed results: {len(unique_results)}")
    print(f"  Saved new articles: {saved}")
    print(f"  Updated existing: {updated}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch last week news with higher limits")
    parser.add_argument("--max-per-query", type=int, default=30, help="Max results per query (default 30)")
    parser.add_argument("--include-industries", action="store_true", help="Also fetch industry/market topics")
    parser.add_argument("--industries", type=str, default="", help="Comma-separated industries to search (overrides default list when --include-industries)")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
