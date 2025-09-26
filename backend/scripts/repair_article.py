"""
Repair a specific article by re-extracting content (PDF-aware) and regenerating a clean summary.

Usage (PowerShell):
  # Default repairs article id 610
  python -m backend.scripts.repair_article

  # Or provide a different id
  $env:REPAIR_ARTICLE_ID=637; python -m backend.scripts.repair_article
"""

import os
import asyncio
from sqlalchemy import select, update

from backend.app.db import SessionLocal
from backend.app.models import NewsArticle
from backend.app.news_service import NewsProcessor


async def main():
    article_id = int(os.getenv("REPAIR_ARTICLE_ID", "610"))
    session = SessionLocal()
    try:
        art = session.execute(select(NewsArticle).where(NewsArticle.id == article_id)).scalar_one_or_none()
        if not art:
            print(f"Article {article_id} not found")
            return
        print(f"Repairing article {art.id}: {art.title}\nURL: {art.url}")

        proc = NewsProcessor()
        # Re-extract content (handles PDF)
        txt = await proc._extract_content(art.url)
        if not txt:
            print("No content could be re-extracted; aborting")
            return

        # Build non-empty summary (mirror processor fallback)
        def build_summary(title: str, content: str) -> str:
            s = proc._generate_summary(content or "")
            if not s:
                s = proc._generate_summary(f"{title or ''} {content or ''}")
            if not s:
                t = (title or "").strip()
                s = (t[:199] + "…") if len(t) > 200 else (t or "新闻简要：暂无可提取正文，标题提示该条与市场相关。")
            return s[:997] + "…" if len(s) > 1000 else s

        summary = build_summary(art.title or "", txt)

        session.execute(
            update(NewsArticle)
            .where(NewsArticle.id == art.id)
            .values(content=txt[:8000], summary=summary, summary_from_llm=False)
        )
        session.commit()
        print("Repair done: content and summary updated.")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
