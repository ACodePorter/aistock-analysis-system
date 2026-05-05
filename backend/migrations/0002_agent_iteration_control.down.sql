-- Migration: 0002_agent_iteration_control
-- Direction: downgrade
-- Purpose: rollback persisted agent iteration control tables.

DROP TABLE IF EXISTS agent_verification_checks;
DROP TABLE IF EXISTS agent_review_runs;
DROP TABLE IF EXISTS failure_analyses;
DROP TABLE IF EXISTS feature_snapshots;