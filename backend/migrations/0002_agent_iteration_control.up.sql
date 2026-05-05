-- Migration: 0002_agent_iteration_control
-- Direction: upgrade
-- Purpose: persist feature snapshots, failure analyses, agent review runs, and verification checks.

CREATE TABLE IF NOT EXISTS feature_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id VARCHAR(80) NOT NULL UNIQUE,
    symbol VARCHAR(16) NOT NULL,
    as_of_date DATE NULL,
    prediction_date DATE NULL,
    target_date DATE NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'latest_prediction_signal_context',
    schema_version INTEGER NOT NULL DEFAULT 1,
    completeness_score FLOAT NULL,
    verification_status VARCHAR(20) NULL,
    gate_result JSONB NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_feature_snapshots_symbol_asof ON feature_snapshots(symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_target_date ON feature_snapshots(target_date);
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_status ON feature_snapshots(verification_status);

CREATE TABLE IF NOT EXISTS failure_analyses (
    id BIGSERIAL PRIMARY KEY,
    analysis_id VARCHAR(80) NOT NULL UNIQUE,
    symbol VARCHAR(16) NOT NULL,
    lookback_days INTEGER NOT NULL DEFAULT 60,
    severity VARCHAR(20) NOT NULL DEFAULT 'unknown',
    sample_count INTEGER NOT NULL DEFAULT 0,
    high_deviation_count INTEGER NOT NULL DEFAULT 0,
    evidence_snapshot_ids JSONB NULL,
    root_causes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_failure_analyses_symbol_created ON failure_analyses(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_failure_analyses_severity ON failure_analyses(severity);

CREATE TABLE IF NOT EXISTS agent_review_runs (
    id BIGSERIAL PRIMARY KEY,
    review_id VARCHAR(80) NOT NULL UNIQUE,
    symbol VARCHAR(16) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'waiting_for_samples',
    priority VARCHAR(20) NOT NULL DEFAULT 'none',
    source VARCHAR(64) NOT NULL DEFAULT 'failure_analysis_rule_agent',
    proposed_actions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocked_actions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    gate_result JSONB NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_review_runs_symbol_created ON agent_review_runs(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_review_runs_status ON agent_review_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_review_runs_verification ON agent_review_runs(verification_status);

CREATE TABLE IF NOT EXISTS agent_verification_checks (
    id BIGSERIAL PRIMARY KEY,
    check_id VARCHAR(96) NOT NULL UNIQUE,
    review_id VARCHAR(80) NOT NULL,
    check_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    evidence_json JSONB NULL,
    message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_agent_verification_review
        FOREIGN KEY (review_id)
        REFERENCES agent_review_runs(review_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_verification_review ON agent_verification_checks(review_id);
CREATE INDEX IF NOT EXISTS idx_agent_verification_type_status ON agent_verification_checks(check_type, status);