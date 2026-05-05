-- Migration: 0004_user_portfolio_opportunities
-- Direction: downgrade

DROP TABLE IF EXISTS opportunity_candidates;
DROP TABLE IF EXISTS user_positions;
DROP TABLE IF EXISTS user_trade_ledger;
DROP TABLE IF EXISTS user_portfolios;