"""
Clear current article data (news_articles) and optionally purge dedup caches (Redis + Mongo).

Usage (PowerShell):
  # Default: clear SQL articles and purge caches
  python -m backend.scripts.clear_articles

  # Skip cache purge
  $env:PURGE_DEDUP_CACHES="false"; python -m backend.scripts.clear_articles
"""

from __future__ import annotations

import os
from sqlalchemy import text

from backend.app.db import engine, SessionLocal, get_redis_client


def clear_sql_articles():
    with engine.begin() as conn:
        # Truncate table and reset identity; CASCADE to clean self FKs like duplicate_of
        conn.execute(text("TRUNCATE TABLE news_articles RESTART IDENTITY CASCADE"))
    print("✓ Cleared PostgreSQL table: news_articles (TRUNCATE RESTART IDENTITY CASCADE)")


def purge_redis():
    client = get_redis_client()
    if not client:
        print("⚠ Redis not configured or unavailable; skip Redis cache purge")
        return
    # Delete url_cache:* keys (URL dedup cache)
    try:
        pattern = "url_cache:*"
        batch = []
        count = 0
        for key in client.scan_iter(match=pattern, count=1000):
            batch.append(key)
            if len(batch) >= 1000:
                client.delete(*batch)
                count += len(batch)
                batch.clear()
        if batch:
            client.delete(*batch)
            count += len(batch)
        print(f"✓ Purged Redis dedup keys matching '{pattern}': {count} keys deleted")
    except Exception as e:
        print(f"⚠ Redis purge error: {e}")


def purge_mongo():
    try:
        import os
        from pymongo import MongoClient
        mongo_host = os.getenv("MONGO_HOST", "localhost")
        mongo_port = int(os.getenv("MONGO_PORT", "27017"))
        mongo_user = os.getenv("MONGO_USER", "")
        mongo_password = os.getenv("MONGO_PASSWORD", "")
        mongo_db = os.getenv("MONGO_DB", "aistock_news")
        if mongo_user and mongo_password:
            uri = f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/{mongo_db}"
        else:
            uri = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client[mongo_db]
        # Collections used by dedup
        cols = ["url_cache", "content_fingerprints", "similarity_cache"]
        total = 0
        for c in cols:
            try:
                r = db[c].delete_many({})
                total += r.deleted_count
                print(f"  - Mongo collection '{c}': deleted {r.deleted_count} docs")
            except Exception as ce:
                print(f"  - Mongo collection '{c}' purge error: {ce}")
        print(f"✓ Purged MongoDB dedup caches (collections: {', '.join(cols)})")
    except Exception as e:
        print(f"⚠ MongoDB not available or purge failed: {e}")


def main():
    clear_sql_articles()
    purge = os.getenv("PURGE_DEDUP_CACHES", "true").lower() in ("1", "true", "yes")
    if purge:
        purge_redis()
        purge_mongo()
    else:
        print("↷ Skipped dedup cache purge (PURGE_DEDUP_CACHES=false)")


if __name__ == "__main__":
    main()
