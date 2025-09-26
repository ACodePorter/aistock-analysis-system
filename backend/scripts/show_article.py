"""
Show an article's title, URL, summary and a content snippet for quick inspection.

Usage (PowerShell):
  python -m backend.scripts.show_article
  $env:SHOW_ARTICLE_ID=610; python -m backend.scripts.show_article
"""

import os
from sqlalchemy import select
from backend.app.db import SessionLocal
from backend.app.models import NewsArticle


def main():
    article_id = int(os.getenv("SHOW_ARTICLE_ID", "610"))
    session = SessionLocal()
    try:
        art = session.execute(select(NewsArticle).where(NewsArticle.id == article_id)).scalar_one_or_none()
        if not art:
            print(f"Article {article_id} not found")
            return
        content = (art.content or "")
        print(f"ID: {art.id}")
        print(f"Title: {art.title}")
        print(f"URL: {art.url}")
        print(f"Summary: {art.summary}")
        print("Content snippet:\n" + content[:600])
    finally:
        session.close()


if __name__ == "__main__":
    main()
