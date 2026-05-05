-- Stock Pool & Profile schema migration (idempotent-ish, check existence before applying in tooling)

-- Tables
CREATE TABLE IF NOT EXISTS stock_pool_members (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    first_seen_date DATE NOT NULL,
    last_seen_date DATE NOT NULL,
    exit_date DATE NULL,
    notes TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_pool_symbol ON stock_pool_members(symbol);
CREATE INDEX IF NOT EXISTS idx_stock_pool_last_seen ON stock_pool_members(last_seen_date);

CREATE TABLE IF NOT EXISTS stock_profiles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) UNIQUE NOT NULL,
    company_name VARCHAR(128) NULL,
    industry VARCHAR(64) NULL,
    sub_industry VARCHAR(64) NULL,
    business_summary TEXT NULL,
    core_products TEXT NULL,
    competitive_position TEXT NULL,
    competitors TEXT NULL,
    strategic_keywords TEXT NULL,
    risk_factors TEXT NULL,
    history_highlights TEXT NULL,
    profile_json TEXT NULL,
    last_refreshed TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_profile_symbol ON stock_profiles(symbol);
CREATE INDEX IF NOT EXISTS idx_stock_profile_industry ON stock_profiles(industry);

-- Columns
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='stock_daily_features' AND column_name='in_stock_pool') THEN
        EXECUTE 'ALTER TABLE stock_daily_features ADD COLUMN in_stock_pool BOOLEAN NULL';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='stock_daily_features' AND column_name='industry') THEN
        EXECUTE 'ALTER TABLE stock_daily_features ADD COLUMN industry VARCHAR(64) NULL';
    END IF;
END $$;
