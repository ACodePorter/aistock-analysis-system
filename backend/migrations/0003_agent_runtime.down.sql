-- Migration: 0003_agent_runtime
-- Direction: downgrade

DROP TABLE IF EXISTS agent_runtime_skill_audit_logs;
DROP TABLE IF EXISTS agent_runtime_skill_versions;
DROP TABLE IF EXISTS agent_runtime_skill_definitions;
DROP TABLE IF EXISTS agent_runtime_skill_usages;
DROP TABLE IF EXISTS agent_runtime_pipeline_runs;
DROP TABLE IF EXISTS agent_runtime_runs;
DROP TABLE IF EXISTS agent_runtime_tasks;