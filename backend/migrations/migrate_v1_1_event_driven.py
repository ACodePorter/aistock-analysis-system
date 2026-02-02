"""
v1.1 数据库迁移脚本 - 事件驱动系统升级

执行方式：
    cd backend && python -m migrations.migrate_v1_1_event_driven

主要变更：
1. Watchlist 表：新增 status, last_active_at, clean_rule_tag
2. NewsSource 表：新增 source_level
3. 新建 events 表（事件中心化）
4. 新建 briefings 表（简报系统）
"""

import os
import sys
from datetime import datetime

# 添加项目路径 - 使用简单直接的导入
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from app.core.db import get_db_url

# 直接从环境变量或默认值创建数据库连接
DATABASE_URL = os.getenv("DATABASE_URL") or get_db_url()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


MIGRATION_SQL = """
-- =============================================
-- v1.1 Migration: Event-Driven System Upgrade
-- Date: 2026-02-01
-- =============================================

-- 1. Watchlist 表扩展
DO $$
BEGIN
    -- 添加 status 字段
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'watchlist' AND column_name = 'status') THEN
        ALTER TABLE watchlist ADD COLUMN status VARCHAR(20) DEFAULT 'active';
        COMMENT ON COLUMN watchlist.status IS 'active/cooling/archived';
    END IF;
    
    -- 添加 last_active_at 字段
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'watchlist' AND column_name = 'last_active_at') THEN
        ALTER TABLE watchlist ADD COLUMN last_active_at TIMESTAMP;
        COMMENT ON COLUMN watchlist.last_active_at IS '最后活跃时间';
    END IF;
    
    -- 添加 clean_rule_tag 字段
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'watchlist' AND column_name = 'clean_rule_tag') THEN
        ALTER TABLE watchlist ADD COLUMN clean_rule_tag VARCHAR(100);
        COMMENT ON COLUMN watchlist.clean_rule_tag IS '清洗策略标签';
    END IF;
END $$;

-- 创建 watchlist 索引
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);

-- 2. NewsSource 表扩展
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'news_sources' AND column_name = 'source_level') THEN
        ALTER TABLE news_sources ADD COLUMN source_level VARCHAR(2) DEFAULT 'L2';
        COMMENT ON COLUMN news_sources.source_level IS 'L1/L2/L3/L4 信源等级';
    END IF;
END $$;

-- 创建 news_sources 索引
CREATE INDEX IF NOT EXISTS idx_news_source_level ON news_sources(source_level);
CREATE INDEX IF NOT EXISTS idx_news_source_enabled ON news_sources(enabled);

-- 3. 创建 events 表（事件中心化核心）
CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(64) UNIQUE NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_date DATE NOT NULL,
    
    -- 信源与可信度
    source_level VARCHAR(2) NOT NULL DEFAULT 'L2',
    confidence FLOAT DEFAULT 0.5,
    
    -- 内容
    summary TEXT NOT NULL,
    description TEXT,
    
    -- 结构化数据 (JSONB)
    entities JSONB,
    evidence JSONB,
    
    -- 元数据
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    merged_into VARCHAR(64)
);

COMMENT ON TABLE events IS '事件中心化核心表 - v1.1';
COMMENT ON COLUMN events.event_id IS '事件唯一标识';
COMMENT ON COLUMN events.source_level IS 'L1法定披露/L2财经媒体/L3官方机构/L4研究观点';
COMMENT ON COLUMN events.confidence IS '置信度 0-1';
COMMENT ON COLUMN events.entities IS '结构化实体：主体/对手方/金额等';
COMMENT ON COLUMN events.evidence IS '证据链：article_id/url列表';
COMMENT ON COLUMN events.merged_into IS '如果被合并，指向目标event_id';

-- events 索引
CREATE INDEX IF NOT EXISTS idx_event_event_id ON events(event_id);
CREATE INDEX IF NOT EXISTS idx_event_symbol ON events(symbol);
CREATE INDEX IF NOT EXISTS idx_event_symbol_date ON events(symbol, event_date);
CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_event_source_level ON events(source_level);

-- 4. 创建 briefings 表（简报系统）
CREATE TABLE IF NOT EXISTS briefings (
    id BIGSERIAL PRIMARY KEY,
    briefing_id VARCHAR(64) UNIQUE NOT NULL,
    symbol VARCHAR(16),
    period VARCHAR(10) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    
    -- 内容
    risk_summary TEXT,
    opportunity_summary TEXT,
    key_events JSONB,
    
    -- LLM 元数据
    llm_model VARCHAR(64),
    llm_tokens INTEGER,
    
    -- 时间戳
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE briefings IS '简报表（日报/周报）- v1.1';
COMMENT ON COLUMN briefings.briefing_id IS '简报唯一标识';
COMMENT ON COLUMN briefings.symbol IS '股票代码（NULL表示市场综合简报）';
COMMENT ON COLUMN briefings.period IS 'daily/weekly';
COMMENT ON COLUMN briefings.key_events IS '关键事件id/摘要/排序';
COMMENT ON COLUMN briefings.llm_model IS 'LLM模型标识';
COMMENT ON COLUMN briefings.llm_tokens IS 'Token消耗统计';

-- briefings 索引
CREATE INDEX IF NOT EXISTS idx_briefing_briefing_id ON briefings(briefing_id);
CREATE INDEX IF NOT EXISTS idx_briefing_symbol ON briefings(symbol);
CREATE INDEX IF NOT EXISTS idx_briefing_symbol_period ON briefings(symbol, period);
CREATE INDEX IF NOT EXISTS idx_briefing_period_start ON briefings(period_start);

-- 5. 迁移已有数据：设置 watchlist 默认状态
UPDATE watchlist SET status = 'active' WHERE status IS NULL;

-- 如果有 enabled 字段，将 enabled=false 的改为 archived
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'watchlist' AND column_name = 'enabled') THEN
        UPDATE watchlist SET status = 'archived' WHERE enabled = false AND status = 'active';
    END IF;
END $$;

-- 完成
SELECT 'v1.1 Migration completed successfully' AS result;
"""


def run_migration():
    """执行迁移"""
    print("=" * 60)
    print("AIStock v1.1 Database Migration")
    print("Event-Driven System Upgrade")
    print("=" * 60)
    print(f"Execution Time: {datetime.now().isoformat()}")
    print()
    
    try:
        with engine.connect() as conn:
            # 开始事务
            trans = conn.begin()
            try:
                # 执行迁移SQL（包含 DO $$ 块，需整体执行）
                try:
                    conn.exec_driver_sql(MIGRATION_SQL)
                except Exception as e:
                    # 忽略已存在的对象错误
                    if 'already exists' not in str(e).lower():
                        raise
                
                trans.commit()
                print("✅ Migration completed successfully!")
                print()
                
                # 验证表创建
                print("Verifying new tables...")
                result = conn.execute(text("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name IN ('events', 'briefings')
                """))
                tables = [row[0] for row in result]
                
                if 'events' in tables:
                    print("  ✅ events table created")
                else:
                    print("  ❌ events table NOT found")
                    
                if 'briefings' in tables:
                    print("  ✅ briefings table created")
                else:
                    print("  ❌ briefings table NOT found")
                
                # 验证字段
                print()
                print("Verifying new columns...")
                
                # watchlist.status
                result = conn.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'watchlist' AND column_name = 'status'
                """))
                if result.fetchone():
                    print("  ✅ watchlist.status column added")
                else:
                    print("  ❌ watchlist.status column NOT found")
                
                # news_sources.source_level
                result = conn.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'news_sources' AND column_name = 'source_level'
                """))
                if result.fetchone():
                    print("  ✅ news_sources.source_level column added")
                else:
                    print("  ❌ news_sources.source_level column NOT found")
                
                print()
                print("=" * 60)
                print("Migration verification complete!")
                print("=" * 60)
                
            except Exception as e:
                trans.rollback()
                raise e
                
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
