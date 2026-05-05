"""
AI 总览页数据提供器

页面展示：
- 观察列表全部股票 + 最新预测 + 准确率 + 信号
- 信号分布饼图
- 模型健康度概览
- 最近评估运行
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func, desc, and_
from sqlalchemy.orm import Session

from ..models import (
    QEStockModel, QESignal, QEPrediction,
    QEEvaluationRun, QETrainingJob,
)

logger = logging.getLogger(__name__)


class OverviewDataProvider:
    """AI 总览页数据"""

    def __init__(self, session: Session):
        self.session = session

    def get_overview(self) -> dict:
        """获取总览页全部数据"""
        return {
            "model_stats": self._model_stats(),
            "signal_summary": self._signal_summary(),
            "training_activity": self._training_activity(),
            "recent_predictions": self._recent_predictions(),
        }

    def _model_stats(self) -> dict:
        """模型统计"""
        total = self.session.execute(
            select(func.count(QEStockModel.id))
        ).scalar() or 0

        active = self.session.execute(
            select(func.count(QEStockModel.id))
            .where(QEStockModel.status == "active")
        ).scalar() or 0

        return {
            "total_models": total,
            "active_models": active,
            "algo_distribution": self._algo_distribution(),
        }

    def _algo_distribution(self) -> dict:
        """算法分布"""
        rows = self.session.execute(
            select(QEStockModel.algo, func.count(QEStockModel.id))
            .group_by(QEStockModel.algo)
        ).all()
        return {r[0]: r[1] for r in rows}

    def _signal_summary(self) -> dict:
        """最近一日信号摘要"""
        latest_date = self.session.execute(
            select(func.max(QESignal.signal_date))
        ).scalar()

        if not latest_date:
            return {"date": None, "total": 0, "distribution": {}}

        rows = self.session.execute(
            select(QESignal.action, func.count(QESignal.id))
            .where(QESignal.signal_date == latest_date)
            .group_by(QESignal.action)
        ).all()

        avg_score = self.session.execute(
            select(func.avg(QESignal.score))
            .where(QESignal.signal_date == latest_date)
        ).scalar()

        return {
            "date": latest_date.isoformat(),
            "total": sum(r[1] for r in rows),
            "distribution": {r[0]: r[1] for r in rows},
            "avg_score": round(float(avg_score or 0), 2),
        }

    def _training_activity(self) -> dict:
        """训练活动统计"""
        from datetime import date, timedelta
        cutoff = date.today() - timedelta(days=7)

        recent = self.session.execute(
            select(func.count(QETrainingJob.id))
            .where(QETrainingJob.started_at >= cutoff)
        ).scalar() or 0

        completed = self.session.execute(
            select(func.count(QETrainingJob.id))
            .where(
                and_(
                    QETrainingJob.started_at >= cutoff,
                    QETrainingJob.status == "completed",
                )
            )
        ).scalar() or 0

        return {
            "last_7d_total": recent,
            "last_7d_completed": completed,
        }

    def _recent_predictions(self, limit: int = 20) -> list[dict]:
        """最近的预测记录"""
        preds = self.session.execute(
            select(QEPrediction)
            .order_by(desc(QEPrediction.created_at))
            .limit(limit)
        ).scalars().all()

        return [
            {
                "symbol": p.symbol,
                "predict_date": p.predict_date.isoformat(),
                "horizon": p.horizon,
                "direction_prob_up": p.direction_prob_up,
                "predicted_return": p.predicted_return,
                "confidence": p.confidence,
                "actual_return": p.actual_return,
                "actual_direction": p.actual_direction,
            }
            for p in preds
        ]
