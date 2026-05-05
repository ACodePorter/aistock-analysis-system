-- Migration: 0001_add_last_updated_at_to_watchlist
-- Direction: downgrade
-- Purpose: rollback watchlist last_updated_at tracking column.

DROP INDEX IF EXISTS idx_watchlist_last_updated_at;
ALTER TABLE watchlist DROP COLUMN IF EXISTS last_updated_at;