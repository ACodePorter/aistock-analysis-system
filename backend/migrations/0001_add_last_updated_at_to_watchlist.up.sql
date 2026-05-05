-- Migration: 0001_add_last_updated_at_to_watchlist
-- Direction: upgrade
-- Purpose: add last_updated_at to watchlist for news refresh tracking.

ALTER TABLE watchlist
ADD COLUMN IF NOT EXISTS last_updated_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_watchlist_last_updated_at ON watchlist(last_updated_at);