"""
Fill missing or empty article summaries.

Usage (PowerShell):
  python -m backend.scripts.fix_empty_summaries

This script scans `news_articles` where summary is NULL or empty string and
fills it using the same fallback logic as ingestion (content-based summary, then title).
"""

import asyncio
from sqlalchemy import select, update
from backend.app.db import SessionLocal
from backend.app.models import NewsArticle
from backend.app.news_service import NewsProcessor


async def main():
    proc = NewsProcessor()
    session = SessionLocal()
    updated = 0
    try:
        rows = session.execute(
            select(NewsArticle).where(
                (NewsArticle.summary.is_(None)) | (NewsArticle.summary == "")
            )
        ).scalars().all()
        print(f"Found {len(rows)} articles with missing/empty summary")
        for art in rows:
            # Regenerate a concise summary; mimic processor's fallback chain
            effective = proc._generate_summary(art.content or "")
            if not effective:
                effective = proc._generate_summary(f"{art.title or ''} {art.content or ''}")
            if not effective:
                t = (art.title or "").strip()
                effective = (t[:199] + "…") if len(t) > 200 else (t or "新闻简要：暂无可提取正文，标题提示该条与市场相关。")
            if effective and len(effective) > 1000:
                effective = effective[:997] + "…"
            session.execute(
                update(NewsArticle)
                .where(NewsArticle.id == art.id)
                .values(summary=effective, summary_from_llm=False)
            )
            updated += 1
        session.commit()
        print(f"Updated {updated} articles.")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
