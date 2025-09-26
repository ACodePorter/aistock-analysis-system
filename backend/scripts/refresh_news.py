#!/usr/bin/env python3
"""
Clear all news articles, re-fetch via legacy NewsScheduler, and validate published_at population.
"""
import asyncio
import os
import sys
from datetime import datetime

from sqlalchemy import text, select

# Ensure backend/app is importable when running this script directly
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.db import SessionLocal
from app.models import NewsArticle, Watchlist
from app.news_service import NewsScheduler


def clear_news():
    with SessionLocal() as session:
        total_before = session.execute(text("SELECT COUNT(*) FROM news_articles")).scalar_one()
        print(f"Existing news articles: {total_before}")
        session.execute(text("DELETE FROM news_articles"))
        session.commit()
        total_after = session.execute(text("SELECT COUNT(*) FROM news_articles")).scalar_one()
        print(f"Cleared news articles. Remaining: {total_after}")


def has_watchlist() -> bool:
    with SessionLocal() as session:
        cnt = session.execute(text("SELECT COUNT(*) FROM watchlist WHERE enabled = true")).scalar_one()
        print(f"Enabled watchlist count: {cnt}")
        return cnt > 0


async def refetch_news():
    scheduler = NewsScheduler()
    await scheduler.run_scheduled_news_collection()


def validate_published():
    with SessionLocal() as session:
        total = session.execute(text("SELECT COUNT(*) FROM news_articles")).scalar_one()
        with_pub = session.execute(text("SELECT COUNT(*) FROM news_articles WHERE published_at IS NOT NULL")).scalar_one()
        without_pub = total - with_pub
        print("\nValidation summary:")
        print(f"  Total articles: {total}")
        print(f"  With published_at: {with_pub}")
        print(f"  Without published_at: {without_pub}")

        # Show a few samples
        rows = session.execute(
            text(
                "SELECT title, url, published_at FROM news_articles ORDER BY published_at DESC NULLS LAST LIMIT 5"
            )
        ).mappings().all()
        print("\nSample articles (top 5):")
        for r in rows:
            print("-", r["published_at"], r["title"][:60], r["url"]) 


if __name__ == "__main__":
    print("=== Refresh news: clear -> refetch -> validate ===")
    if not has_watchlist():
        print("No enabled watchlist stocks found. Please add stocks before re-fetching news.")
    else:
        clear_news()
        asyncio.run(refetch_news())
        validate_published()
    print("Done.")
