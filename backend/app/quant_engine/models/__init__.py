"""
Quant Engine ORM 模型定义（qe_ 前缀，与现有表隔离）

新增表：
- qe_stock_models:       每只股票的独立模型注册
- qe_model_versions:     模型版本历史与元数据
- qe_factor_metadata:    因子库定义（因子注册表）
- qe_factor_values:      因子值存储（时间序列）
- qe_predictions:        预测记录（分类+回归）
- qe_evaluation_runs:    回测/评估运行记录
- qe_evaluation_metrics: 评估指标明细
- qe_signals:            交易信号
- qe_training_jobs:      训练任务队列
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    String, Integer, Boolean, Date, BigInteger, Float, TIMESTAMP,
    Text, Index, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ...core.models import Base


# =========================
# 枚举
# =========================

class QEModelStatus(str, Enum):
    """模型状态"""
    ACTIVE = "active"          # 当前服务中
    TRAINING = "training"      # 训练中
    RETIRED = "retired"        # 已退役
    FAILED = "failed"          # 训练失败


class QETrainingJobStatus(str, Enum):
    """训练任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class QESignalAction(str, Enum):
    """信号动作"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class QEFactorCategory(str, Enum):
    """因子分类"""
    TECHNICAL = "technical"
    NEWS = "news"
    MACRO = "macro"
    BEHAVIORAL = "behavioral"
    CROSS_STOCK = "cross_stock"


# =========================
# 每只股票的模型注册
# =========================

class QEStockModel(Base):
    """股票级模型注册表：每个 (symbol, task) 对应一个模型实例

    - symbol:         股票代码（如 600519.SH）
    - task:           预测任务（next_day_direction / fwd_ret_5d 等）
    - algo:           算法类型（lightgbm / xgboost / lstm 等）
    - active_version: 当前生效的版本号
    - status:         模型状态
    """
    __tablename__ = "qe_stock_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    task: Mapped[str] = mapped_column(String(50), index=True)
    algo: Mapped[str] = mapped_column(String(50))
    active_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default=QEModelStatus.ACTIVE.value
    )
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="模型超参数 JSON")
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "task", "algo", name="uq_qe_stock_model"),
        Index("idx_qe_sm_symbol_task", "symbol", "task"),
        Index("idx_qe_sm_status", "status"),
    )


class QEModelVersion(Base):
    """模型版本历史表

    - stock_model_id: 关联 qe_stock_models.id
    - version:        版本号（自增）
    - artifact_path:  模型存储路径（本地 / 对象存储）
    - features_used:  使用的特征列表 (JSONB)
    - metrics_json:   训练时评估指标
    - train_samples:  训练样本数
    - train_start/end:训练数据时间范围
    """
    __tablename__ = "qe_model_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stock_model_id: Mapped[int] = mapped_column(BigInteger, index=True)
    version: Mapped[int] = mapped_column(Integer)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    features_used: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    train_samples: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    train_start: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    train_end: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("stock_model_id", "version", name="uq_qe_mv_model_version"),
        Index("idx_qe_mv_active", "stock_model_id", "is_active"),
    )


# =========================
# 因子库
# =========================

class QEFactorMetadata(Base):
    """因子注册表：每个因子的元数据定义

    - factor_name:    因子唯一名称（如 rsi_14, macd_signal, news_sentiment_3d）
    - category:       分类（technical/news/macro/behavioral/cross_stock）
    - description:    因子描述
    - compute_params: 计算参数（如 {"window": 14}）
    - enabled:        是否启用
    """
    __tablename__ = "qe_factor_metadata"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    factor_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compute_params: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    data_type: Mapped[str] = mapped_column(String(20), default="float", comment="float/int/bool/category")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )

    __table_args__ = (
        Index("idx_qe_fm_category", "category", "enabled"),
    )


class QEFactorValue(Base):
    """因子值存储表（时间序列特征存储）

    - symbol:       股票代码
    - trade_date:   交易日
    - factor_name:  因子名称（关联 qe_factor_metadata.factor_name）
    - value:        因子值（浮点数）
    - normalized:   标准化后的值（可选）
    """
    __tablename__ = "qe_factor_values"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    trade_date: Mapped[datetime.date] = mapped_column(Date)
    factor_name: Mapped[str] = mapped_column(String(100))
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    normalized: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", "factor_name", name="uq_qe_fv_stf"),
        Index("idx_qe_fv_symbol_date", "symbol", "trade_date"),
        Index("idx_qe_fv_factor", "factor_name", "trade_date"),
    )


# =========================
# 预测记录
# =========================

class QEPrediction(Base):
    """预测结果表

    - symbol:              股票代码
    - predict_date:        预测生成日
    - target_date:         预测目标日
    - horizon:             预测周期（1d/5d/10d/20d）
    - direction_prob_up:   上涨概率（分类任务）
    - predicted_return:    预测收益率（回归任务）
    - confidence:          置信度
    - model_version_id:    使用的模型版本
    - actual_return:       实际收益率（回填）
    - actual_direction:    实际方向（回填）
    """
    __tablename__ = "qe_predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    predict_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    target_date: Mapped[datetime.date] = mapped_column(Date)
    horizon: Mapped[str] = mapped_column(String(10))
    direction_prob_up: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    direction_prob_down: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    predicted_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_version_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # 回填字段
    actual_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_direction: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    explanation_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="预测解释（特征贡献等）")
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("symbol", "predict_date", "horizon", "model_version_id",
                         name="uq_qe_pred_sphm"),
        Index("idx_qe_pred_symbol_date", "symbol", "predict_date"),
        Index("idx_qe_pred_target", "target_date"),
    )


# =========================
# 回测与评估
# =========================

class QEEvaluationRun(Base):
    """评估运行记录

    - run_type:   评估类型（backtest / holdout / walk_forward）
    - scope:      评估范围（symbol / portfolio / global）
    - symbols:    涉及的股票列表 (JSONB)
    - period_start / period_end: 评估时间范围
    """
    __tablename__ = "qe_evaluation_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_type: Mapped[str] = mapped_column(String(30))
    scope: Mapped[str] = mapped_column(String(20))
    symbols: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    model_version_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    period_start: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    summary_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )

    __table_args__ = (
        Index("idx_qe_er_type_scope", "run_type", "scope"),
    )


class QEEvaluationMetric(Base):
    """评估指标明细

    支持：accuracy, precision, recall, auc, pnl, max_drawdown, sharpe 等
    """
    __tablename__ = "qe_evaluation_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evaluation_run_id: Mapped[int] = mapped_column(BigInteger, index=True)
    metric_name: Mapped[str] = mapped_column(String(50))
    metric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    horizon: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )

    __table_args__ = (
        Index("idx_qe_em_run_metric", "evaluation_run_id", "metric_name"),
    )


# =========================
# 交易信号
# =========================

class QESignal(Base):
    """量化交易信号表

    - action:       信号动作（strong_buy/buy/hold/sell/strong_sell）
    - score:        综合信号得分（0~100）
    - risk_score:   风险评分（0~100，越高越危险）
    - rank:         当日所有股票中的排名（1 = 最佳）
    - factors_json: 信号生成所依据的因子贡献
    """
    __tablename__ = "qe_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    signal_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    action: Mapped[str] = mapped_column(String(20))
    score: Mapped[float] = mapped_column(Float, default=50.0)
    risk_score: Mapped[float] = mapped_column(Float, default=50.0)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    direction_prob_up: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    predicted_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    trigger_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    holding_period: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signal_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    factors_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    model_version_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("symbol", "signal_date", name="uq_qe_signal_sd"),
        Index("idx_qe_sig_date_rank", "signal_date", "rank"),
        Index("idx_qe_sig_action", "action"),
    )


# =========================
# 训练任务队列
# =========================

class QETrainingJob(Base):
    """训练任务表

    - job_type:   增量训练 / 全量训练 / 自动选模
    - trigger:    触发方式（scheduled / event / manual）
    """
    __tablename__ = "qe_training_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(30))
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled")
    status: Mapped[str] = mapped_column(
        String(20), default=QETrainingJobStatus.PENDING.value
    )
    config_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, default=datetime.datetime.utcnow
    )

    __table_args__ = (
        Index("idx_qe_tj_status", "status"),
        Index("idx_qe_tj_symbol_type", "symbol", "job_type"),
    )
