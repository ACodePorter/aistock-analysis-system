"""
Quant Engine REST API 路由

前缀: /api/quant

端点：
- POST /train          单股票训练
- POST /train/batch    批量训练
- POST /predict        单股票预测
- POST /backtest       回测
- POST /signal         生成信号
- GET  /signals/top    Top N 选股
- GET  /signals/ranked 全部排名
- GET  /signals/distribution 信号分布
- GET  /model/{symbol} 模型信息
- GET  /evaluation/{symbol} 评估结果
- GET  /accuracy/{symbol}   预测准确率
- GET  /signal-history/{symbol} 信号历史
- POST /backfill       预测回填
- GET  /dashboard/overview  AI总览
- GET  /dashboard/stock/{symbol} 单股票分析
- GET  /health         健康检查
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, and_, desc

from ...core.db import SessionLocal
from ..models import QEStockModel, QEModelVersion, QESignal
from ..model_engine.trainer import TrainingOrchestrator
from ..model_engine.registry import ModelManager
from ..feature_engineering.pipeline import FeaturePipeline
from ..evaluation_engine.backtester import Backtester
from ..evaluation_engine.reporter import EvaluationReporter
from ..signal_engine.generator import SignalGenerator
from ..signal_engine.ranker import StockRanker

from .schemas import (
    TrainRequest, BatchTrainRequest, TrainResult,
    PredictRequest, PredictionResponse,
    BacktestRequest, BacktestResult,
    SignalRequest, SignalResponse,
    TopNRequest, TopNResponse,
    ModelInfoResponse, EvaluationResponse, AccuracyResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quant", tags=["quant-engine"])


# ===========================
# 训练
# ===========================

@router.post("/train", response_model=TrainResult)
def train_model(req: TrainRequest):
    """训练单只股票模型"""
    with SessionLocal() as session:
        orchestrator = TrainingOrchestrator(session)
        result = orchestrator.train_single(
            symbol=req.symbol,
            task=req.task,
            algo=req.algo,
            horizon=req.horizon,
            auto_select=req.auto_select,
        )
        return TrainResult(**result)


@router.post("/train/batch")
def train_batch(req: BatchTrainRequest):
    """批量训练所有观察列表股票"""
    with SessionLocal() as session:
        orchestrator = TrainingOrchestrator(session)
        results = orchestrator.train_all(
            task=req.task,
            algo=req.algo,
            horizon=req.horizon,
            pinned_only=req.pinned_only,
            auto_select=req.auto_select,
        )
        completed = sum(1 for r in results if r.get("status") == "completed")
        return {
            "total": len(results),
            "completed": completed,
            "failed": len(results) - completed,
            "results": results,
        }


# ===========================
# 预测
# ===========================

@router.post("/predict", response_model=PredictionResponse)
def predict(req: PredictRequest):
    """对单只股票进行预测"""
    with SessionLocal() as session:
        pipeline = FeaturePipeline(session)
        manager = ModelManager(session)

        features, _feat_names = pipeline.build_latest(symbol=req.symbol)
        if features is None or features.empty:
            raise HTTPException(status_code=400, detail=f"特征数据不足: {req.symbol}")

        model, db_model = manager.get_or_create_model(req.symbol, req.task, req.algo)
        if model._model is None:
            raise HTTPException(status_code=404, detail=f"未找到可用模型: {req.symbol}")

        pred = model.get_prediction_result(
            features, symbol=req.symbol,
            predict_date=date.today().isoformat(),
            horizon=req.horizon,
        )

        return PredictionResponse(
            symbol=pred.symbol,
            predict_date=pred.predict_date,
            horizon=pred.horizon,
            direction_prob_up=pred.direction_prob_up,
            direction_prob_down=pred.direction_prob_down,
            predicted_direction=pred.predicted_direction,
            predicted_return=pred.predicted_return,
            confidence=pred.confidence,
            feature_importance=pred.feature_importance,
        )


# ===========================
# 回测
# ===========================

@router.post("/backtest", response_model=BacktestResult)
def backtest(req: BacktestRequest):
    """对单只股票进行回测"""
    with SessionLocal() as session:
        bt = Backtester(session)
        if req.method == "walk_forward":
            result = bt.walk_forward(
                symbol=req.symbol,
                task=req.task,
                algo=req.algo,
                horizon=req.horizon,
                train_window=req.train_window,
                test_window=req.test_window,
            )
        else:
            result = bt.holdout_evaluation(
                symbol=req.symbol,
                task=req.task,
                algo=req.algo,
                horizon=req.horizon,
            )
        return BacktestResult(**result)


# ===========================
# 信号
# ===========================

@router.post("/signal", response_model=SignalResponse)
def generate_signal(req: SignalRequest):
    """为单只股票生成信号"""
    with SessionLocal() as session:
        gen = SignalGenerator(session)
        result = gen.generate_signal(
            symbol=req.symbol,
            task=req.task,
            algo=req.algo,
            horizon=req.horizon,
        )
        if not result:
            raise HTTPException(status_code=400, detail=f"信号生成失败: {req.symbol}")
        return SignalResponse(
            symbol=result["symbol"],
            signal_date=result["signal_date"].isoformat(),
            action=result["action"],
            score=result["score"],
            risk_score=result["risk_score"],
            direction_prob_up=result.get("direction_prob_up"),
            predicted_return=result.get("predicted_return"),
            factors=result.get("factors_json"),
        )


@router.post("/signals/generate-all")
def generate_all_signals(
    task: str = Query("next_day_direction"),
    algo: str = Query("lightgbm"),
    horizon: str = Query("5d"),
    pinned_only: bool = Query(True),
):
    """批量生成所有观察列表股票的信号"""
    with SessionLocal() as session:
        gen = SignalGenerator(session)
        results = gen.generate_all_signals(task, algo, horizon, pinned_only)
        return {
            "total": len(results),
            "signals": results,
        }


@router.get("/signals/top", response_model=TopNResponse)
def get_top_signals(
    n: int = Query(10, ge=1, le=50),
    min_score: float = Query(60.0),
    max_risk: float = Query(70.0),
):
    """获取 Top N 推荐股票"""
    with SessionLocal() as session:
        ranker = StockRanker(session)
        top = ranker.get_top_n(n=n, min_score=min_score, max_risk=max_risk)
        return TopNResponse(
            stocks=top,
            total=len(top),
            signal_date=top[0]["signal_date"] if top else None,
        )


@router.get("/signals/ranked")
def get_ranked_signals(limit: int = Query(50, ge=1, le=200)):
    """获取全部排名信号"""
    with SessionLocal() as session:
        ranker = StockRanker(session)
        return ranker.get_ranked_signals(limit=limit)


@router.get("/signals/distribution")
def get_signal_distribution():
    """获取信号分布统计"""
    with SessionLocal() as session:
        ranker = StockRanker(session)
        return ranker.get_signal_distribution()


# ===========================
# 模型信息
# ===========================

@router.get("/model/{symbol}", response_model=ModelInfoResponse)
def get_model_info(
    symbol: str,
    task: str = Query("next_day_direction"),
    algo: str = Query("lightgbm"),
):
    """获取股票的模型信息"""
    with SessionLocal() as session:
        db_model = session.execute(
            select(QEStockModel).where(
                and_(
                    QEStockModel.symbol == symbol,
                    QEStockModel.task == task,
                    QEStockModel.algo == algo,
                )
            )
        ).scalar_one_or_none()

        if not db_model:
            raise HTTPException(status_code=404, detail=f"未找到模型: {symbol}")

        # 获取最新版本的 metrics
        latest_version = session.execute(
            select(QEModelVersion)
            .where(
                and_(
                    QEModelVersion.stock_model_id == db_model.id,
                    QEModelVersion.is_active == True,  # noqa: E712
                )
            )
            .order_by(desc(QEModelVersion.version))
            .limit(1)
        ).scalar_one_or_none()

        return ModelInfoResponse(
            symbol=db_model.symbol,
            task=db_model.task,
            algo=db_model.algo,
            active_version=db_model.active_version,
            status=db_model.status,
            latest_metrics=latest_version.metrics_json if latest_version else None,
            created_at=db_model.created_at.isoformat() if db_model.created_at else None,
        )


# ===========================
# 评估
# ===========================

@router.get("/evaluation/{symbol}", response_model=EvaluationResponse)
def get_evaluation(
    symbol: str,
    horizon: str = Query("5d"),
):
    """获取股票最新评估结果"""
    with SessionLocal() as session:
        reporter = EvaluationReporter(session)
        result = reporter.get_latest_evaluation(symbol, horizon)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到评估结果: {symbol}")
        return EvaluationResponse(**result)


@router.get("/accuracy/{symbol}", response_model=AccuracyResponse)
def get_accuracy(
    symbol: str,
    horizon: str = Query("5d"),
    days: int = Query(60, ge=7, le=365),
):
    """获取股票预测准确率"""
    with SessionLocal() as session:
        reporter = EvaluationReporter(session)
        result = reporter.get_prediction_accuracy(symbol, horizon, days)
        return AccuracyResponse(**result)


@router.get("/evaluations")
def list_evaluations(limit: int = Query(20, ge=1, le=100)):
    """获取评估运行历史"""
    with SessionLocal() as session:
        reporter = EvaluationReporter(session)
        return reporter.get_all_evaluations(limit)


# ===========================
# 信号历史
# ===========================

@router.get("/signal-history/{symbol}")
def get_signal_history(
    symbol: str,
    days: int = Query(30, ge=1, le=365),
):
    """获取单只股票的信号历史"""
    with SessionLocal() as session:
        ranker = StockRanker(session)
        return ranker.get_stock_signal_history(symbol, days)


# ===========================
# 预测回填
# ===========================

@router.post("/backfill")
def backfill_predictions(symbol: Optional[str] = Query(None)):
    """回填预测 vs 实际结果"""
    with SessionLocal() as session:
        bt = Backtester(session)
        updated = bt.backfill_actuals(symbol)
        return {"updated": updated}


# ===========================
# Dashboard 聚合接口
# ===========================

@router.get("/dashboard/overview")
def dashboard_overview():
    """AI 总览页数据

    返回：
    - 所有观察列表股票的最新信号
    - 信号分布统计
    - 模型整体准确率
    - Top 买入/卖出推荐
    """
    with SessionLocal() as session:
        ranker = StockRanker(session)
        reporter = EvaluationReporter(session)

        # 信号排名
        ranked = ranker.get_ranked_signals(limit=100)
        distribution = ranker.get_signal_distribution()
        top_buy = ranker.get_top_n(
            n=5, min_score=65,
            actions=["strong_buy", "buy"],
        )
        top_sell = ranker.get_top_n(
            n=5, min_score=0, max_risk=100,
            actions=["strong_sell", "sell"],
        )

        return {
            "signals": ranked,
            "distribution": distribution,
            "top_buy": top_buy,
            "top_sell": top_sell,
            "recent_evaluations": reporter.get_all_evaluations(limit=5),
        }


@router.get("/dashboard/stock/{symbol}")
def dashboard_stock(
    symbol: str,
    horizon: str = Query("5d"),
):
    """单股票分析页数据

    返回：
    - 模型信息
    - 最新预测
    - 最新信号
    - 信号历史
    - 预测准确率
    - 评估结果
    """
    with SessionLocal() as session:
        ranker = StockRanker(session)
        reporter = EvaluationReporter(session)

        # 模型信息
        db_model = session.execute(
            select(QEStockModel)
            .where(QEStockModel.symbol == symbol)
            .limit(1)
        ).scalar_one_or_none()

        model_info = None
        if db_model:
            model_info = {
                "task": db_model.task,
                "algo": db_model.algo,
                "active_version": db_model.active_version,
                "status": db_model.status,
            }

        # 最新信号
        latest_signal = session.execute(
            select(QESignal)
            .where(QESignal.symbol == symbol)
            .order_by(desc(QESignal.signal_date))
            .limit(1)
        ).scalar_one_or_none()

        signal_data = None
        if latest_signal:
            signal_data = {
                "action": latest_signal.action,
                "score": latest_signal.score,
                "risk_score": latest_signal.risk_score,
                "signal_date": latest_signal.signal_date.isoformat(),
                "factors": latest_signal.factors_json,
            }

        return {
            "symbol": symbol,
            "model": model_info,
            "latest_signal": signal_data,
            "signal_history": ranker.get_stock_signal_history(symbol, days=30),
            "accuracy": reporter.get_prediction_accuracy(symbol, horizon),
            "evaluation": reporter.get_latest_evaluation(symbol, horizon),
        }


# ===========================
# 健康检查
# ===========================

@router.get("/health")
def health_check():
    """量化引擎健康检查"""
    return {
        "status": "ok",
        "module": "quant_engine",
        "version": "0.1.0",
    }
