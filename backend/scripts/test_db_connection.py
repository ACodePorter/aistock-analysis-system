#!/usr/bin/env python3
"""
测试数据库连接
"""
import sys
import os

# 添加后端目录到Python路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

try:
    from app.db import engine
    from sqlalchemy import text

    print("🔍 测试数据库连接...")
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        print("✅ 数据库连接成功:", result.fetchone())

    print("🔍 测试表结构...")
    # 检查news_articles表是否存在
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'news_articles'
            ORDER BY ordinal_position
        """))
        columns = result.fetchall()

        if columns:
            print("✅ news_articles表存在，包含以下列:")
            for col in columns:
                print(f"   - {col[0]}: {col[1]} ({'NULL' if col[2] == 'YES' else 'NOT NULL'})")
        else:
            print("❌ news_articles表不存在")

except Exception as e:
    print(f"❌ 数据库连接失败: {e}")
    import traceback
    traceback.print_exc()