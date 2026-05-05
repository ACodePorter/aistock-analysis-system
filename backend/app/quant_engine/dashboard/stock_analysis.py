"""
单股票分析页数据提供器

页面展示：
- 预测 vs 实际对比图（时序）
- 特征重要性排名
- 新闻影响分析
- 模型版本历史
- 信号走势
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select, and_, desc, func
from sqlalchemy.orm import Session

from ..models import (
    QEStockModel, QEModelVersion, QEPrediction, QESignal,
)

logger = logging.getLogger(__name__)


class StockAnalysisProvider:
    """单股票分析页数据"""

    def __init__(self, session: Session):
        self.session = session

    def get_analysis(self, symbol: str, horizon: str = "5d", days: int = 90) -> dict:
        """获取单只股票的完整分析数据"""
        return {
            "symbol": symbol,
            "model_info": self._model_info(symbol),
            "prediction_vs_actual": self._prediction_vs_actual(symbol, horizon, days),
            "feature_importance": self._feature_importance(symbol),
            "model_versions": self._model_versions(symbol),
            "signal_trend": self._signal_trend(symbol, days),
        }

    def _model_info(self, symbol: str) -> Optional[dict]:
        """模型基本信息"""
        db_model = self.session.execute(
            select(QEStockModel)
            .where(QEStockModel.symbol == symbol)
            .order_by(desc(QEStockModel.updated_at))
            .limit(1)
        ).scalar_one_or_none()

        if not db_model:
            return None

        return {
            "task": db_model.task,
            "algo": db_model.algo,
            "active_version": db_model.active_version,
            "status": db_model.status,
            "created_at": db_model.created_at.isoformat() if db_model.created_at else None,
        }

    def _prediction_vs_actual(
        self, symbol: str, horizon: str, days: int,
    ) -> list[dict]:
        """预测 vs 实际收益时序对比数据"""
        cutoff = date.today() - timedelta(days=days)

        preds = self.session.execute(
            select(QEPrediction)
            .where(
                and_(
                    QEPrediction.symbol == symbol,
                    QEPrediction.horizon == horizon,
                    QEPrediction.predict_date >= cutoff,
                )
            )
            .order_by(QEPrediction.predict_date)
        ).scalars().all()

        return [
            {
                "date": p.predict_date.isoformat(),
                "prob_up": p.direction_prob_up,
                "predicted_return": p.predicted_return,
                "actual_return": p.actual_return,
                "actual_direction": p.actual_direction,
                "confidence": p.confidence,
                "correct": (
                    (p.direction_prob_up > 0.5 and p.actual_direction == 1) or
                    (p.direction_prob_up is not None and p.direction_prob_up <= 0.5 and p.actual_direction == 0)
                ) if p.actual_direction is not None and p.direction_prob_up is not None else None,
            }
            for p in preds
        ]

    def _feature_importance(self, symbol: str) -> Optional[dict]:
        """最新模型的特征重要性

        从最新一条预测的 explanation_json 中提取
        """
        pred = self.session.execute(
            select(QEPrediction)
            .where(
                and_(
                    QEPrediction.symbol == symbol,
                    QEPrediction.explanation_json.is_not(None),
                )
            )
            .order_by(desc(QEPrediction.created_at))
            .limit(1)
        ).scalar_one_or_none()

        if not pred or not pred.explanation_json:
            return None

        # 取 top 20 重要特征
        importance = pred.explanation_json
        if isinstance(importance, dict):
            sorted_features = sorted(importance.items(), key=lambda x: abs(x[1]), reverse=True)
            return {
                "features": [{"name": k, "importance": v} for k, v in sorted_features[:20]],
                "predict_date": pred.predict_date.isoformat(),
            }
        return None

    def _model_versions(self, symbol: str, limit: int = 10) -> list[dict]:
        """模型版本历史"""
        db_model = self.session.execute(
            select(QEStockModel)
            .where(QEStockModel.symbol == symbol)
            .limit(1)
        ).scalar_one_or_none()

        if not db_model:
            return []

        versions = self.session.execute(
            select(QEModelVersion)
            .where(QEModelVersion.stock_model_id == db_model.id)
            .order_by(desc(QEModelVersion.version))
            .limit(limit)
        ).scalars().all()

        return [
            {
                "version": v.version,
                "is_active": v.is_active,
                "train_samples": v.train_samples,
                "train_start": v.train_start.isoformat() if v.train_start else None,
                "train_end": v.train_end.isoformat() if v.train_end else None,
                "metrics": v.metrics_json,
                "features_count": len(v.features_used) if v.features_used else 0,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ]

    def _signal_trend(self, symbol: str, days: int) -> list[dict]:
        """信号走势数据"""
        cutoff = date.today() - timedelta(days=days)

        signals = self.session.execute(
            select(QESignal)
            .where(
                and_(
                    QESignal.symbol == symbol,
                    QESignal.signal_date >= cutoff,
                )
            )
            .order_by(QESignal.signal_date)
        ).scalars().all()

        return [
            {
                "date": s.signal_date.isoformat(),
                "action": s.action,
                "score": s.score,
                "risk_score": s.risk_score,
                "rank": s.rank,
            }
            for s in signals
        ]
