#!/usr/bin/env python3
"""
量化引擎（quant_engine）数据库迁移脚本
日期：2026-03-31

功能：
    - 创建 qe_* 前缀的 9 张表（幂等，IF NOT EXISTS 保护）
    - 支持独立运行或作为模块调用
    
使用方法：
    cd backend
    python migrations/migrate_quant_engine.py
    
    # 或指定数据库 URL：
    DATABASE_URL=postgresql://user:pass@host/db python migrations/migrate_quant_engine.py
"""

import os
import sys
import logging

# 将 backend 目录加入路径
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _backend_dir)

from sqlalchemy import create_engine, text, inspect

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://aistock:aistock@localhost:5432/aistock",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

QE_TABLES = [
    "qe_stock_models",
    "qe_model_versions",
    "qe_factor_metadata",
    "qe_factor_values",
    "qe_predictions",
    "qe_evaluation_runs",
    "qe_evaluation_metrics",
    "qe_signals",
    "qe_training_jobs",
]

# SQL DDL — 与 infra/initdb/migrations/2026_03_31_quant_engine.sql 保持一致
_DDL = """
CREATE TABLE IF NOT EXISTS qe_stock_models (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(16)  NOT NULL,
    task        VARCHAR(50)  NOT NULL,
    algo        VARCHAR(50)  NOT NULL,
    active_version INTEGER   NOT NULL DEFAULT 0,
    status      VARCHAR(20)  NOT NULL DEFAULT 'active',
    config_json TEXT         NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NULL,
    CONSTRAINT uq_qe_stock_model UNIQUE (symbol, task, algo)
);
CREATE INDEX IF NOT EXISTS idx_qe_sm_symbol_task ON qe_stock_models (symbol, task);
CREATE INDEX IF NOT EXISTS idx_qe_sm_status      ON qe_stock_models (status);

CREATE TABLE IF NOT EXISTS qe_model_versions (
    id              BIGSERIAL PRIMARY KEY,
    stock_model_id  BIGINT       NOT NULL,
    version         INTEGER      NOT NULL,
    artifact_path   VARCHAR(500) NULL,
    features_used   JSONB        NULL,
    metrics_json    JSONB        NULL,
    train_samples   INTEGER      NULL,
    train_start     DATE         NULL,
    train_end       DATE         NULL,
    is_active       BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_qe_mv_model_version UNIQUE (stock_model_id, version)
);
CREATE INDEX IF NOT EXISTS idx_qe_mv_active ON qe_model_versions (stock_model_id, is_active);

CREATE TABLE IF NOT EXISTS qe_factor_metadata (
    id              BIGSERIAL PRIMARY KEY,
    factor_name     VARCHAR(100) NOT NULL UNIQUE,
    category        VARCHAR(30)  NOT NULL,
    description     TEXT         NULL,
    compute_params  JSONB        NULL,
    data_type       VARCHAR(20)  NOT NULL DEFAULT 'float',
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qe_fm_category ON qe_factor_metadata (category, enabled);

CREATE TABLE IF NOT EXISTS qe_factor_values (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(16)  NOT NULL,
    trade_date  DATE         NOT NULL,
    factor_name VARCHAR(100) NOT NULL,
    value       FLOAT        NULL,
    normalized  FLOAT        NULL,
    CONSTRAINT uq_qe_fv_stf UNIQUE (symbol, trade_date, factor_name)
);
CREATE INDEX IF NOT EXISTS idx_qe_fv_symbol_date ON qe_factor_values (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_qe_fv_factor       ON qe_factor_values (factor_name, trade_date);

CREATE TABLE IF NOT EXISTS qe_predictions (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              VARCHAR(16)  NOT NULL,
    predict_date        DATE         NOT NULL,
    target_date         DATE         NOT NULL,
    horizon             VARCHAR(10)  NOT NULL,
    direction_prob_up   FLOAT        NULL,
    direction_prob_down FLOAT        NULL,
    predicted_return    FLOAT        NULL,
    confidence          FLOAT        NULL,
    model_version_id    BIGINT       NULL,
    actual_return       FLOAT        NULL,
    actual_direction    INTEGER      NULL,
    explanation_json    JSONB        NULL,
    created_at          TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_qe_pred_sphm UNIQUE (symbol, predict_date, horizon, model_version_id)
);
CREATE INDEX IF NOT EXISTS idx_qe_pred_symbol_date ON qe_predictions (symbol, predict_date);
CREATE INDEX IF NOT EXISTS idx_qe_pred_target       ON qe_predictions (target_date);

CREATE TABLE IF NOT EXISTS qe_evaluation_runs (
    id               BIGSERIAL PRIMARY KEY,
    run_type         VARCHAR(30)  NOT NULL,
    scope            VARCHAR(20)  NOT NULL,
    symbols          JSONB        NULL,
    model_version_id BIGINT       NULL,
    period_start     DATE         NULL,
    period_end       DATE         NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'completed',
    summary_json     JSONB        NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qe_er_type_scope ON qe_evaluation_runs (run_type, scope);

CREATE TABLE IF NOT EXISTS qe_evaluation_metrics (
    id                BIGSERIAL PRIMARY KEY,
    evaluation_run_id BIGINT       NOT NULL,
    metric_name       VARCHAR(50)  NOT NULL,
    metric_value      FLOAT        NULL,
    symbol            VARCHAR(16)  NULL,
    horizon           VARCHAR(10)  NULL,
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qe_em_run_metric ON qe_evaluation_metrics (evaluation_run_id, metric_name);

CREATE TABLE IF NOT EXISTS qe_signals (
    id                BIGSERIAL PRIMARY KEY,
    symbol            VARCHAR(16)  NOT NULL,
    signal_date       DATE         NOT NULL,
    action            VARCHAR(20)  NOT NULL,
    score             FLOAT        NOT NULL DEFAULT 50.0,
    risk_score        FLOAT        NOT NULL DEFAULT 50.0,
    rank              INTEGER      NULL,
    direction_prob_up FLOAT        NULL,
    predicted_return  FLOAT        NULL,
    factors_json      JSONB        NULL,
    model_version_id  BIGINT       NULL,
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_qe_signal_sd UNIQUE (symbol, signal_date)
);
CREATE INDEX IF NOT EXISTS idx_qe_sig_date_rank ON qe_signals (signal_date, rank);
CREATE INDEX IF NOT EXISTS idx_qe_sig_action    ON qe_signals (action);

CREATE TABLE IF NOT EXISTS qe_training_jobs (
    id            BIGSERIAL PRIMARY KEY,
    symbol        VARCHAR(16)  NULL,
    job_type      VARCHAR(30)  NOT NULL,
    trigger       VARCHAR(20)  NOT NULL DEFAULT 'scheduled',
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
    config_json   JSONB        NULL,
    result_json   JSONB        NULL,
    error_message TEXT         NULL,
    started_at    TIMESTAMP    NULL,
    finished_at   TIMESTAMP    NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qe_tj_status      ON qe_training_jobs (status);
CREATE INDEX IF NOT EXISTS idx_qe_tj_symbol_type ON qe_training_jobs (symbol, job_type);
"""


def migrate(database_url: str = DATABASE_URL) -> bool:
    """执行 qe_* 表迁移，返回 True 表示成功"""
    logger.info("🔄 开始量化引擎数据库迁移...")
    logger.info(f"   目标数据库: {database_url.split('@')[-1]}")

    engine = create_engine(database_url)

    try:
        with engine.begin() as conn:
            conn.execute(text(_DDL))
        logger.info("✅ DDL 执行完成")
    except Exception as exc:
        logger.error(f"❌ DDL 执行失败: {exc}")
        return False

    # 验证表是否存在
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    missing = [t for t in QE_TABLES if t not in existing]

    if missing:
        logger.error(f"❌ 以下表未成功创建: {missing}")
        return False

    logger.info(f"✅ 全部 {len(QE_TABLES)} 张 qe_* 表已就绪:")
    for t in QE_TABLES:
        logger.info(f"   ✓ {t}")
    return True


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
