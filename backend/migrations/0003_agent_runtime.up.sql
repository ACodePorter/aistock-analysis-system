-- Migration: 0003_agent_runtime
-- Direction: upgrade
-- Purpose: add multi-role Agent runtime task, run, pipeline, Skill usage, version and audit records.

CREATE TABLE IF NOT EXISTS agent_runtime_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(80) NOT NULL UNIQUE,
    user_message TEXT NOT NULL,
    intent VARCHAR(64) NOT NULL,
    risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
    plan_json JSONB NOT NULL,
    final_summary TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL,
    finished_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_task_intent_created ON agent_runtime_tasks(intent, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_task_status_created ON agent_runtime_tasks(status, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_runtime_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(80) NOT NULL UNIQUE,
    task_id VARCHAR(80) NOT NULL,
    pipeline_run_id VARCHAR(80) NULL,
    agent_name VARCHAR(80) NOT NULL,
    status VARCHAR(24) NOT NULL,
    input_summary TEXT NOT NULL,
    output_summary TEXT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    duration_ms INTEGER NULL,
    error TEXT NULL,
    used_data_sources JSONB NULL,
    used_skills JSONB NULL,
    output_json JSONB NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_run_agent_started ON agent_runtime_runs(agent_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_run_task ON agent_runtime_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_run_pipeline ON agent_runtime_runs(pipeline_run_id);

CREATE TABLE IF NOT EXISTS agent_runtime_pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    pipeline_run_id VARCHAR(80) NOT NULL UNIQUE,
    pipeline_type VARCHAR(40) NOT NULL,
    status VARCHAR(24) NOT NULL,
    triggered_by VARCHAR(24) NOT NULL DEFAULT 'user',
    user_request TEXT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    duration_ms INTEGER NULL,
    final_summary TEXT NULL,
    warnings_json JSONB NULL,
    payload_json JSONB NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_pipeline_type_started ON agent_runtime_pipeline_runs(pipeline_type, started_at DESC);

CREATE TABLE IF NOT EXISTS agent_runtime_skill_usages (
    id BIGSERIAL PRIMARY KEY,
    usage_id VARCHAR(80) NOT NULL UNIQUE,
    skill_key VARCHAR(100) NOT NULL,
    skill_name VARCHAR(160) NOT NULL,
    owner_agent VARCHAR(80) NOT NULL,
    task_id VARCHAR(80) NULL,
    pipeline_run_id VARCHAR(80) NULL,
    agent_run_id VARCHAR(80) NULL,
    status VARCHAR(24) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    duration_ms INTEGER NULL,
    input_summary TEXT NULL,
    output_summary TEXT NULL,
    error TEXT NULL,
    triggered_by VARCHAR(24) NOT NULL DEFAULT 'user',
    data_sources_used JSONB NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_usage_key_started ON agent_runtime_skill_usages(skill_key, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_usage_owner_started ON agent_runtime_skill_usages(owner_agent, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_usage_task ON agent_runtime_skill_usages(task_id);

CREATE TABLE IF NOT EXISTS agent_runtime_skill_definitions (
    id BIGSERIAL PRIMARY KEY,
    skill_key VARCHAR(100) NOT NULL UNIQUE,
    definition_json JSONB NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
    version VARCHAR(40) NOT NULL DEFAULT '1.0.0',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NULL,
    updated_by VARCHAR(80) NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_definition_enabled ON agent_runtime_skill_definitions(enabled);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_definition_risk ON agent_runtime_skill_definitions(risk_level);

CREATE TABLE IF NOT EXISTS agent_runtime_skill_versions (
    id BIGSERIAL PRIMARY KEY,
    version_id VARCHAR(80) NOT NULL UNIQUE,
    skill_key VARCHAR(100) NOT NULL,
    version VARCHAR(40) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(80) NOT NULL DEFAULT 'system',
    change_summary TEXT NOT NULL,
    before_json JSONB NULL,
    after_json JSONB NOT NULL,
    audit_log_id VARCHAR(80) NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_version_key_created ON agent_runtime_skill_versions(skill_key, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_runtime_skill_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    audit_log_id VARCHAR(80) NOT NULL UNIQUE,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor VARCHAR(24) NOT NULL DEFAULT 'user',
    action VARCHAR(40) NOT NULL,
    skill_key VARCHAR(100) NOT NULL,
    before_json JSONB NULL,
    after_json JSONB NULL,
    reason TEXT NULL,
    result VARCHAR(24) NOT NULL,
    risk_level VARCHAR(20) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_audit_key_time ON agent_runtime_skill_audit_logs(skill_key, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_skill_audit_action ON agent_runtime_skill_audit_logs(action);