"""
模型评估器

统一的指标计算与训练报告生成。
支持分类（Accuracy / F1 / AUC）和回归（MSE / MAE / R² / IC）任务。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------

def accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(y_true == y_pred))


def f1_score_binary(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    tp = np.sum((y_true == 1) & (y_pred == 1))
    fp = np.sum((y_true == 0) & (y_pred == 1))
    fn = np.sum((y_true == 1) & (y_pred == 0))
    precision = tp / (tp + fp + 1e-9)
    recall = tp / (tp + fn + 1e-9)
    return float(2 * precision * recall / (precision + recall + 1e-9))


def auc_score(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """手写 AUC 避免 sklearn 依赖（仅对二分类）"""
    pos = y_proba[y_true == 1]
    neg = y_proba[y_true == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    # Mann-Whitney U statistic
    count = 0.0
    for p in pos:
        count += np.sum(p > neg) + 0.5 * np.sum(p == neg)
    return float(count / (len(pos) * len(neg)))


def mse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean((y_true - y_pred) ** 2))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(mse(y_true, y_pred)))


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def r2_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot < 1e-12:
        return 0.0
    return float(1.0 - ss_res / ss_tot)


def information_coefficient(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """IC：预测值与真实值的 Spearman rank correlation"""
    from scipy.stats import spearmanr
    if len(y_true) < 5:
        return 0.0
    corr, _ = spearmanr(y_true, y_pred)
    return float(corr) if np.isfinite(corr) else 0.0


def directional_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """方向准确率：预测涨跌方向的正确比例"""
    if len(y_true) < 2:
        return 0.0
    correct = np.sum(np.sign(y_true) == np.sign(y_pred))
    return float(correct / len(y_true))


# ---------------------------------------------------------------------------
# 统一评估接口
# ---------------------------------------------------------------------------

class ModelEvaluator:
    """根据任务类型自动选择合适指标"""

    @staticmethod
    def evaluate(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        task_type: str,
        y_proba: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """
        Args:
            y_true:    真实值
            y_pred:    预测值（分类为 label，回归为连续值）
            task_type: "classification" / "regression"
            y_proba:   分类概率（可选，用于 AUC）

        Returns:
            指标字典
        """
        metrics: Dict[str, float] = {}

        if task_type == "classification":
            metrics["accuracy"] = accuracy(y_true, y_pred)
            metrics["f1"] = f1_score_binary(y_true, y_pred)
            if y_proba is not None:
                metrics["auc"] = auc_score(y_true, y_proba)
            metrics["ic"] = information_coefficient(y_true, y_pred.astype(float))
        else:
            metrics["mse"] = mse(y_true, y_pred)
            metrics["rmse"] = rmse(y_true, y_pred)
            metrics["mae"] = mae(y_true, y_pred)
            metrics["r2"] = r2_score(y_true, y_pred)
            metrics["ic"] = information_coefficient(y_true, y_pred)
            metrics["directional_accuracy"] = directional_accuracy(y_true, y_pred)

        return metrics


# ---------------------------------------------------------------------------
# 训练报告
# ---------------------------------------------------------------------------

@dataclass
class FoldReport:
    """单个 CV fold 的评估报告"""
    fold: int
    train_metrics: Dict[str, float] = field(default_factory=dict)
    val_metrics: Dict[str, float] = field(default_factory=dict)
    best_iteration: int = 0
    train_samples: int = 0
    val_samples: int = 0
    feature_importance: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrainingReport:
    """完整的训练报告"""
    model_name: str
    task_type: str
    horizon: str
    n_folds: int
    fold_reports: List[FoldReport] = field(default_factory=list)
    avg_val_metrics: Dict[str, float] = field(default_factory=dict)
    std_val_metrics: Dict[str, float] = field(default_factory=dict)
    best_fold: int = 0
    best_val_score: float = float("inf")
    total_train_time_sec: float = 0.0
    created_at: str = ""
    iteration_curves: Dict[int, List[Dict[str, float]]] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"===== Training Report: {self.model_name} =====",
            f"Task: {self.task_type} | Horizon: {self.horizon} | Folds: {self.n_folds}",
            f"Best fold: {self.best_fold} (score: {self.best_val_score:.6f})",
            f"Training time: {self.total_train_time_sec:.1f}s",
            "",
            "--- Average Validation Metrics ---",
        ]
        for k, v in self.avg_val_metrics.items():
            std = self.std_val_metrics.get(k, 0)
            lines.append(f"  {k:>25s}: {v:.6f} ± {std:.6f}")
        lines.append("")
        for fr in self.fold_reports:
            lines.append(f"  Fold {fr.fold}: train={fr.train_samples}, val={fr.val_samples}")
            for k, v in fr.val_metrics.items():
                lines.append(f"    {k}: {v:.6f}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2, default=str)
        logger.info("Training report saved: %s", path)


def aggregate_fold_reports(
    fold_reports: List[FoldReport],
    task_type: str,
) -> tuple[Dict[str, float], Dict[str, float], int, float]:
    """汇总所有 fold 报告

    Returns:
        avg_metrics, std_metrics, best_fold_idx, best_score
    """
    if not fold_reports:
        return {}, {}, 0, float("inf")

    metric_keys = list(fold_reports[0].val_metrics.keys())
    metric_arrays: Dict[str, List[float]] = {k: [] for k in metric_keys}

    for fr in fold_reports:
        for k in metric_keys:
            metric_arrays[k].append(fr.val_metrics.get(k, 0))

    avg = {k: float(np.mean(v)) for k, v in metric_arrays.items()}
    std = {k: float(np.std(v)) for k, v in metric_arrays.items()}

    # 选择最优 fold（分类用 AUC/accuracy 最大，回归用 MSE 最小）
    if task_type == "classification":
        score_key = "auc" if "auc" in metric_keys else "accuracy"
        scores = metric_arrays[score_key]
        best_idx = int(np.argmax(scores))
        best_score = scores[best_idx]
    else:
        score_key = "mse"
        scores = metric_arrays.get(score_key, [float("inf")])
        best_idx = int(np.argmin(scores))
        best_score = scores[best_idx]

    return avg, std, best_idx, best_score
