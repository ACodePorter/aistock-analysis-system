#!/usr/bin/env python3
"""
Database migration script to add user interaction fields to news_articles table
"""
import os
import sys
from dotenv import load_dotenv
import psycopg2

# Load environment variables
load_dotenv()

DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

def run_migration():
    """Run the database migration"""
    try:
        # Connect to the database
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.autocommit = True

        with conn.cursor() as cur:
            print("🔄 Checking if migration is needed...")

            # Check if columns already exist
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'news_articles'
                AND column_name IN ('is_bookmarked', 'is_read')
            """)

            existing_columns = [row[0] for row in cur.fetchall()]

            if 'is_bookmarked' in existing_columns:
                print("✅ is_bookmarked column already exists")
            else:
                print("📝 Adding is_bookmarked column...")
                cur.execute("""
                    ALTER TABLE news_articles
                    ADD COLUMN is_bookmarked BOOLEAN DEFAULT FALSE
                """)
                print("✅ Added is_bookmarked column")

            if 'is_read' in existing_columns:
                print("✅ is_read column already exists")
            else:
                print("📝 Adding is_read column...")
                cur.execute("""
                    ALTER TABLE news_articles
                    ADD COLUMN is_read BOOLEAN DEFAULT FALSE
                """)
                print("✅ Added is_read column")

            # Create indexes for better performance
            print("📝 Creating indexes for new columns...")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_bookmarked
                ON news_articles(is_bookmarked) WHERE is_bookmarked = true
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_read
                ON news_articles(is_read) WHERE is_read = true
            """)

            print("✅ Migration completed successfully!")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("🚀 Starting database migration for news_articles table...")
    run_migration()
    print("🎉 Migration script completed!")