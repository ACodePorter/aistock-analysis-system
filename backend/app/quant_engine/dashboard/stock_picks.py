"""
选股推荐页数据提供器

页面展示：
- Top N 推荐股票（按综合评分排序）
- 回测收益率
- 推荐理由（因子贡献）
- 历史推荐命中率
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select, and_, desc, func
from sqlalchemy.orm import Session

from ..models import QESignal, QEPrediction, QEEvaluationRun

logger = logging.getLogger(__name__)


class StockPicksProvider:
    """选股推荐页数据"""

    def __init__(self, session: Session):
        self.session = session

    def get_picks(
        self,
        n: int = 10,
        min_score: float = 60.0,
        max_risk: float = 70.0,
    ) -> dict:
        """获取选股推荐页数据"""
        return {
            "top_picks": self._top_picks(n, min_score, max_risk),
            "hit_rate": self._historical_hit_rate(),
            "backtest_summary": self._backtest_summary(),
        }

    def _top_picks(
        self, n: int, min_score: float, max_risk: float,
    ) -> list[dict]:
        """Top N 推荐股票"""
        latest_date = self.session.execute(
            select(func.max(QESignal.signal_date))
        ).scalar()

        if not latest_date:
            return []

        signals = self.session.execute(
            select(QESignal)
            .where(
                and_(
                    QESignal.signal_date == latest_date,
                    QESignal.score >= min_score,
                    QESignal.risk_score <= max_risk,
                    QESignal.action.in_(["strong_buy", "buy"]),
                )
            )
            .order_by(desc(QESignal.score))
            .limit(n)
        ).scalars().all()

        results = []
        for rank, s in enumerate(signals, 1):
            # 获取该股票的历史推荐命中率
            hit_rate = self._stock_hit_rate(s.symbol)

            results.append({
                "rank": rank,
                "symbol": s.symbol,
                "action": s.action,
                "score": s.score,
                "risk_score": s.risk_score,
                "direction_prob_up": s.direction_prob_up,
                "predicted_return": s.predicted_return,
                "signal_date": latest_date.isoformat(),
                "factors": s.factors_json,
                "historical_hit_rate": hit_rate,
            })

        return results

    def _stock_hit_rate(self, symbol: str, days: int = 60) -> Optional[float]:
        """单只股票的历史预测命中率"""
        cutoff = date.today() - timedelta(days=days)

        preds = self.session.execute(
            select(QEPrediction)
            .where(
                and_(
                    QEPrediction.symbol == symbol,
                    QEPrediction.predict_date >= cutoff,
                    QEPrediction.actual_direction.is_not(None),
                )
            )
        ).scalars().all()

        if not preds:
            return None

        correct = sum(
            1 for p in preds
            if (p.direction_prob_up and p.direction_prob_up > 0.5 and p.actual_direction == 1)
            or (p.direction_prob_up and p.direction_prob_up <= 0.5 and p.actual_direction == 0)
        )

        return correct / len(preds)

    def _historical_hit_rate(self, days: int = 30) -> dict:
        """全局历史推荐命中率"""
        cutoff = date.today() - timedelta(days=days)

        total = self.session.execute(
            select(func.count(QEPrediction.id))
            .where(
                and_(
                    QEPrediction.predict_date >= cutoff,
                    QEPrediction.actual_direction.is_not(None),
                )
            )
        ).scalar() or 0

        if total == 0:
            return {"total": 0, "correct": 0, "hit_rate": None}

        # 简化查询：direction_prob_up > 0.5 且 actual_direction = 1 即为正确
        correct = self.session.execute(
            select(func.count(QEPrediction.id))
            .where(
                and_(
                    QEPrediction.predict_date >= cutoff,
                    QEPrediction.actual_direction.is_not(None),
                    (
                        (QEPrediction.direction_prob_up > 0.5) & (QEPrediction.actual_direction == 1)
                    ) | (
                        (QEPrediction.direction_prob_up <= 0.5) & (QEPrediction.actual_direction == 0)
                    ),
                )
            )
        ).scalar() or 0

        return {
            "total": total,
            "correct": correct,
            "hit_rate": round(correct / total, 4) if total > 0 else None,
            "period_days": days,
        }

    def _backtest_summary(self) -> list[dict]:
        """最近的回测摘要"""
        runs = self.session.execute(
            select(QEEvaluationRun)
            .where(QEEvaluationRun.run_type.in_(["walk_forward", "holdout"]))
            .order_by(desc(QEEvaluationRun.created_at))
            .limit(10)
        ).scalars().all()

        return [
            {
                "run_id": r.id,
                "run_type": r.run_type,
                "symbols": r.symbols,
                "summary": r.summary_json,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]
