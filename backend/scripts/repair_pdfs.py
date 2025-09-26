"""
Batch repair for PDF-linked articles: re-extract text with pdfminer/pypdf and regenerate concise non-LLM summaries.

Usage (PowerShell):
  # Dry-run first (shows counts only)
  $env:DRY_RUN="true"; python -m backend.scripts.repair_pdfs

  # Apply changes with a limit
  $env:DRY_RUN="false"; $env:LIMIT="100"; python -m backend.scripts.repair_pdfs

  # Only process specific IDs (comma-separated)
  $env:ONLY_IDS="610,742"; python -m backend.scripts.repair_pdfs
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Iterable, List, Optional

from sqlalchemy import select, update

from backend.app.db import SessionLocal
from backend.app.models import NewsArticle
from backend.app.news_service import NewsProcessor


PDF_RE = re.compile(r"\.pdf(?:\b|$)", re.IGNORECASE)


def _chunked(seq: List[int], n: int) -> Iterable[List[int]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _build_summary(proc: NewsProcessor, title: str, content: str) -> str:
    s = proc._generate_summary(content or "")
    if not s:
        s = proc._generate_summary(f"{title or ''} {content or ''}")
    if not s:
        t = (title or "").strip()
        s = (t[:199] + "…") if len(t) > 200 else (t or "新闻简要：暂无可提取正文，标题提示该条与市场相关。")
    return s[:997] + "…" if len(s) > 1000 else s


async def _process_one(proc: NewsProcessor, article_id: int) -> Optional[tuple[int, str]]:
    session = SessionLocal()
    try:
        art = session.execute(select(NewsArticle).where(NewsArticle.id == article_id)).scalar_one_or_none()
        if not art:
            return None
        url = art.url or ""
        # Only PDFs
        if not PDF_RE.search(url):
            return None
        txt = await proc._extract_content(url)
        if not txt:
            return None
        summary = _build_summary(proc, art.title or "", txt)
        session.execute(
            update(NewsArticle)
            .where(NewsArticle.id == art.id)
            .values(content=txt[:8000], summary=summary, summary_from_llm=False)
        )
        session.commit()
        return (art.id, url)
    finally:
        session.close()


async def main():
    dry_run = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
    limit = int(os.getenv("LIMIT", "0"))
    only_ids = [int(x) for x in os.getenv("ONLY_IDS", "").split(",") if x.strip().isdigit()]

    session = SessionLocal()
    try:
        ids: List[int] = []
        if only_ids:
            ids = only_ids
        else:
            # Fetch candidates by URL pattern
            q = session.execute(
                select(NewsArticle.id, NewsArticle.url)
            ).all()
            for _id, url in q:
                if url and PDF_RE.search(url):
                    ids.append(_id)
        if limit > 0:
            ids = ids[:limit]
    finally:
        session.close()

    print(f"Found {len(ids)} PDF article candidates")
    if dry_run:
        print("Dry-run: no changes will be written.")
        return

    proc = NewsProcessor()
    updated = 0
    # Moderate concurrency for network fetches
    sem = asyncio.Semaphore(4)

    async def _task(aid: int):
        nonlocal updated
        async with sem:
            res = await _process_one(proc, aid)
            if res:
                updated += 1
                print(f"Updated PDF article {res[0]} -> {res[1]}")

    await asyncio.gather(*(_task(i) for i in ids))
    print(f"Done. Updated {updated} articles.")


if __name__ == "__main__":
    asyncio.run(main())
