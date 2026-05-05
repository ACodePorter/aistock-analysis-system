-- Migration: 0004_user_portfolio_opportunities
-- Direction: upgrade
-- Purpose: add user trade ledger derived positions and opportunity candidates.

CREATE TABLE IF NOT EXISTS user_portfolios (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL DEFAULT '我的持仓',
    base_currency VARCHAR(10) NOT NULL DEFAULT 'CNY',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_portfolio_default ON user_portfolios(is_default);

CREATE TABLE IF NOT EXISTS user_trade_ledger (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id VARCHAR(50) NOT NULL DEFAULT 'default',
    symbol VARCHAR(16) NOT NULL,
    side VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL,
    fees DOUBLE PRECISION NOT NULL DEFAULT 0,
    tax DOUBLE PRECISION NOT NULL DEFAULT 0,
    source VARCHAR(32) NOT NULL DEFAULT 'manual',
    external_trade_id VARCHAR(128) NULL,
    notes TEXT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_user_trade_side CHECK (side IN ('buy', 'sell')),
    CONSTRAINT chk_user_trade_quantity CHECK (quantity > 0),
    CONSTRAINT chk_user_trade_price CHECK (price > 0)
);

CREATE INDEX IF NOT EXISTS idx_user_trade_portfolio_symbol_date ON user_trade_ledger(portfolio_id, symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_user_trade_external ON user_trade_ledger(portfolio_id, source, external_trade_id);

CREATE TABLE IF NOT EXISTS user_positions (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id VARCHAR(50) NOT NULL DEFAULT 'default',
    symbol VARCHAR(16) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_cost DOUBLE PRECISION NULL,
    total_cost DOUBLE PRECISION NULL,
    realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    first_entry_date DATE NULL,
    last_trade_date DATE NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'manual',
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_user_positions_portfolio_symbol UNIQUE (portfolio_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_user_position_symbol ON user_positions(symbol);

CREATE TABLE IF NOT EXISTS opportunity_candidates (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    name VARCHAR(128) NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'opportunity_agent',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    opportunity_score DOUBLE PRECISION NULL,
    confidence DOUBLE PRECISION NULL,
    risk_level VARCHAR(20) NOT NULL DEFAULT 'medium',
    recommended_action VARCHAR(50) NULL,
    rationale TEXT NULL,
    evidence_json JSONB NULL,
    auto_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    discovered_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NULL,
    reviewed_at TIMESTAMP NULL,
    review_notes TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_opportunity_status_score ON opportunity_candidates(status, opportunity_score);
CREATE INDEX IF NOT EXISTS idx_opportunity_symbol_status ON opportunity_candidates(symbol, status);
