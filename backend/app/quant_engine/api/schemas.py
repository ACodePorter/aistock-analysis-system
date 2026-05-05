"""
Quant Engine Pydantic 请求/响应模型
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ===========================
# 请求模型
# ===========================

class TrainRequest(BaseModel):
    """训练请求"""
    symbol: str = Field(..., description="股票代码")
    task: str = Field("next_day_direction", description="预测任务")
    algo: str = Field("lightgbm", description="算法: lightgbm / xgboost")
    horizon: str = Field("5d", description="预测周期: 1d/5d/10d/20d")
    auto_select: bool = Field(False, description="是否自动选择最优算法")


class BatchTrainRequest(BaseModel):
    """批量训练请求"""
    task: str = Field("next_day_direction")
    algo: str = Field("lightgbm")
    horizon: str = Field("5d")
    pinned_only: bool = Field(True, description="仅训练已置顶股票")
    auto_select: bool = Field(False)


class PredictRequest(BaseModel):
    """预测请求"""
    symbol: str = Field(..., description="股票代码")
    task: str = Field("next_day_direction")
    algo: str = Field("lightgbm")
    horizon: str = Field("5d")


class BacktestRequest(BaseModel):
    """回测请求"""
    symbol: str = Field(..., description="股票代码")
    task: str = Field("next_day_direction")
    algo: str = Field("lightgbm")
    horizon: str = Field("5d")
    method: str = Field("holdout", description="回测方法: holdout / walk_forward")
    train_window: int = Field(500, ge=100, description="训练窗口大小（walk_forward）")
    test_window: int = Field(20, ge=5, description="测试窗口大小（walk_forward）")


class SignalRequest(BaseModel):
    """信号生成请求"""
    symbol: str = Field(..., description="股票代码")
    task: str = Field("next_day_direction")
    algo: str = Field("lightgbm")
    horizon: str = Field("5d")


class TopNRequest(BaseModel):
    """Top N 选股请求"""
    n: int = Field(10, ge=1, le=50)
    min_score: float = Field(60.0, ge=0, le=100)
    max_risk: float = Field(70.0, ge=0, le=100)
    actions: Optional[list[str]] = Field(None, description="限定信号类型")


# ===========================
# 响应模型
# ===========================

class TrainResult(BaseModel):
    """训练结果"""
    symbol: str
    task: str
    algo: str
    version: Optional[int] = None
    metrics: Optional[dict] = None
    feature_count: Optional[int] = None
    train_samples: Optional[int] = None
    status: str


class PredictionResponse(BaseModel):
    """预测结果"""
    symbol: str
    predict_date: str
    horizon: str
    direction_prob_up: Optional[float] = None
    direction_prob_down: Optional[float] = None
    predicted_direction: Optional[int] = None
    predicted_return: Optional[float] = None
    confidence: Optional[float] = None
    feature_importance: Optional[dict] = None


class SignalResponse(BaseModel):
    """信号结果"""
    symbol: str
    signal_date: str
    action: str
    score: float
    risk_score: float
    direction_prob_up: Optional[float] = None
    predicted_return: Optional[float] = None
    factors: Optional[dict] = None


class TopNResponse(BaseModel):
    """Top N 结果"""
    stocks: list[dict]
    total: int
    signal_date: Optional[str] = None


class BacktestResult(BaseModel):
    """回测结果"""
    run_id: Optional[int] = None
    symbol: str
    total_predictions: Optional[int] = None
    train_samples: Optional[int] = None
    test_samples: Optional[int] = None
    metrics: Optional[dict] = None
    error: Optional[str] = None


class ModelInfoResponse(BaseModel):
    """模型信息"""
    symbol: str
    task: str
    algo: str
    active_version: int
    status: str
    latest_metrics: Optional[dict] = None
    created_at: Optional[str] = None


class EvaluationResponse(BaseModel):
    """评估结果"""
    run_id: Optional[int] = None
    run_type: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    summary: Optional[dict] = None
    metrics: Optional[dict] = None


class AccuracyResponse(BaseModel):
    """预测准确率"""
    symbol: str
    horizon: str
    total: int
    correct: Optional[int] = None
    accuracy: Optional[float] = None
    avg_confidence: Optional[float] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
