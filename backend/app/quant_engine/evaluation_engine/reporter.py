"""
评估报告生成器（Evaluation Reporter）

生成人类可读的评估报告，提供给 Dashboard 和 API 层。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy import select, and_, desc
from sqlalchemy.orm import Session

from ..models import QEEvaluationRun, QEEvaluationMetric, QEPrediction

logger = logging.getLogger(__name__)


class EvaluationReporter:
    """评估报告生成器"""

    def __init__(self, session: Session):
        self.session = session

    def get_latest_evaluation(
        self,
        symbol: str,
        horizon: str = "5d",
    ) -> Optional[dict]:
        """获取某只股票最近一次评估结果"""
        run = self.session.execute(
            select(QEEvaluationRun)
            .where(
                QEEvaluationRun.symbols.contains({"symbols": [symbol]})
            )
            .order_by(desc(QEEvaluationRun.created_at))
            .limit(1)
        ).scalar_one_or_none()

        if not run:
            return None

        metrics = self.session.execute(
            select(QEEvaluationMetric)
            .where(
                and_(
                    QEEvaluationMetric.evaluation_run_id == run.id,
                    QEEvaluationMetric.symbol == symbol,
                )
            )
        ).scalars().all()

        return {
            "run_id": run.id,
            "run_type": run.run_type,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "summary": run.summary_json,
            "metrics": {m.metric_name: m.metric_value for m in metrics},
        }

    def get_prediction_accuracy(
        self,
        symbol: str,
        horizon: str = "5d",
        days: int = 60,
    ) -> dict:
        """计算近 N 天的预测准确度（基于已回填的预测记录）"""
        from datetime import timedelta

        cutoff = date.today() - timedelta(days=days)

        preds = self.session.execute(
            select(QEPrediction)
            .where(
                and_(
                    QEPrediction.symbol == symbol,
                    QEPrediction.horizon == horizon,
                    QEPrediction.predict_date >= cutoff,
                    QEPrediction.actual_direction.is_not(None),
                )
            )
            .order_by(QEPrediction.predict_date)
        ).scalars().all()

        if not preds:
            return {
                "symbol": symbol,
                "horizon": horizon,
                "total": 0,
                "accuracy": None,
                "avg_confidence": None,
            }

        correct = sum(
            1 for p in preds
            if (p.direction_prob_up and p.direction_prob_up > 0.5 and p.actual_direction == 1)
            or (p.direction_prob_up and p.direction_prob_up <= 0.5 and p.actual_direction == 0)
        )

        return {
            "symbol": symbol,
            "horizon": horizon,
            "total": len(preds),
            "correct": correct,
            "accuracy": correct / len(preds),
            "avg_confidence": sum(
                (p.confidence or 0.5) for p in preds
            ) / len(preds),
            "period_start": preds[0].predict_date.isoformat(),
            "period_end": preds[-1].predict_date.isoformat(),
        }

    def get_all_evaluations(
        self,
        limit: int = 20,
    ) -> list[dict]:
        """获取最近的评估运行记录"""
        runs = self.session.execute(
            select(QEEvaluationRun)
            .order_by(desc(QEEvaluationRun.created_at))
            .limit(limit)
        ).scalars().all()

        return [
            {
                "run_id": r.id,
                "run_type": r.run_type,
                "scope": r.scope,
                "symbols": r.symbols,
                "status": r.status,
                "summary": r.summary_json,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]
