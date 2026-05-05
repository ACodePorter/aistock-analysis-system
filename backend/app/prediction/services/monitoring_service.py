"""
预测监控服务（MonitoringService）

职责：
1. 定期评估所有 symbol 的预测表现
2. 检测连续预测错误（超过阈值时触发 retrain 信号）
3. 检查特征有效性（feature decay detection）
4. 生成监控报告
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.models import (
    Forecast,
    PredictionEvaluation,
)
from ...core.constants import RETRAIN_TRIGGER_RULES
from .prediction_service import PredictionService

logger = logging.getLogger(__name__)


@dataclass
class SymbolHealth:
    """单只股票的模型健康状态"""
    symbol: str
    direction_accuracy: float = 0.0
    avg_error_pct: float = 0.0
    interval_hit_rate: float = 0.0
    interval_evaluations: int = 0
    consecutive_failures: int = 0
    total_evaluations: int = 0
    needs_retrain: bool = False
    retrain_reason: str = ""


@dataclass
class MonitoringReport:
    """全局监控报告"""
    timestamp: str = ""
    total_symbols: int = 0
    healthy: int = 0
    warning: int = 0
    critical: int = 0
    retrain_triggered: List[str] = field(default_factory=list)
    symbol_health: List[SymbolHealth] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  Prediction Monitoring Report",
            "=" * 60,
            f"  Time: {self.timestamp}",
            f"  Symbols: {self.total_symbols} total",
            f"  Healthy: {self.healthy} | Warning: {self.warning} | Critical: {self.critical}",
        ]
        if self.retrain_triggered:
            lines.append(f"  Retrain triggered: {', '.join(self.retrain_triggered)}")
        lines.append("")
        if self.symbol_health:
            lines.append(
                f"  {'Symbol':<12s} {'DirAcc':>8s} {'MAPE%':>8s} "
                f"{'IntHit':>8s} {'ConsecFail':>10s} {'Status':<15s}"
            )
            lines.append("  " + "-" * 66)
            for sh in sorted(self.symbol_health, key=lambda x: -x.consecutive_failures):
                status = "CRITICAL" if sh.needs_retrain else ("WARNING" if sh.consecutive_failures >= 2 else "OK")
                lines.append(
                    f"  {sh.symbol:<12s} {sh.direction_accuracy:>7.1%} "
                    f"{sh.avg_error_pct:>7.2f}% "
                    f"{sh.interval_hit_rate:>7.1%} "
                    f"{sh.consecutive_failures:>10d}   {status:<15s}"
                )
        lines.append("=" * 60)
        return "\n".join(lines)


class MonitoringService:
    """预测监控与失败检测

    参数：
        failure_threshold: 连续预测方向错误次数阈值，超过则触发 retrain
        accuracy_threshold: 方向准确率低于此值视为 warning
        lookback_days: 评估回溯天数
    """

    def __init__(
        self,
        session: Session,
        failure_threshold: Optional[int] = None,
        accuracy_threshold: Optional[float] = None,
        lookback_days: int = 30,
        mape_threshold_pct: Optional[float] = None,
        interval_hit_rate_threshold: Optional[float] = None,
    ):
        self.session = session
        self.failure_threshold = failure_threshold or int(RETRAIN_TRIGGER_RULES["consecutive_failures"])
        self.accuracy_threshold = accuracy_threshold or float(RETRAIN_TRIGGER_RULES["direction_accuracy_threshold"])
        self.lookback_days = lookback_days
        self.mape_threshold_pct = mape_threshold_pct or float(RETRAIN_TRIGGER_RULES["mape_threshold_pct"])
        self.interval_hit_rate_threshold = interval_hit_rate_threshold or float(RETRAIN_TRIGGER_RULES["interval_hit_rate_threshold"])
        self.min_evaluations = int(RETRAIN_TRIGGER_RULES.get("min_evaluations", 5))
        self.min_interval_evaluations = int(RETRAIN_TRIGGER_RULES.get("min_interval_evaluations", 3))
        self._pred_service = PredictionService(session)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run_health_check(self) -> MonitoringReport:
        """对所有有预测记录的 symbol 执行健康检查

        Returns: MonitoringReport
        """
        symbols = self._get_monitored_symbols()
        report = MonitoringReport(
            timestamp=datetime.utcnow().isoformat(),
            total_symbols=len(symbols),
        )

        for symbol in symbols:
            health = self._check_symbol(symbol)
            report.symbol_health.append(health)

            if health.needs_retrain:
                report.critical += 1
                report.retrain_triggered.append(symbol)
                self._log_event(
                    symbol=symbol,
                    event_type="failure_detected",
                    reason=health.retrain_reason,
                    details=asdict(health),
                )
            elif health.consecutive_failures >= 2 or health.direction_accuracy < self.accuracy_threshold:
                report.warning += 1
            else:
                report.healthy += 1

        logger.info(
            "Health check: %d symbols — %d healthy, %d warning, %d critical",
            report.total_symbols, report.healthy, report.warning, report.critical,
        )
        return report

    # ------------------------------------------------------------------
    # 特征衰减检测
    # ------------------------------------------------------------------

    def check_feature_decay(self, symbol: str) -> Dict:
        """检测特征有效性衰减

        对比最近 7 天 vs 前 30 天的预测误差，若误差显著增大则表明特征失效。
        """
        now = date.today()
        recent_cutoff = now - timedelta(days=7)
        history_cutoff = now - timedelta(days=self.lookback_days)

        recent_evals = self.session.execute(
            select(PredictionEvaluation).where(
                PredictionEvaluation.symbol == symbol,
                PredictionEvaluation.actual_price.isnot(None),
                PredictionEvaluation.target_date >= recent_cutoff,
            )
        ).scalars().all()

        older_evals = self.session.execute(
            select(PredictionEvaluation).where(
                PredictionEvaluation.symbol == symbol,
                PredictionEvaluation.actual_price.isnot(None),
                PredictionEvaluation.target_date >= history_cutoff,
                PredictionEvaluation.target_date < recent_cutoff,
            )
        ).scalars().all()

        recent_errors = [e.error_pct for e in recent_evals if e.error_pct is not None]
        older_errors = [e.error_pct for e in older_evals if e.error_pct is not None]

        if not recent_errors or not older_errors:
            return {"symbol": symbol, "decay_detected": False, "reason": "insufficient_data"}

        import numpy as np
        recent_avg = np.mean(recent_errors)
        older_avg = np.mean(older_errors)

        decay_ratio = recent_avg / (older_avg + 1e-9)
        decay_detected = decay_ratio > 1.5  # 误差增大 50% 以上

        result = {
            "symbol": symbol,
            "decay_detected": decay_detected,
            "recent_avg_error": float(recent_avg),
            "older_avg_error": float(older_avg),
            "decay_ratio": float(decay_ratio),
        }

        if decay_detected:
            self._log_event(
                symbol=symbol,
                event_type="feature_check",
                reason="feature_decay",
                details=result,
            )
            logger.warning("Feature decay detected for %s: ratio=%.2f", symbol, decay_ratio)

        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _get_monitored_symbols(self) -> List[str]:
        """获取所有有预测评估记录的 symbol"""
        cutoff = date.today() - timedelta(days=self.lookback_days)
        rows = self.session.execute(
            select(PredictionEvaluation.symbol)
            .where(PredictionEvaluation.target_date >= cutoff)
            .distinct()
        ).scalars().all()
        return list(set(rows))

    def _check_symbol(self, symbol: str) -> SymbolHealth:
        """检查单只股票的预测健康状态"""
        summary = self._pred_service.get_accuracy_summary(symbol, self.lookback_days)
        consec = self._pred_service.count_consecutive_failures(
            symbol,
            error_threshold_pct=self.mape_threshold_pct,
        )
        interval_hit_rate, interval_count = self._interval_hit_rate(symbol)

        health = SymbolHealth(
            symbol=symbol,
            direction_accuracy=summary.get("direction_accuracy", 0),
            avg_error_pct=summary.get("avg_error_pct", 0),
            interval_hit_rate=interval_hit_rate,
            interval_evaluations=interval_count,
            consecutive_failures=consec,
            total_evaluations=summary.get("total", 0),
        )

        reasons = []
        if consec >= self.failure_threshold:
            reasons.append(f"consecutive_failures={consec}")
        if health.total_evaluations >= self.min_evaluations:
            if health.direction_accuracy < self.accuracy_threshold:
                reasons.append(f"low_accuracy={health.direction_accuracy:.2%}")
            if health.avg_error_pct > self.mape_threshold_pct:
                reasons.append(f"high_mape={health.avg_error_pct:.2f}%")
        if (
            health.interval_evaluations >= self.min_interval_evaluations
            and health.interval_hit_rate < self.interval_hit_rate_threshold
        ):
            reasons.append(f"low_interval_hit={health.interval_hit_rate:.2%}")

        if reasons:
            health.needs_retrain = True
            health.retrain_reason = ";".join(reasons)

        return health

    def _interval_hit_rate(self, symbol: str) -> tuple[float, int]:
        """计算预测区间命中率。PredictionEvaluation 不存区间，回查 Forecast 原记录。"""
        cutoff = date.today() - timedelta(days=self.lookback_days)
        evals = self.session.execute(
            select(PredictionEvaluation).where(
                PredictionEvaluation.symbol == symbol,
                PredictionEvaluation.actual_price.isnot(None),
                PredictionEvaluation.target_date >= cutoff,
            )
        ).scalars().all()
        if not evals:
            return 0.0, 0

        forecasts = self.session.execute(
            select(Forecast).where(
                Forecast.symbol == symbol,
                Forecast.target_date >= cutoff,
            )
        ).scalars().all()
        forecast_map = {}
        for forecast in forecasts:
            pred_date = forecast.run_at.date() if isinstance(forecast.run_at, datetime) else forecast.run_at
            forecast_map[(pred_date, forecast.target_date, forecast.model)] = forecast

        hits = 0
        total = 0
        for evaluation in evals:
            forecast = forecast_map.get(
                (evaluation.prediction_date, evaluation.target_date, evaluation.model_name)
            )
            if not forecast or forecast.yhat_lower is None or forecast.yhat_upper is None:
                continue
            actual = float(evaluation.actual_price)
            lower = float(forecast.yhat_lower)
            upper = float(forecast.yhat_upper)
            if lower <= actual <= upper:
                hits += 1
            total += 1

        return (hits / total if total else 0.0), total

    def _log_event(
        self,
        symbol: Optional[str],
        event_type: str,
        reason: str,
        details: Optional[Dict] = None,
    ) -> None:
        """写入模型生命周期事件"""
        try:
            from ...core.models import ModelLifecycleEvent
            event = ModelLifecycleEvent(
                symbol=symbol,
                event_type=event_type,
                trigger_reason=reason,
                details_json=json.dumps(details, default=str) if details else None,
            )
            self.session.add(event)
            self.session.commit()
        except Exception as e:
            logger.warning("Failed to log lifecycle event: %s", e)
            try:
                self.session.rollback()
            except Exception:
                pass
