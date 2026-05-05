"""
训练服务（TrainingService）

职责：
1. 触发模型再训练（使用 framework 中的 AutoOptimizer 或 TimeSeriesCVTrainer）
2. 检查特征有效性 — 对比旧/新特征集的表现
3. 因子动态扩展 + A/B 测试 — 自动尝试引入新特征并评估效果
4. 增量更新 / 全量重训
5. 结果写入 ModelRegistry + ModelLifecycleEvent
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from ...core.models import ModelRegistry, ModelLifecycleEvent
from ...core.constants import RETRAIN_TRIGGER_RULES

logger = logging.getLogger(__name__)

CHECKPOINT_DIR = os.path.join("storage", "model_checkpoints")


@dataclass
class RetrainResult:
    """再训练结果"""
    symbol: str
    model_name: str
    task_type: str
    success: bool = False
    score_before: float = 0.0
    score_after: float = 0.0
    improved: bool = False
    best_params: Dict[str, Any] = field(default_factory=dict)
    features_used: List[str] = field(default_factory=list)
    artifact_path: str = ""
    duration_sec: float = 0.0
    error: str = ""


@dataclass
class ABTestResult:
    """A/B 测试结果"""
    symbol: str
    baseline_score: float = 0.0
    candidate_score: float = 0.0
    new_features: List[str] = field(default_factory=list)
    winner: str = ""   # "baseline" or "candidate"
    improvement: float = 0.0


class TrainingService:
    """模型训练与再训练服务

    与 prediction.framework 集成，提供：
    - retrain(): 对指定 symbol 全量重训
    - incremental_update(): 增量更新（追加近期数据再训练）
    - ab_test_features(): 对比旧/新特征集
    """

    def __init__(
        self,
        session: Session,
        model_name: str = "lightgbm",
        task_type: str = "classification",
        horizon: str = "5d",
        use_optimizer: bool = True,
        checkpoint_dir: str = CHECKPOINT_DIR,
    ):
        self.session = session
        self.model_name = model_name
        self.task_type = task_type
        self.horizon = horizon
        self.use_optimizer = use_optimizer
        self.checkpoint_dir = checkpoint_dir

    # ------------------------------------------------------------------
    # 1. 全量重训
    # ------------------------------------------------------------------

    def retrain(
        self,
        symbol: str,
        reason: str = "manual",
        min_rounds: int = 30,
    ) -> RetrainResult:
        """对指定 symbol 执行全量重训

        流程：
        1. 从 DB 读取历史价格
        2. 调用 framework 训练（可选 AutoOptimizer）
        3. 将模型注册到 ModelRegistry
        4. 记录生命周期事件
        """
        t0 = time.time()
        result = RetrainResult(
            symbol=symbol, model_name=self.model_name, task_type=self.task_type,
        )

        try:
            df = self._load_price_data(symbol)
            if df is None or len(df) < 100:
                result.error = f"Insufficient data: {len(df) if df is not None else 0} rows"
                return result

            score_before = self._get_current_score(symbol)
            result.score_before = score_before

            original_checkpoint_dir = self.checkpoint_dir
            self.checkpoint_dir = self._make_run_checkpoint_dir(symbol)
            if self.use_optimizer:
                retrain_result = self._train_with_optimizer(df, min_rounds)
            else:
                retrain_result = self._train_basic(df)
            self.checkpoint_dir = original_checkpoint_dir

            if retrain_result is None:
                result.error = "Training failed"
                return result

            report, score_after, artifact_path, features, best_params = retrain_result
            improvement_ratio = float(RETRAIN_TRIGGER_RULES.get("min_score_improvement_ratio", 1.02))

            result.success = True
            result.score_after = score_after
            result.improved = score_after > (score_before * improvement_ratio) if score_before > 0 else True
            result.best_params = best_params
            result.features_used = features
            result.artifact_path = artifact_path
            result.duration_sec = time.time() - t0

            self._register_model(symbol, result, activate=result.improved)
            self._log_event(
                symbol=symbol,
                event_type="retrain_completed",
                reason=reason,
                model_name=self.model_name,
                score_before=score_before,
                score_after=score_after,
                details={
                    "improved": result.improved,
                    "activation_threshold_ratio": improvement_ratio,
                    "activated": result.improved,
                    "best_params": best_params,
                    "n_features": len(features),
                    "duration_sec": result.duration_sec,
                },
            )

            logger.info(
                "Retrain completed: %s score %.4f → %.4f (%s)",
                symbol, score_before, score_after,
                "improved" if result.improved else "no improvement",
            )

            if not result.improved and self._count_recent_no_improve(symbol) >= 2:
                self._log_event(
                    symbol=symbol,
                    event_type="retrain_stagnated",
                    reason="two_consecutive_no_improve",
                    model_name=self.model_name,
                    score_before=score_before,
                    score_after=score_after,
                    details={
                        "activation_threshold_ratio": improvement_ratio,
                        "message": "连续两次再训练未达到激活阈值，保留旧模型",
                    },
                )

        except Exception as e:
            try:
                self.checkpoint_dir = original_checkpoint_dir  # type: ignore[name-defined]
            except Exception:
                pass
            result.error = str(e)
            result.duration_sec = time.time() - t0
            logger.error("Retrain failed for %s: %s", symbol, e)
            self._log_event(
                symbol=symbol,
                event_type="retrain_completed",
                reason=reason,
                details={"error": str(e)},
            )

        return result

    # ------------------------------------------------------------------
    # 2. 增量更新
    # ------------------------------------------------------------------

    def incremental_update(
        self,
        symbol: str,
        lookback_days: int = 90,
    ) -> RetrainResult:
        """增量更新：仅用最近 N 天数据微调模型

        比全量重训更快，适合日常更新。
        """
        t0 = time.time()
        result = RetrainResult(
            symbol=symbol, model_name=self.model_name, task_type=self.task_type,
        )

        try:
            df = self._load_price_data(symbol, lookback_days=lookback_days)
            if df is None or len(df) < 60:
                result.error = f"Insufficient data for incremental: {len(df) if df is not None else 0}"
                return result

            retrain_result = self._train_basic(df)
            if retrain_result is None:
                result.error = "Incremental training failed"
                return result

            report, score_after, artifact_path, features, best_params = retrain_result

            result.success = True
            result.score_after = score_after
            result.features_used = features
            result.artifact_path = artifact_path
            result.duration_sec = time.time() - t0

            self._register_model(symbol, result)

            logger.info("Incremental update for %s: score=%.4f", symbol, score_after)

        except Exception as e:
            result.error = str(e)
            result.duration_sec = time.time() - t0
            logger.error("Incremental update failed for %s: %s", symbol, e)

        return result

    # ------------------------------------------------------------------
    # 3. A/B 测试新因子
    # ------------------------------------------------------------------

    def ab_test_features(
        self,
        symbol: str,
        candidate_features: Optional[List[str]] = None,
        expanded_top_n: int = 50,
    ) -> ABTestResult:
        """A/B 测试：对比当前特征集 vs 扩展特征集

        baseline:  当前模型使用的特征 (top_n=40)
        candidate: 扩展特征集 (top_n=50 或指定的新因子)

        Returns: ABTestResult
        """
        result = ABTestResult(symbol=symbol)

        try:
            df = self._load_price_data(symbol)
            if df is None or len(df) < 100:
                return result

            from ..framework.data_loader import TimeSeriesDataLoader

            loader = TimeSeriesDataLoader()

            # baseline: 标准 top_n=40
            dataset_a, _ = loader.prepare_advanced(
                df, horizon=self.horizon, task_type=self.task_type,
                top_n_features=40,
            )

            # candidate: 扩展 top_n
            dataset_b, _ = loader.prepare_advanced(
                df, horizon=self.horizon, task_type=self.task_type,
                top_n_features=expanded_top_n,
            )

            from ..framework.models import get_model

            score_a = self._quick_cv_score(dataset_a)
            score_b = self._quick_cv_score(dataset_b)

            result.baseline_score = score_a
            result.candidate_score = score_b
            result.new_features = [
                f for f in dataset_b.feature_names if f not in dataset_a.feature_names
            ]
            result.improvement = score_b - score_a

            if score_b > score_a + 0.005:
                result.winner = "candidate"
            else:
                result.winner = "baseline"

            self._log_event(
                symbol=symbol,
                event_type="ab_test",
                reason="feature_expansion",
                score_before=score_a,
                score_after=score_b,
                details={
                    "baseline_features": len(dataset_a.feature_names),
                    "candidate_features": len(dataset_b.feature_names),
                    "new_features": result.new_features[:10],
                    "winner": result.winner,
                    "improvement": result.improvement,
                },
            )

            logger.info(
                "A/B test %s: baseline=%.4f, candidate=%.4f → winner=%s",
                symbol, score_a, score_b, result.winner,
            )

        except Exception as e:
            logger.error("A/B test failed for %s: %s", symbol, e)

        return result

    # ------------------------------------------------------------------
    # 内部：数据加载
    # ------------------------------------------------------------------

    def _load_price_data(
        self, symbol: str, lookback_days: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """从 DB 读取历史价格"""
        try:
            from ...core.db import engine

            where_clause = "WHERE symbol = %(symbol)s"
            params: Dict[str, Any] = {"symbol": symbol}

            if lookback_days:
                cutoff = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                where_clause += " AND trade_date >= %(cutoff)s"
                params["cutoff"] = cutoff

            sql = f"""
                SELECT trade_date, open, high, low, close, vol as volume
                FROM prices_daily
                {where_clause}
                ORDER BY trade_date
            """
            df = pd.read_sql_query(sql, con=engine, params=params)
            if df.empty:
                return None

            if "trade_date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")

            return df
        except Exception as e:
            logger.error("Failed to load price data for %s: %s", symbol, e)
            return None

    # ------------------------------------------------------------------
    # 内部：训练
    # ------------------------------------------------------------------

    def _train_with_optimizer(self, df: pd.DataFrame, min_rounds: int = 30):
        """使用 AutoOptimizer 训练"""
        from ..framework.auto_optimizer import AutoOptimizer
        from ..framework.data_loader import TimeSeriesDataLoader

        loader = TimeSeriesDataLoader()
        dataset, _ = loader.prepare_advanced(
            df, horizon=self.horizon, task_type=self.task_type,
            top_n_features=40,
        )

        optimizer = AutoOptimizer(
            min_rounds=min_rounds,
            max_rounds=min_rounds + 30,
            n_cv_folds=3,
            checkpoint_dir=self.checkpoint_dir,
        )
        opt_result = optimizer.optimize(dataset, self.model_name)

        if opt_result.final_report is None:
            return None

        score = opt_result.best_score
        features = dataset.feature_names
        artifact_path = os.path.join(
            self.checkpoint_dir,
            f"{self.model_name}_{self.task_type}_{self.horizon}_latest.pkl",
        )

        return opt_result.final_report, score, artifact_path, features, opt_result.best_params

    def _train_basic(self, df: pd.DataFrame):
        """使用基础 CV 训练"""
        from ..framework.data_loader import TimeSeriesDataLoader
        from ..framework.trainer import TimeSeriesCVTrainer
        from ..framework.models import get_model

        loader = TimeSeriesDataLoader()
        dataset, _ = loader.prepare_advanced(
            df, horizon=self.horizon, task_type=self.task_type,
            top_n_features=40,
        )

        model = get_model(self.model_name, self.task_type)
        trainer = TimeSeriesCVTrainer(checkpoint_dir=self.checkpoint_dir)
        report = trainer.run(dataset, model, n_splits=3)

        score = report.best_val_score
        if self.task_type == "regression":
            score = -score  # negate MSE
        features = dataset.feature_names
        artifact_path = os.path.join(
            self.checkpoint_dir,
            f"{self.model_name}_{self.task_type}_{self.horizon}_latest.pkl",
        )

        return report, score, artifact_path, features, {}

    def _quick_cv_score(self, dataset) -> float:
        """快速 2-fold CV 评分（用于 A/B 测试）"""
        from ..framework.data_loader import TimeSeriesDataLoader
        from ..framework.evaluator import ModelEvaluator
        from ..framework.models import get_model

        model = get_model(self.model_name, self.task_type)
        loader = TimeSeriesDataLoader()

        try:
            splits = loader.get_cv_splits(dataset, n_splits=2, min_train_size=60)
        except ValueError:
            return 0.0

        scores = []
        for split in splits:
            X_tr, y_tr = dataset.X[split.train_idx], dataset.y[split.train_idx]
            X_va, y_va = dataset.X[split.val_idx], dataset.y[split.val_idx]

            fold_model = model.__class__(task_type=model.task_type, params=model.params.copy())
            try:
                fold_model.train(X_tr, y_tr, X_val=X_va, y_val=y_va, feature_names=dataset.feature_names)
                y_pred = fold_model.predict(X_va)
                proba = None
                if self.task_type == "classification":
                    try:
                        p = fold_model.predict_proba(X_va)
                        if p.ndim == 2 and p.shape[1] >= 2:
                            proba = p[:, 1]
                    except Exception:
                        pass
                metrics = ModelEvaluator.evaluate(y_va, y_pred, self.task_type, proba)
                if self.task_type == "classification":
                    scores.append(metrics.get("auc", metrics.get("accuracy", 0.5)))
                else:
                    scores.append(-metrics.get("mse", 1e6))
            except Exception:
                scores.append(0.0)

        return float(np.mean(scores)) if scores else 0.0

    def _make_run_checkpoint_dir(self, symbol: str) -> str:
        safe_symbol = symbol.replace(".", "_").replace("/", "_").replace("\\", "_")
        run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return os.path.join(
            self.checkpoint_dir,
            safe_symbol,
            self.task_type,
            self.horizon,
            run_id,
        )

    # ------------------------------------------------------------------
    # 内部：模型注册
    # ------------------------------------------------------------------

    def _get_current_score(self, symbol: str) -> float:
        """获取当前活跃模型的评分"""
        try:
            reg = self.session.execute(
                select(ModelRegistry)
                .where(
                    ModelRegistry.is_active == True,
                    ModelRegistry.task == f"{symbol}_{self.task_type}_{self.horizon}",
                )
                .order_by(ModelRegistry.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if reg and reg.metrics_json:
                metrics = json.loads(reg.metrics_json)
                return metrics.get("score", 0.0)
        except Exception:
            pass
        return 0.0

    def _register_model(self, symbol: str, result: RetrainResult, activate: bool = True) -> None:
        """将训练结果注册到 ModelRegistry"""
        try:
            task = f"{symbol}_{self.task_type}_{self.horizon}"
            if activate:
                old_active = self.session.execute(
                    select(ModelRegistry).where(
                        ModelRegistry.is_active == True,
                        ModelRegistry.task == task,
                    )
                ).scalars().all()
                for m in old_active:
                    m.is_active = False

            latest_version = self.session.execute(
                select(func.max(ModelRegistry.version)).where(ModelRegistry.task == task)
            ).scalar() or 0

            new_reg = ModelRegistry(
                model_name=f"{symbol}_{result.model_name}",
                version=int(latest_version) + 1,
                task=task,
                algo=result.model_name,
                features_used=json.dumps(result.features_used[:50]),
                metrics_json=json.dumps({
                    "score": result.score_after,
                    "improved": result.improved,
                    "activated": activate,
                }),
                artifact_path=result.artifact_path,
                is_active=activate,
            )
            self.session.add(new_reg)
            self.session.commit()
        except Exception as e:
            logger.warning("Failed to register model: %s", e)
            try:
                self.session.rollback()
            except Exception:
                pass

    def _count_recent_no_improve(self, symbol: str, limit: int = 2) -> int:
        """统计最近连续未达激活阈值的重训完成事件。"""
        events = self.session.execute(
            select(ModelLifecycleEvent)
            .where(
                ModelLifecycleEvent.symbol == symbol,
                ModelLifecycleEvent.event_type == "retrain_completed",
            )
            .order_by(ModelLifecycleEvent.created_at.desc())
            .limit(limit)
        ).scalars().all()
        count = 0
        for event in events:
            improved = None
            if event.details_json:
                try:
                    improved = json.loads(event.details_json).get("improved")
                except Exception:
                    improved = None
            if improved is False:
                count += 1
            else:
                break
        return count

    def _log_event(
        self,
        symbol: Optional[str],
        event_type: str,
        reason: str,
        model_name: Optional[str] = None,
        score_before: Optional[float] = None,
        score_after: Optional[float] = None,
        details: Optional[Dict] = None,
    ) -> None:
        try:
            event = ModelLifecycleEvent(
                symbol=symbol,
                event_type=event_type,
                trigger_reason=reason,
                model_name=model_name or self.model_name,
                score_before=score_before,
                score_after=score_after,
                details_json=json.dumps(details, default=str) if details else None,
            )
            self.session.add(event)
            self.session.commit()
        except Exception as e:
            logger.warning("Failed to log event: %s", e)
            try:
                self.session.rollback()
            except Exception:
                pass
