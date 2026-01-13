-- 迁移脚本：为 watchlist 表添加 last_updated_at 字段
-- 日期：2025-10-17

-- 添加 last_updated_at 列（如果不存在）
ALTER TABLE watchlist
ADD COLUMN IF NOT EXISTS last_updated_at TIMESTAMP NULL COMMENT '最后一次资讯更新完成时间';

-- 创建索引以加快查询
CREATE INDEX IF NOT EXISTS idx_watchlist_last_updated_at ON watchlist(last_updated_at);
