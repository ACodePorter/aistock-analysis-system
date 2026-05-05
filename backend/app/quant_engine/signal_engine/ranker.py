"""
股票排名器（Stock Ranker）

根据量化信号、模型预测、综合评分对股票进行排名和筛选。

功能：
1. Top N 选股推荐
2. 多维度排名（信号得分、预测收益、风险调整收益）
3. 行业分布均衡
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select, and_, desc, func
from sqlalchemy.orm import Session

from ..models import QESignal, QEPrediction, QESignalAction

logger = logging.getLogger(__name__)


class StockRanker:
    """股票排名器

    用法：
        ranker = StockRanker(session)
        top_stocks = ranker.get_top_n(n=10)
        ranked = ranker.get_ranked_signals()
    """

    def __init__(self, session: Session):
        self.session = session

    def get_top_n(
        self,
        n: int = 10,
        signal_date: Optional[date] = None,
        min_score: float = 60.0,
        max_risk: float = 70.0,
        actions: Optional[list[str]] = None,
    ) -> list[dict]:
        """获取 Top N 推荐股票

        Args:
            n:            返回数量
            signal_date:  信号日期（默认最近一天有信号的日期）
            min_score:    最低综合评分
            max_risk:     最大风险评分
            actions:      限定信号类型

        Returns:
            Top N 股票列表，按 score 降序
        """
        if signal_date is None:
            signal_date = self._get_latest_signal_date()
            if signal_date is None:
                return []

        query = (
            select(QESignal)
            .where(
                and_(
                    QESignal.signal_date == signal_date,
                    QESignal.score >= min_score,
                    QESignal.risk_score <= max_risk,
                )
            )
        )

        if actions:
            query = query.where(QESignal.action.in_(actions))

        query = query.order_by(desc(QESignal.score)).limit(n)
        signals = self.session.execute(query).scalars().all()

        return [
            {
                "rank": idx + 1,
                "symbol": s.symbol,
                "action": s.action,
                "score": s.score,
                "risk_score": s.risk_score,
                "direction_prob_up": s.direction_prob_up,
                "predicted_return": s.predicted_return,
                "signal_date": s.signal_date.isoformat(),
                "factors": s.factors_json,
            }
            for idx, s in enumerate(signals)
        ]

    def get_ranked_signals(
        self,
        signal_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[dict]:
        """获取全部已排名信号"""
        if signal_date is None:
            signal_date = self._get_latest_signal_date()
            if signal_date is None:
                return []

        signals = self.session.execute(
            select(QESignal)
            .where(QESignal.signal_date == signal_date)
            .order_by(QESignal.rank.asc().nullslast())
            .limit(limit)
        ).scalars().all()

        return [
            {
                "rank": s.rank,
                "symbol": s.symbol,
                "action": s.action,
                "score": s.score,
                "risk_score": s.risk_score,
                "direction_prob_up": s.direction_prob_up,
                "predicted_return": s.predicted_return,
                "signal_date": s.signal_date.isoformat(),
            }
            for s in signals
        ]

    def get_signal_distribution(
        self,
        signal_date: Optional[date] = None,
    ) -> dict:
        """获取信号分布统计"""
        if signal_date is None:
            signal_date = self._get_latest_signal_date()
            if signal_date is None:
                return {}

        rows = self.session.execute(
            select(QESignal.action, func.count(QESignal.id))
            .where(QESignal.signal_date == signal_date)
            .group_by(QESignal.action)
        ).all()

        distribution = {r[0]: r[1] for r in rows}
        total = sum(distribution.values())

        return {
            "signal_date": signal_date.isoformat(),
            "total": total,
            "distribution": distribution,
            "avg_score": self.session.execute(
                select(func.avg(QESignal.score))
                .where(QESignal.signal_date == signal_date)
            ).scalar() or 0,
        }

    def get_stock_signal_history(
        self,
        symbol: str,
        days: int = 30,
    ) -> list[dict]:
        """获取单只股票的信号历史"""
        cutoff = date.today() - timedelta(days=days)

        signals = self.session.execute(
            select(QESignal)
            .where(
                and_(
                    QESignal.symbol == symbol,
                    QESignal.signal_date >= cutoff,
                )
            )
            .order_by(desc(QESignal.signal_date))
        ).scalars().all()

        return [
            {
                "signal_date": s.signal_date.isoformat(),
                "action": s.action,
                "score": s.score,
                "risk_score": s.risk_score,
                "rank": s.rank,
                "direction_prob_up": s.direction_prob_up,
            }
            for s in signals
        ]

    def _get_latest_signal_date(self) -> Optional[date]:
        """获取最近有信号的日期"""
        result = self.session.execute(
            select(func.max(QESignal.signal_date))
        ).scalar()
        return result
