"""
收敛检测 + 自动调参优化器（AutoOptimizer）

核心能力：
1. 收敛检测 — 连续 N 轮指标提升 < 阈值 → 收敛停止
2. 发散检测 — 当前得分低于历史最优 × (1 - 发散阈值) → 回滚
3. 超参搜索 — 智能采样 + 诊断驱动调参（过拟合→加正则，欠拟合→加容量）
4. 训练策略 — 至少 min_rounds 轮（默认 50），每轮记录参数组合与结果
5. 最终输出 — 最优参数、收敛日志、全部搜索历史

架构：AutoOptimizer 内部调用 TimeSeriesCVTrainer，对用户透明。

用法：
    from app.prediction.framework.auto_optimizer import AutoOptimizer

    optimizer = AutoOptimizer()
    result = optimizer.optimize(
        dataset, model_name="lightgbm",
        max_rounds=50, n_cv_folds=3,
    )
    print(result.summary())
    print(f"Best params: {result.best_params}")
"""

from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .data_loader import TimeSeriesDataset, TimeSeriesDataLoader
from .evaluator import ModelEvaluator, TrainingReport, aggregate_fold_reports
from .models.base_model import BaseModel

logger = logging.getLogger(__name__)


# ===================================================================
# 数据结构
# ===================================================================

class ConvergenceStatus(Enum):
    IMPROVING = "improving"
    PLATEAU = "plateau"
    CONVERGED = "converged"
    DIVERGED = "diverged"


@dataclass
class TuningRound:
    """单轮调参记录"""
    round_id: int
    params: Dict[str, Any]
    score: float
    metrics: Dict[str, float] = field(default_factory=dict)
    train_score: float = 0.0
    is_best: bool = False
    status: str = "improving"
    adjustment: str = ""
    duration_sec: float = 0.0


@dataclass
class OptimizationResult:
    """完整优化结果"""
    model_name: str
    task_type: str
    horizon: str
    best_params: Dict[str, Any] = field(default_factory=dict)
    best_score: float = float("-inf")
    best_round: int = 0
    total_rounds: int = 0
    converged: bool = False
    convergence_round: int = -1
    rounds: List[TuningRound] = field(default_factory=list)
    total_time_sec: float = 0.0
    final_report: Optional[TrainingReport] = None

    def summary(self) -> str:
        lines = [
            "=" * 65,
            f"  AutoOptimizer Result: {self.model_name}",
            "=" * 65,
            f"  Task: {self.task_type} | Horizon: {self.horizon}",
            f"  Total rounds: {self.total_rounds} | Best round: {self.best_round}",
            f"  Best score: {self.best_score:.6f}",
            f"  Converged: {self.converged}"
            + (f" (at round {self.convergence_round})" if self.converged else ""),
            f"  Total time: {self.total_time_sec:.1f}s",
            "",
            "  --- Best Parameters ---",
        ]
        for k, v in sorted(self.best_params.items()):
            lines.append(f"    {k}: {v}")
        lines.append("")
        lines.append("  --- Search History (last 15 rounds) ---")
        lines.append(
            f"  {'Round':>5s}  {'Score':>10s}  {'Status':>10s}  {'Adjustment':<30s}"
        )
        lines.append("  " + "-" * 60)
        for r in self.rounds[-15:]:
            marker = " *" if r.is_best else "  "
            lines.append(
                f"  {r.round_id:>5d}  {r.score:>10.6f}  "
                f"{r.status:>10s}  {r.adjustment:<30s}{marker}"
            )
        lines.append("=" * 65)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("final_report", None)
        return d

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2, default=str)
        logger.info("Optimization result saved: %s", path)


# ===================================================================
# 收敛检测器
# ===================================================================

class ConvergenceDetector:
    """检测训练是否收敛或发散

    收敛：连续 patience 轮得分提升 < min_improvement
    发散：当前得分 < best_score × (1 - divergence_threshold)
    """

    def __init__(
        self,
        patience: int = 5,
        min_improvement: float = 0.001,
        divergence_threshold: float = 0.05,
        higher_is_better: bool = True,
    ):
        self.patience = patience
        self.min_improvement = min_improvement
        self.divergence_threshold = divergence_threshold
        self.higher_is_better = higher_is_better

        self._scores: List[float] = []
        self._best_score = float("-inf") if higher_is_better else float("inf")
        self._stagnant_count = 0

    def update(self, score: float) -> ConvergenceStatus:
        self._scores.append(score)

        # 是否为新的最优
        improved = (
            (score > self._best_score + self.min_improvement)
            if self.higher_is_better
            else (score < self._best_score - self.min_improvement)
        )

        if improved:
            self._best_score = score
            self._stagnant_count = 0
            return ConvergenceStatus.IMPROVING

        # 检测发散
        if self.higher_is_better:
            diverged = score < self._best_score * (1.0 - self.divergence_threshold)
        else:
            diverged = score > self._best_score * (1.0 + self.divergence_threshold)

        if diverged:
            self._stagnant_count = 0
            return ConvergenceStatus.DIVERGED

        # 计算停滞
        self._stagnant_count += 1
        if self._stagnant_count >= self.patience:
            return ConvergenceStatus.CONVERGED

        return ConvergenceStatus.PLATEAU

    @property
    def best_score(self) -> float:
        return self._best_score

    @property
    def scores(self) -> List[float]:
        return list(self._scores)

    def reset(self) -> None:
        self._scores.clear()
        self._best_score = float("-inf") if self.higher_is_better else float("inf")
        self._stagnant_count = 0


# ===================================================================
# 超参空间
# ===================================================================

def _get_search_space(model_name: str, task_type: str) -> Dict[str, list]:
    """获取模型的超参搜索空间"""
    if model_name == "lightgbm":
        return {
            "n_estimators": [200, 300, 500, 800],
            "learning_rate": [0.01, 0.03, 0.05, 0.08, 0.1],
            "max_depth": [3, 4, 5, 6, 7, 8],
            "num_leaves": [15, 31, 63, 127],
            "min_child_samples": [5, 10, 20, 30, 50],
            "subsample": [0.6, 0.7, 0.8, 0.9, 1.0],
            "colsample_bytree": [0.6, 0.7, 0.8, 0.9, 1.0],
            "reg_alpha": [0, 0.01, 0.1, 0.5, 1.0],
            "reg_lambda": [0, 0.1, 0.5, 1.0, 5.0],
        }
    elif model_name == "xgboost":
        return {
            "n_estimators": [200, 300, 500, 800],
            "learning_rate": [0.01, 0.03, 0.05, 0.08, 0.1],
            "max_depth": [3, 4, 5, 6, 7, 8],
            "min_child_weight": [1, 3, 5, 10, 20],
            "subsample": [0.6, 0.7, 0.8, 0.9, 1.0],
            "colsample_bytree": [0.6, 0.7, 0.8, 0.9, 1.0],
            "reg_alpha": [0, 0.01, 0.1, 0.5, 1.0],
            "reg_lambda": [0.1, 0.5, 1.0, 5.0, 10.0],
        }
    elif model_name == "lstm":
        return {
            "hidden_dim": [32, 64, 128],
            "num_layers": [1, 2, 3],
            "dropout": [0.1, 0.2, 0.3, 0.4],
            "lr": [0.0001, 0.0005, 0.001, 0.003],
            "seq_len": [10, 15, 20, 30],
            "batch_size": [16, 32, 64],
            "epochs": [60, 80, 100],
        }
    else:
        return {}


def _sample_random_params(space: Dict[str, list], rng: np.random.RandomState) -> Dict:
    """从搜索空间随机采样一组参数"""
    return {k: rng.choice(v) for k, v in space.items()}


def _perturb_params(
    base_params: Dict,
    space: Dict[str, list],
    rng: np.random.RandomState,
    n_changes: int = 2,
) -> Dict:
    """对最优参数做局部扰动（Bayesian-style exploitation）"""
    params = dict(base_params)
    keys = [k for k in space.keys() if k in params]
    if not keys:
        return _sample_random_params(space, rng)

    change_keys = rng.choice(keys, size=min(n_changes, len(keys)), replace=False)
    for k in change_keys:
        candidates = space[k]
        current_val = params.get(k)
        if current_val in candidates:
            idx = candidates.index(current_val)
            # 随机选择相邻值
            neighbors = []
            if idx > 0:
                neighbors.append(candidates[idx - 1])
            if idx < len(candidates) - 1:
                neighbors.append(candidates[idx + 1])
            if neighbors:
                params[k] = rng.choice(neighbors)
        else:
            params[k] = rng.choice(candidates)
    return params


# ===================================================================
# 诊断驱动调参
# ===================================================================

def _diagnose_and_adjust(
    params: Dict,
    space: Dict[str, list],
    train_score: float,
    val_score: float,
    task_type: str,
    rng: np.random.RandomState,
) -> Tuple[Dict, str]:
    """根据训练/验证得分差距诊断问题并调整参数

    Returns:
        adjusted_params, adjustment_description
    """
    params = dict(params)

    # 计算过拟合程度
    if task_type == "classification":
        overfit_gap = train_score - val_score  # AUC gap
    else:
        overfit_gap = val_score - train_score  # MSE gap (val worse = positive)

    def _shift(key: str, direction: int):
        """在搜索空间内移动参数值"""
        if key not in space or key not in params:
            return
        candidates = space[key]
        current = params[key]
        if current in candidates:
            idx = candidates.index(current)
            new_idx = max(0, min(len(candidates) - 1, idx + direction))
            params[key] = candidates[new_idx]
        elif direction > 0:
            params[key] = candidates[-1]
        else:
            params[key] = candidates[0]

    if overfit_gap > 0.15:
        # 严重过拟合：大幅增加正则化
        _shift("reg_alpha", 2)
        _shift("reg_lambda", 2)
        _shift("max_depth", -2)
        _shift("num_leaves", -1)
        _shift("min_child_samples", 2)
        _shift("min_child_weight", 2)
        _shift("subsample", -1)
        _shift("colsample_bytree", -1)
        _shift("dropout", 1)
        return params, "severe_overfit→strong_regularize"

    elif overfit_gap > 0.05:
        # 轻度过拟合：适度正则化
        _shift("reg_alpha", 1)
        _shift("reg_lambda", 1)
        _shift("max_depth", -1)
        _shift("min_child_samples", 1)
        _shift("min_child_weight", 1)
        _shift("dropout", 1)
        return params, "mild_overfit→regularize"

    elif val_score < 0.55 and task_type == "classification":
        # 欠拟合：增加容量
        _shift("max_depth", 1)
        _shift("num_leaves", 1)
        _shift("n_estimators", 1)
        _shift("hidden_dim", 1)
        _shift("learning_rate", 1)
        _shift("min_child_samples", -1)
        _shift("min_child_weight", -1)
        return params, "underfit→increase_capacity"

    else:
        # 一般性微调
        return _perturb_params(params, space, rng, n_changes=2), "explore_neighbor"


# ===================================================================
# 主优化器
# ===================================================================

class AutoOptimizer:
    """收敛检测 + 自动调参优化器

    核心流程：
    1. 初始化：用默认参数跑 baseline
    2. 迭代搜索（至少 min_rounds 轮）：
       - 前 30% 轮：随机探索（exploration）
       - 中 40% 轮：诊断驱动调参 + 局部扰动（exploitation）
       - 后 30% 轮：精细扰动最优参数
    3. 每轮检测收敛/发散：
       - 发散 → 回滚到最优参数并扰动
       - 收敛 → 在 min_rounds 之后可提前停止
    4. 用最优参数做最终完整训练

    用法：
        optimizer = AutoOptimizer(min_rounds=50)
        result = optimizer.optimize(dataset, "lightgbm")
    """

    def __init__(
        self,
        min_rounds: int = 50,
        max_rounds: int = 80,
        convergence_patience: int = 5,
        convergence_threshold: float = 0.001,
        divergence_threshold: float = 0.05,
        n_cv_folds: int = 3,
        random_seed: int = 42,
        checkpoint_dir: str = "storage/model_checkpoints",
    ):
        self.min_rounds = min_rounds
        self.max_rounds = max_rounds
        self.convergence_patience = convergence_patience
        self.convergence_threshold = convergence_threshold
        self.divergence_threshold = divergence_threshold
        self.n_cv_folds = n_cv_folds
        self.random_seed = random_seed
        self.checkpoint_dir = checkpoint_dir

    def optimize(
        self,
        dataset: TimeSeriesDataset,
        model_name: str = "lightgbm",
        initial_params: Optional[Dict] = None,
    ) -> OptimizationResult:
        """执行完整的自动调参优化

        Args:
            dataset:        TimeSeriesDataset
            model_name:     "lightgbm" / "xgboost" / "lstm"
            initial_params: 初始超参数（可选，None 则用模型默认值）
        """
        t0 = time.time()
        rng = np.random.RandomState(self.random_seed)
        space = _get_search_space(model_name, dataset.task_type)
        higher_is_better = dataset.task_type == "classification"

        detector = ConvergenceDetector(
            patience=self.convergence_patience,
            min_improvement=self.convergence_threshold,
            divergence_threshold=self.divergence_threshold,
            higher_is_better=higher_is_better,
        )

        # 初始参数
        if initial_params:
            current_params = dict(initial_params)
        else:
            from .models import get_model
            temp = get_model(model_name, dataset.task_type)
            current_params = temp.get_default_params()

        best_params = dict(current_params)
        best_score = float("-inf") if higher_is_better else float("inf")
        best_round = 0
        best_model_state: Optional[BaseModel] = None

        rounds: List[TuningRound] = []
        converged = False
        convergence_round = -1

        logger.info(
            "AutoOptimizer 启动: model=%s, task=%s, min_rounds=%d, max_rounds=%d",
            model_name, dataset.task_type, self.min_rounds, self.max_rounds,
        )

        for round_id in range(self.max_rounds):
            round_t0 = time.time()

            # --- Phase-based 策略 ---
            phase_ratio = round_id / max(self.max_rounds - 1, 1)
            if round_id == 0:
                trial_params = current_params
                adjustment = "baseline"
            elif phase_ratio < 0.3:
                trial_params = _sample_random_params(space, rng)
                adjustment = "random_explore"
            elif phase_ratio < 0.7:
                # 诊断驱动 + 局部扰动
                last_round = rounds[-1] if rounds else None
                if last_round and last_round.status == "diverged":
                    trial_params = _perturb_params(best_params, space, rng, n_changes=1)
                    adjustment = "rollback+perturb"
                else:
                    train_s = last_round.train_score if last_round else 0.5
                    val_s = last_round.score if last_round else 0.5
                    trial_params, adjustment = _diagnose_and_adjust(
                        best_params, space, train_s, val_s, dataset.task_type, rng,
                    )
            else:
                trial_params = _perturb_params(best_params, space, rng, n_changes=1)
                adjustment = "fine_tune_best"

            # --- 训练 + 评估 ---
            score, metrics, train_score, model = self._evaluate_params(
                dataset, model_name, trial_params,
            )

            # --- 收敛检测 ---
            status = detector.update(score)

            is_new_best = (
                (score > best_score) if higher_is_better else (score < best_score)
            )
            if is_new_best:
                best_score = score
                best_params = dict(trial_params)
                best_round = round_id
                best_model_state = model

            # --- 发散回滚 ---
            if status == ConvergenceStatus.DIVERGED:
                current_params = dict(best_params)
                logger.debug(
                    "  Round %d 发散 (score=%.6f < best=%.6f), 回滚到最优参数",
                    round_id, score, best_score,
                )
            else:
                current_params = dict(trial_params)

            # --- 记录 ---
            tr = TuningRound(
                round_id=round_id,
                params=trial_params,
                score=float(score),
                metrics=metrics,
                train_score=float(train_score),
                is_best=is_new_best,
                status=status.value,
                adjustment=adjustment,
                duration_sec=time.time() - round_t0,
            )
            rounds.append(tr)

            if round_id % 10 == 0 or is_new_best:
                logger.info(
                    "  Round %d/%d: score=%.6f %s [%s] %s",
                    round_id, self.max_rounds, score,
                    "★" if is_new_best else " ",
                    status.value, adjustment,
                )

            # --- 收敛停止 ---
            if status == ConvergenceStatus.CONVERGED and round_id >= self.min_rounds:
                converged = True
                convergence_round = round_id
                logger.info(
                    "收敛: round=%d, score=%.6f, patience=%d rounds无提升",
                    round_id, best_score, self.convergence_patience,
                )
                break

        # --- 最终完整训练 ---
        logger.info("用最优参数做最终完整训练: %s", best_params)
        final_report = self._final_train(dataset, model_name, best_params)

        elapsed = time.time() - t0

        result = OptimizationResult(
            model_name=model_name,
            task_type=dataset.task_type,
            horizon=dataset.horizon,
            best_params=best_params,
            best_score=best_score,
            best_round=best_round,
            total_rounds=len(rounds),
            converged=converged,
            convergence_round=convergence_round,
            rounds=rounds,
            total_time_sec=elapsed,
            final_report=final_report,
        )

        # 自动保存
        self._save_result(result, model_name, dataset.task_type, dataset.horizon)

        logger.info(
            "AutoOptimizer 完成: best_score=%.6f, best_round=%d, "
            "total_rounds=%d, converged=%s, time=%.1fs",
            best_score, best_round, len(rounds), converged, elapsed,
        )

        return result

    # ------------------------------------------------------------------
    # 内部：单轮评估
    # ------------------------------------------------------------------

    def _evaluate_params(
        self,
        dataset: TimeSeriesDataset,
        model_name: str,
        params: Dict,
    ) -> Tuple[float, Dict[str, float], float, BaseModel]:
        """用给定参数做 CV 训练并返回得分

        Returns:
            primary_score, val_metrics, train_primary_score, model_instance
        """
        from .models import get_model

        model = get_model(model_name, task_type=dataset.task_type, params=params)
        loader = TimeSeriesDataLoader()

        try:
            splits = loader.get_cv_splits(
                dataset, n_splits=self.n_cv_folds, min_train_size=60,
            )
        except ValueError:
            return self._worst_score(dataset.task_type), {}, 0.0, model

        val_scores = []
        train_scores = []

        for split in splits:
            X_tr = dataset.X[split.train_idx]
            y_tr = dataset.y[split.train_idx]
            X_va = dataset.X[split.val_idx]
            y_va = dataset.y[split.val_idx]

            fold_model = model.__class__(
                task_type=model.task_type, params=params.copy(),
            )
            try:
                fold_model.train(
                    X_tr, y_tr, X_val=X_va, y_val=y_va,
                    feature_names=dataset.feature_names,
                )
            except Exception as e:
                logger.debug("Training failed with params %s: %s", params, e)
                return self._worst_score(dataset.task_type), {}, 0.0, model

            y_pred_va = fold_model.predict(X_va)
            y_pred_tr = fold_model.predict(X_tr)

            proba_va = None
            proba_tr = None
            if dataset.task_type == "classification":
                try:
                    p = fold_model.predict_proba(X_va)
                    if p.ndim == 2 and p.shape[1] >= 2:
                        proba_va = p[:, 1]
                    p2 = fold_model.predict_proba(X_tr)
                    if p2.ndim == 2 and p2.shape[1] >= 2:
                        proba_tr = p2[:, 1]
                except Exception:
                    pass

            vm = ModelEvaluator.evaluate(y_va, y_pred_va, dataset.task_type, proba_va)
            tm = ModelEvaluator.evaluate(y_tr, y_pred_tr, dataset.task_type, proba_tr)

            val_scores.append(self._primary_score(vm, dataset.task_type))
            train_scores.append(self._primary_score(tm, dataset.task_type))

        avg_val = float(np.mean(val_scores))
        avg_train = float(np.mean(train_scores))

        return avg_val, vm, avg_train, model

    @staticmethod
    def _primary_score(metrics: Dict[str, float], task_type: str) -> float:
        if task_type == "classification":
            return metrics.get("auc", metrics.get("accuracy", 0.5))
        else:
            return -metrics.get("mse", 1e6)

    @staticmethod
    def _worst_score(task_type: str) -> float:
        return 0.0 if task_type == "classification" else -1e6

    # ------------------------------------------------------------------
    # 内部：最终完整训练
    # ------------------------------------------------------------------

    def _final_train(
        self,
        dataset: TimeSeriesDataset,
        model_name: str,
        best_params: Dict,
    ) -> Optional[TrainingReport]:
        from .trainer import TimeSeriesCVTrainer
        from .models import get_model

        try:
            model = get_model(model_name, dataset.task_type, best_params)
            trainer = TimeSeriesCVTrainer(checkpoint_dir=self.checkpoint_dir)
            report = trainer.run(
                dataset, model, n_splits=max(3, self.n_cv_folds), auto_save=True,
            )
            return report
        except Exception as e:
            logger.error("最终训练失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def _save_result(
        self,
        result: OptimizationResult,
        model_name: str,
        task_type: str,
        horizon: str,
    ) -> None:
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(
            self.checkpoint_dir,
            f"{model_name}_{task_type}_{horizon}_{ts}_optimization.json",
        )
        result.save(path)


# ===================================================================
# 便捷函数
# ===================================================================

def auto_optimize(
    df,
    model_name: str = "lightgbm",
    task_type: str = "classification",
    horizon: str = "5d",
    min_rounds: int = 50,
    max_rounds: int = 80,
    news_df=None,
    macro_df=None,
    top_n_features: int = 40,
    checkpoint_dir: str = "storage/model_checkpoints",
) -> OptimizationResult:
    """一键自动优化：因子工程 + 特征筛选 + 自动调参 + 收敛检测

    Args:
        df:              OHLCV DataFrame
        model_name:      模型名称
        task_type:       任务类型
        horizon:         预测周期
        min_rounds:      最少搜索轮数
        max_rounds:      最多搜索轮数
        news_df:         新闻情绪数据
        macro_df:        宏观数据
        top_n_features:  保留特征数
        checkpoint_dir:  保存目录

    Returns:
        OptimizationResult
    """
    loader = TimeSeriesDataLoader()
    dataset, _ = loader.prepare_advanced(
        df,
        horizon=horizon,
        task_type=task_type,
        news_df=news_df,
        macro_df=macro_df,
        top_n_features=top_n_features,
    )

    optimizer = AutoOptimizer(
        min_rounds=min_rounds,
        max_rounds=max_rounds,
        checkpoint_dir=checkpoint_dir,
    )

    result = optimizer.optimize(dataset, model_name)
    print(result.summary())
    return result
