-- 2026-04-17 新增 pipeline_runs 表：per-symbol 数据管道执行追踪
-- 与 backend/app/core/models.py 的 PipelineRun ORM 定义保持一致。

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id           BIGSERIAL PRIMARY KEY,
    symbol       VARCHAR(16) NOT NULL,
    run_type     VARCHAR(32) NOT NULL,
    status       VARCHAR(16) NOT NULL,
    run_at       TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms  INTEGER,
    message      TEXT,
    error_message TEXT,
    log_excerpt  TEXT,
    trigger      VARCHAR(32) NOT NULL DEFAULT 'scheduler'
);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_symbol_run_at
    ON pipeline_runs (symbol, run_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_run_type_run_at
    ON pipeline_runs (run_type, run_at);
