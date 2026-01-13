#!/usr/bin/env python3
"""
数据库迁移脚本 - 添加 last_updated_at 字段到 watchlist 表

使用方法：
    python migrations/migrate.py

功能：
    - 自动检查数据库并添加缺失的字段
    - 支持 PostgreSQL 和 SQLite
    - 安全的 IF NOT EXISTS 检查
"""

import os
import sys
import logging
from datetime import datetime

# 添加 backend 目录到路径
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

from sqlalchemy import create_engine, text, inspect
sys.path.insert(0, os.path.join(backend_dir, 'app'))

# 直接从环境变量读取数据库 URL 或使用默认值
import os
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://aistock:aistock@localhost:5432/aistock'
)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate():
    """执行数据库迁移"""
    try:
        logger.info("🔄 开始数据库迁移...")
        logger.info(f"数据库 URL: {DATABASE_URL}")
        
        # 创建数据库引擎
        engine = create_engine(DATABASE_URL)
        
        # 检查连接
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info("✅ 数据库连接成功")
        
        # 获取表信息
        inspector = inspect(engine)
        
        # 检查 watchlist 表是否存在
        if 'watchlist' not in inspector.get_table_names():
            logger.error("❌ watchlist 表不存在，请先创建表")
            return False
        
        # 获取 watchlist 表的列信息
        watchlist_columns = [col['name'] for col in inspector.get_columns('watchlist')]
        logger.info(f"📋 watchlist 表现有列: {watchlist_columns}")
        
        # 检查是否需要添加 last_updated_at 列
        if 'last_updated_at' not in watchlist_columns:
            logger.info("➕ 需要添加 last_updated_at 列...")
            
            with engine.connect() as conn:
                # 确定数据库类型
                db_dialect = engine.dialect.name
                logger.info(f"📊 数据库类型: {db_dialect}")
                
                # PostgreSQL
                if db_dialect == 'postgresql':
                    sql = """
                    ALTER TABLE watchlist
                    ADD COLUMN last_updated_at TIMESTAMP NULL;
                    """
                # SQLite
                elif db_dialect == 'sqlite':
                    sql = """
                    ALTER TABLE watchlist
                    ADD COLUMN last_updated_at TIMESTAMP NULL;
                    """
                # MySQL
                elif db_dialect == 'mysql':
                    sql = """
                    ALTER TABLE watchlist
                    ADD COLUMN last_updated_at TIMESTAMP NULL COMMENT '最后一次资讯更新完成时间';
                    """
                else:
                    logger.error(f"❌ 不支持的数据库类型: {db_dialect}")
                    return False
                
                conn.execute(text(sql))
                conn.commit()
                logger.info("✅ 成功添加 last_updated_at 列")
        else:
            logger.info("✓ last_updated_at 列已存在，跳过添加")
        
        # 创建索引
        try:
            with engine.connect() as conn:
                # 检查索引是否存在
                existing_indexes = [idx['name'] for idx in inspector.get_indexes('watchlist')]
                
                if 'idx_watchlist_last_updated_at' not in existing_indexes:
                    logger.info("➕ 创建索引: idx_watchlist_last_updated_at")
                    sql = """
                    CREATE INDEX idx_watchlist_last_updated_at ON watchlist(last_updated_at);
                    """
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info("✅ 索引创建成功")
                else:
                    logger.info("✓ 索引已存在，跳过创建")
        except Exception as e:
            logger.warning(f"⚠️  索引创建失败（可能已存在）: {e}")
        
        logger.info("🎉 数据库迁移完成！")
        return True
        
    except Exception as e:
        logger.error(f"❌ 迁移失败: {str(e)}", exc_info=True)
        return False


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
