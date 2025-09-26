#!/usr/bin/env python3
"""
Database migration: add `summary_from_llm` boolean column to news_articles.

Run:
  python backend/scripts/migrate_add_summary_from_llm.py

Env vars (same as other migrations): POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT
"""
from __future__ import annotations

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

def run_migration():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            print("🔄 Checking existing columns…")
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'news_articles' AND column_name = 'summary_from_llm'
                """
            )
            exists = cur.fetchone() is not None
            if exists:
                print("✅ summary_from_llm already exists")
            else:
                print("📝 Adding summary_from_llm column…")
                cur.execute(
                    """
                    ALTER TABLE news_articles
                    ADD COLUMN summary_from_llm BOOLEAN DEFAULT FALSE
                    """
                )
                print("✅ Added summary_from_llm column")
            print("✅ Migration done")
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    run_migration()
