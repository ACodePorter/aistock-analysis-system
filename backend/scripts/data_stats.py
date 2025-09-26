import os
import sys
from sqlalchemy import select, func
from backend.app.db import SessionLocal
from backend.app.models import NewsArticle


def main():
    session = SessionLocal()
    try:
        total = session.execute(select(func.count(NewsArticle.id))).scalar()
        pdf_count = session.execute(
            select(func.count(NewsArticle.id)).where(NewsArticle.url.ilike('%\.pdf'))
        ).scalar()
        empty_summary = session.execute(
            select(func.count(NewsArticle.id)).where((NewsArticle.summary.is_(None)) | (func.length(NewsArticle.summary) == 0))
        ).scalar()
        llm_true = session.execute(
            select(func.count(NewsArticle.id)).where(NewsArticle.summary_from_llm.is_(True))
        ).scalar()
        llm_false = session.execute(
            select(func.count(NewsArticle.id)).where(NewsArticle.summary_from_llm.is_(False))
        ).scalar()

        print("News data stats:\n")
        print(f"  Total articles: {total}")
        print(f"  PDF URLs:      {pdf_count}")
        print(f"  Empty summary: {empty_summary}")
        print(f"  LLM summaries: {llm_true}")
        print(f"  Non-LLM sum.:  {llm_false}")
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
