"""
持续学习闭环调度器（ContinuousLearningLoop）

完整闭环：
  预测 → 记录 → 回填实际 → 监控 → 检测失败 → 再训练 → 因子扩展 A/B 测试

本模块提供两个入口函数供调度器调用：
1. run_evaluation_loop()  — 轻量级，每日运行：同步预测、回填、健康检查
2. run_retrain_loop()     — 重量级，每周或按需：对失败 symbol 执行再训练 + A/B 测试
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

from ...core.constants import RETRAIN_TRIGGER_RULES
from .prediction_service import PredictionService
from .monitoring_service import MonitoringService, MonitoringReport
from .training_service import TrainingService, RetrainResult, ABTestResult

logger = logging.getLogger(__name__)

_LOCAL_RETRAIN_COOLDOWN: Dict[str, float] = {}
_LOCAL_RETRAIN_LOCKS: Dict[str, float] = {}


@dataclass
class LearningCycleReport:
    """单次学习闭环的完整报告"""
    timestamp: str = ""
    phase: str = ""  # evaluation / retrain

    # 评估阶段
    forecasts_synced: int = 0
    actuals_backfilled: int = 0
    monitoring: Optional[MonitoringReport] = None

    # 再训练阶段
    retrain_results: List[RetrainResult] = field(default_factory=list)
    ab_test_results: List[ABTestResult] = field(default_factory=list)
    feature_decay_symbols: List[str] = field(default_factory=list)
    auto_retrain_triggered: List[str] = field(default_factory=list)
    auto_retrain_skipped: Dict[str, str] = field(default_factory=dict)

    total_time_sec: float = 0.0

    def summary(self) -> str:
        lines = [
            "=" * 65,
            "  Continuous Learning Cycle Report",
            "=" * 65,
            f"  Time: {self.timestamp}",
            f"  Phase: {self.phase}",
            f"  Duration: {self.total_time_sec:.1f}s",
            "",
        ]

        if self.phase in ("evaluation", "full"):
            lines.append(f"  Forecasts synced: {self.forecasts_synced}")
            lines.append(f"  Actuals backfilled: {self.actuals_backfilled}")
            if self.monitoring:
                lines.append(f"  Symbols monitored: {self.monitoring.total_symbols}")
                lines.append(
                    f"  Health: {self.monitoring.healthy} OK / "
                    f"{self.monitoring.warning} warn / "
                    f"{self.monitoring.critical} critical"
                )
                if self.monitoring.retrain_triggered:
                    lines.append(f"  Retrain needed: {', '.join(self.monitoring.retrain_triggered)}")
                if self.auto_retrain_triggered:
                    lines.append(f"  Auto retrain triggered: {', '.join(self.auto_retrain_triggered)}")
                if self.auto_retrain_skipped:
                    skipped = ", ".join(f"{k}({v})" for k, v in self.auto_retrain_skipped.items())
                    lines.append(f"  Auto retrain skipped: {skipped}")

        if self.phase in ("retrain", "full"):
            lines.append("")
            if self.retrain_results:
                lines.append("  --- Retrain Results ---")
                for rr in self.retrain_results:
                    status = "OK" if rr.success else "FAIL"
                    imp = "improved" if rr.improved else "no change"
                    lines.append(
                        f"  {rr.symbol:<12s} [{status}] "
                        f"score: {rr.score_before:.4f} → {rr.score_after:.4f} ({imp})"
                    )
            if self.ab_test_results:
                lines.append("")
                lines.append("  --- A/B Test Results ---")
                for ab in self.ab_test_results:
                    lines.append(
                        f"  {ab.symbol:<12s} baseline={ab.baseline_score:.4f} "
                        f"candidate={ab.candidate_score:.4f} → {ab.winner}"
                    )
            if self.feature_decay_symbols:
                lines.append("")
                lines.append(f"  Feature decay: {', '.join(self.feature_decay_symbols)}")

        lines.append("=" * 65)
        return "\n".join(lines)


class ContinuousLearningLoop:
    """持续学习闭环控制器

    参数：
        failure_threshold:     连续错误阈值（默认 3 次触发再训练）
        accuracy_threshold:    准确率低于此值触发 warning
        retrain_min_rounds:    再训练最小轮数
        ab_test_on_retrain:    再训练时是否同时执行 A/B 测试
        model_name / task_type / horizon: 默认模型配置
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        accuracy_threshold: float = 0.45,
        retrain_min_rounds: int = 30,
        ab_test_on_retrain: bool = True,
        auto_retrain_on_critical: Optional[bool] = None,
        model_name: str = "lightgbm",
        task_type: str = "classification",
        horizon: str = "5d",
    ):
        self.failure_threshold = failure_threshold or int(RETRAIN_TRIGGER_RULES["consecutive_failures"])
        self.accuracy_threshold = accuracy_threshold or float(RETRAIN_TRIGGER_RULES["direction_accuracy_threshold"])
        self.retrain_min_rounds = retrain_min_rounds
        self.ab_test_on_retrain = ab_test_on_retrain
        env_auto = os.getenv("PREDICTION_AUTO_RETRAIN_ENABLED")
        if auto_retrain_on_critical is None and env_auto is not None:
            auto_retrain_on_critical = env_auto.lower() in ("1", "true", "yes", "on")
        self.auto_retrain_on_critical = (
            bool(RETRAIN_TRIGGER_RULES.get("auto_retrain_enabled", True))
            if auto_retrain_on_critical is None
            else auto_retrain_on_critical
        )
        self.cooldown_seconds = int(float(RETRAIN_TRIGGER_RULES.get("cooldown_hours", 24)) * 3600)
        self.lock_ttl_seconds = int(RETRAIN_TRIGGER_RULES.get("retrain_lock_ttl_seconds", 7200))
        self.model_name = model_name
        self.task_type = task_type
        self.horizon = horizon

    # ------------------------------------------------------------------
    # 入口 1: 评估循环（轻量，每日）
    # ------------------------------------------------------------------

    def run_evaluation_loop(self) -> LearningCycleReport:
        """评估循环：同步预测 → 回填 → 健康检查

        适合每日收盘后运行，耗时短。
        """
        t0 = time.time()
        report = LearningCycleReport(
            timestamp=datetime.utcnow().isoformat(),
            phase="evaluation",
        )

        try:
            from ...core.db import SessionLocal

            with SessionLocal() as session:
                pred_svc = PredictionService(session)
                mon_svc = MonitoringService(
                    session,
                    failure_threshold=self.failure_threshold,
                    accuracy_threshold=self.accuracy_threshold,
                )

                # Step 1: 同步 forecasts → prediction_evaluations
                report.forecasts_synced = pred_svc.sync_forecasts(lookback_days=7)

                # Step 2: 回填实际价格
                report.actuals_backfilled = pred_svc.backfill_actuals()

                # Step 3: 健康检查
                report.monitoring = mon_svc.run_health_check()

                # Step 4: 特征衰减检测
                if report.monitoring:
                    for sh in report.monitoring.symbol_health:
                        if sh.total_evaluations >= 5:
                            decay = mon_svc.check_feature_decay(sh.symbol)
                            if decay.get("decay_detected"):
                                report.feature_decay_symbols.append(sh.symbol)

                if self.auto_retrain_on_critical and report.monitoring:
                    trigger_reasons = {
                        sh.symbol: sh.retrain_reason
                        for sh in report.monitoring.symbol_health
                        if sh.needs_retrain
                    }
                    retrain_symbols = self._select_retrain_symbols(
                        report.monitoring.retrain_triggered,
                        trigger_reasons,
                        report.auto_retrain_skipped,
                    )
                    if retrain_symbols:
                        report.auto_retrain_triggered = retrain_symbols
                        self._log_retrain_triggers(session, retrain_symbols, trigger_reasons)

            if report.auto_retrain_triggered:
                retrain_report = self.run_retrain_loop(force_symbols=report.auto_retrain_triggered)
                report.retrain_results.extend(retrain_report.retrain_results)
                report.ab_test_results.extend(retrain_report.ab_test_results)
                for symbol in report.auto_retrain_triggered:
                    self._release_retrain_lock(symbol)

        except Exception as e:
            logger.error("Evaluation loop failed: %s", e, exc_info=True)
            for symbol in report.auto_retrain_triggered:
                self._release_retrain_lock(symbol)

        report.total_time_sec = time.time() - t0
        logger.info("Evaluation loop done in %.1fs", report.total_time_sec)
        return report

    # ------------------------------------------------------------------
    # 入口 2: 再训练循环（重量，每周或按需）
    # ------------------------------------------------------------------

    def run_retrain_loop(
        self,
        force_symbols: Optional[List[str]] = None,
    ) -> LearningCycleReport:
        """再训练循环：对需要再训练的 symbol 执行全量重训 + A/B 测试

        如果 force_symbols 非空，则强制对这些 symbol 重训（忽略健康检查）。
        否则先跑评估循环确定需要再训练的 symbol。
        """
        t0 = time.time()
        report = LearningCycleReport(
            timestamp=datetime.utcnow().isoformat(),
            phase="retrain",
        )

        try:
            from ...core.db import SessionLocal

            # 确定需要再训练的 symbol
            retrain_symbols: List[str] = []

            if force_symbols:
                retrain_symbols = list(force_symbols)
            else:
                eval_report = self.run_evaluation_loop()
                report.forecasts_synced = eval_report.forecasts_synced
                report.actuals_backfilled = eval_report.actuals_backfilled
                report.monitoring = eval_report.monitoring
                report.feature_decay_symbols = eval_report.feature_decay_symbols
                report.phase = "full"

                if eval_report.monitoring:
                    retrain_symbols = list(eval_report.monitoring.retrain_triggered)
                # 特征衰减的也加入
                for s in eval_report.feature_decay_symbols:
                    if s not in retrain_symbols:
                        retrain_symbols.append(s)

            if not retrain_symbols:
                logger.info("No symbols need retraining")
                report.total_time_sec = time.time() - t0
                return report

            logger.info("Retraining %d symbols: %s", len(retrain_symbols), retrain_symbols)

            with SessionLocal() as session:
                train_svc = TrainingService(
                    session,
                    model_name=self.model_name,
                    task_type=self.task_type,
                    horizon=self.horizon,
                    use_optimizer=True,
                )

                for symbol in retrain_symbols:
                    # 再训练
                    rr = train_svc.retrain(
                        symbol,
                        reason="continuous_learning",
                        min_rounds=self.retrain_min_rounds,
                    )
                    report.retrain_results.append(rr)

                    # A/B 测试
                    if self.ab_test_on_retrain:
                        ab = train_svc.ab_test_features(symbol, expanded_top_n=50)
                        report.ab_test_results.append(ab)

        except Exception as e:
            logger.error("Retrain loop failed: %s", e, exc_info=True)

        report.total_time_sec = time.time() - t0
        logger.info("Retrain loop done in %.1fs", report.total_time_sec)
        return report

    def _select_retrain_symbols(
        self,
        symbols: List[str],
        reasons: Dict[str, str],
        skipped: Dict[str, str],
    ) -> List[str]:
        selected: List[str] = []
        for symbol in symbols:
            acquired, reason = self._acquire_retrain_slot(symbol)
            if acquired:
                selected.append(symbol)
            else:
                skipped[symbol] = reason
                logger.info("Skip auto retrain for %s: %s", symbol, reason)
        if selected:
            logger.warning(
                "Auto retrain selected for %d symbols: %s; reasons=%s",
                len(selected), selected, {s: reasons.get(s, "") for s in selected},
            )
        return selected

    def _acquire_retrain_slot(self, symbol: str) -> tuple[bool, str]:
        cooldown_key = f"prediction:auto_retrain:cooldown:{symbol}"
        lock_key = f"prediction:auto_retrain:lock:{symbol}"
        try:
            from ...core.db import get_redis_client

            redis_client = get_redis_client()
            if redis_client is not None:
                if redis_client.get(cooldown_key):
                    return False, "cooldown"
                locked = redis_client.set(lock_key, "1", nx=True, ex=self.lock_ttl_seconds)
                if not locked:
                    return False, "locked"
                redis_client.set(cooldown_key, datetime.utcnow().isoformat(), ex=self.cooldown_seconds)
                return True, "acquired"
        except Exception as exc:
            logger.debug("Redis retrain lock unavailable for %s: %s", symbol, exc)

        now = time.time()
        cooldown_until = _LOCAL_RETRAIN_COOLDOWN.get(symbol, 0)
        if cooldown_until > now:
            return False, "cooldown"
        lock_until = _LOCAL_RETRAIN_LOCKS.get(symbol, 0)
        if lock_until > now:
            return False, "locked"
        _LOCAL_RETRAIN_LOCKS[symbol] = now + self.lock_ttl_seconds
        _LOCAL_RETRAIN_COOLDOWN[symbol] = now + self.cooldown_seconds
        return True, "acquired"

    def _release_retrain_lock(self, symbol: str) -> None:
        lock_key = f"prediction:auto_retrain:lock:{symbol}"
        try:
            from ...core.db import get_redis_client

            redis_client = get_redis_client()
            if redis_client is not None:
                redis_client.delete(lock_key)
                return
        except Exception:
            pass
        _LOCAL_RETRAIN_LOCKS.pop(symbol, None)

    def _log_retrain_triggers(self, session, symbols: List[str], reasons: Dict[str, str]) -> None:
        try:
            from ...core.models import ModelLifecycleEvent

            for symbol in symbols:
                event = ModelLifecycleEvent(
                    symbol=symbol,
                    event_type="retrain_triggered",
                    trigger_reason=reasons.get(symbol) or "monitoring_critical",
                    model_name=self.model_name,
                    details_json=json.dumps(
                        {
                            "reason": reasons.get(symbol),
                            "cooldown_seconds": self.cooldown_seconds,
                            "source": "daily_evaluation",
                        },
                        default=str,
                    ),
                )
                session.add(event)
            session.commit()
        except Exception as exc:
            logger.warning("Failed to log retrain_triggered events: %s", exc)
            try:
                session.rollback()
            except Exception:
                pass


# ===================================================================
# 便捷函数（供 scheduler 调用）
# ===================================================================

def run_daily_evaluation() -> LearningCycleReport:
    """每日评估入口（供调度器直接调用）"""
    loop = ContinuousLearningLoop()
    report = loop.run_evaluation_loop()
    logger.info(report.summary())
    return report


def run_weekly_retrain() -> LearningCycleReport:
    """每周再训练入口（供调度器直接调用）"""
    loop = ContinuousLearningLoop()
    report = loop.run_retrain_loop()
    logger.info(report.summary())
    return report


def run_forced_retrain(symbols: List[str]) -> LearningCycleReport:
    """手动强制再训练"""
    loop = ContinuousLearningLoop()
    report = loop.run_retrain_loop(force_symbols=symbols)
    logger.info(report.summary())
    return report
