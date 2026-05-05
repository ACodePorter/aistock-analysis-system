"""
时间序列交叉验证训练器（TimeSeriesCVTrainer）

职责：
1. 接收 TimeSeriesDataset + BaseModel 实例
2. 执行 N 折时间序列 CV，每折独立训练模型
3. 每折内逐迭代记录 loss 曲线
4. 自动选择最优 fold，保存 best checkpoint
5. 输出完整 TrainingReport

用法：
    from prediction.framework.data_loader import TimeSeriesDataLoader
    from prediction.framework.models import get_model
    from prediction.framework.trainer import TimeSeriesCVTrainer

    loader = TimeSeriesDataLoader()
    dataset = loader.prepare(df, horizon="5d", task_type="classification")
    model = get_model("lightgbm", task_type="classification")

    trainer = TimeSeriesCVTrainer(checkpoint_dir="storage/checkpoints")
    report = trainer.run(dataset, model, n_splits=5)

    print(report.summary())
    trainer.save_best_model("storage/checkpoints/best.pkl")
"""

from __future__ import annotations

import copy
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from .data_loader import TimeSeriesDataLoader, TimeSeriesDataset, SplitIndex
from .evaluator import (
    ModelEvaluator,
    FoldReport,
    TrainingReport,
    aggregate_fold_reports,
)
from .feature_selector import ImportanceTracker
from .models.base_model import BaseModel, TrainResult

logger = logging.getLogger(__name__)

DEFAULT_CHECKPOINT_DIR = os.path.join("storage", "model_checkpoints")


class TimeSeriesCVTrainer:
    """时间序列交叉验证训练器

    核心流程：
    1. get_cv_splits() 生成严格的时序 expanding-window 分割
    2. 每个 fold: 新建模型实例 → train() → evaluate()
    3. 记录逐迭代 loss 曲线 + fold 级指标
    4. 选出最优 fold → 保存 best checkpoint
    """

    def __init__(self, checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR):
        self.checkpoint_dir = checkpoint_dir
        self._best_model: Optional[BaseModel] = None
        self._best_fold: int = -1
        self._report: Optional[TrainingReport] = None
        self._importance_tracker: Optional[ImportanceTracker] = None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(
        self,
        dataset: TimeSeriesDataset,
        model: BaseModel,
        n_splits: int = 5,
        min_train_size: int = 120,
        auto_save: bool = True,
    ) -> TrainingReport:
        """执行完整的时间序列 CV 训练

        Args:
            dataset:        TimeSeriesDataLoader.prepare() 的输出
            model:          BaseModel 实例（会在每个 fold 中被深拷贝）
            n_splits:       CV 折数
            min_train_size: 最小训练集大小
            auto_save:      是否自动保存最优模型

        Returns:
            TrainingReport
        """
        t0 = time.time()
        loader = TimeSeriesDataLoader()
        splits = loader.get_cv_splits(
            dataset, n_splits=n_splits, min_train_size=min_train_size,
        )

        logger.info(
            "开始训练: model=%s, task=%s, horizon=%s, folds=%d",
            model.name, dataset.task_type, dataset.horizon, len(splits),
        )

        fold_reports: List[FoldReport] = []
        fold_models: Dict[int, BaseModel] = {}
        iteration_curves: Dict[int, List[Dict[str, float]]] = {}
        self._importance_tracker = ImportanceTracker()

        for split in splits:
            fold_model = self._clone_model(model)
            fr, curves = self._train_fold(dataset, fold_model, split)
            fold_reports.append(fr)
            fold_models[split.fold] = fold_model
            iteration_curves[split.fold] = curves

            # 记录特征重要性变化趋势
            if fr.feature_importance:
                self._importance_tracker.record(split.fold, fr.feature_importance)

            logger.info(
                "  Fold %d 完成: val_metrics=%s",
                split.fold,
                {k: f"{v:.4f}" for k, v in fr.val_metrics.items()},
            )

        # 汇总
        avg_metrics, std_metrics, best_fold_idx, best_score = aggregate_fold_reports(
            fold_reports, dataset.task_type,
        )

        self._best_model = fold_models.get(best_fold_idx)
        self._best_fold = best_fold_idx

        elapsed = time.time() - t0

        self._report = TrainingReport(
            model_name=model.name,
            task_type=dataset.task_type,
            horizon=dataset.horizon,
            n_folds=len(splits),
            fold_reports=fold_reports,
            avg_val_metrics=avg_metrics,
            std_val_metrics=std_metrics,
            best_fold=best_fold_idx,
            best_val_score=best_score,
            total_train_time_sec=elapsed,
            created_at=datetime.utcnow().isoformat(),
            iteration_curves=iteration_curves,
        )

        logger.info(
            "训练完成: best_fold=%d, avg_metrics=%s, time=%.1fs",
            best_fold_idx,
            {k: f"{v:.4f}" for k, v in avg_metrics.items()},
            elapsed,
        )

        if auto_save:
            self._auto_save(model.name, dataset.task_type, dataset.horizon)

        return self._report

    # ------------------------------------------------------------------
    # 单 fold 训练
    # ------------------------------------------------------------------

    def _train_fold(
        self,
        dataset: TimeSeriesDataset,
        model: BaseModel,
        split: SplitIndex,
    ) -> tuple[FoldReport, List[Dict[str, float]]]:
        """训练单个 fold 并评估"""
        X_train = dataset.X[split.train_idx]
        y_train = dataset.y[split.train_idx]
        X_val = dataset.X[split.val_idx]
        y_val = dataset.y[split.val_idx]

        # 训练
        train_result: TrainResult = model.train(
            X_train, y_train,
            X_val=X_val, y_val=y_val,
            feature_names=dataset.feature_names,
        )

        # 在验证集上评估
        y_pred_val = model.predict(X_val)
        y_proba_val = None
        if dataset.task_type == "classification":
            try:
                proba = model.predict_proba(X_val)
                if proba.ndim == 2 and proba.shape[1] >= 2:
                    y_proba_val = proba[:, 1]
            except Exception:
                pass

        val_metrics = ModelEvaluator.evaluate(
            y_val, y_pred_val, dataset.task_type, y_proba_val,
        )

        # 在训练集上评估（检测过拟合）
        y_pred_train = model.predict(X_train)
        y_proba_train = None
        if dataset.task_type == "classification":
            try:
                proba_tr = model.predict_proba(X_train)
                if proba_tr.ndim == 2 and proba_tr.shape[1] >= 2:
                    y_proba_train = proba_tr[:, 1]
            except Exception:
                pass

        train_metrics = ModelEvaluator.evaluate(
            y_train, y_pred_train, dataset.task_type, y_proba_train,
        )

        # 逐迭代 loss 曲线
        curves = [
            {
                "iteration": log.iteration,
                "train_loss": log.train_loss,
                "val_loss": log.val_loss,
            }
            for log in train_result.iteration_logs
        ]

        fold_report = FoldReport(
            fold=split.fold,
            train_metrics=train_metrics,
            val_metrics=val_metrics,
            best_iteration=train_result.best_iteration,
            train_samples=len(X_train),
            val_samples=len(X_val),
            feature_importance=train_result.feature_importance,
        )

        return fold_report, curves

    # ------------------------------------------------------------------
    # 模型保存
    # ------------------------------------------------------------------

    def save_best_model(self, path: Optional[str] = None) -> Optional[str]:
        """手动保存最优模型到指定路径"""
        if self._best_model is None:
            logger.warning("无最优模型可保存（请先调用 run()）")
            return None
        if path is None:
            path = os.path.join(self.checkpoint_dir, "best_model.pkl")
        return self._best_model.save(path)

    def _auto_save(self, model_name: str, task_type: str, horizon: str) -> None:
        """训练完成后自动保存"""
        if self._best_model is None:
            return
        os.makedirs(self.checkpoint_dir, exist_ok=True)

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{model_name}_{task_type}_{horizon}_{ts}.pkl"
        model_path = os.path.join(self.checkpoint_dir, filename)
        self._best_model.save(model_path)

        # 同时保存训练报告
        if self._report:
            report_path = model_path.replace(".pkl", "_report.json")
            self._report.save(report_path)

        # 保存特征重要性趋势
        if self._importance_tracker:
            trend_path = model_path.replace(".pkl", "_importance_trend.csv")
            self._importance_tracker.save(trend_path)

        # 更新 "latest" 软链接 / 文件
        latest_path = os.path.join(
            self.checkpoint_dir, f"{model_name}_{task_type}_{horizon}_latest.pkl"
        )
        try:
            if os.path.exists(latest_path):
                os.remove(latest_path)
            self._best_model.save(latest_path)
        except Exception as e:
            logger.warning("Failed to save latest model: %s", e)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _clone_model(model: BaseModel) -> BaseModel:
        """深拷贝模型（保留类型和参数，但重置训练状态）"""
        new = model.__class__(task_type=model.task_type, params=model.params.copy())
        return new

    @property
    def best_model(self) -> Optional[BaseModel]:
        return self._best_model

    @property
    def report(self) -> Optional[TrainingReport]:
        return self._report

    @property
    def importance_tracker(self) -> Optional[ImportanceTracker]:
        return self._importance_tracker


# ---------------------------------------------------------------------------
# 便捷函数：一键训练
# ---------------------------------------------------------------------------

def train_and_evaluate(
    df,
    model_name: str = "lightgbm",
    task_type: str = "classification",
    horizon: str = "5d",
    n_splits: int = 5,
    model_params: Optional[dict] = None,
    news_df=None,
    checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR,
) -> TrainingReport:
    """便捷入口：从 DataFrame 到训练报告

    Args:
        df:             OHLCV DataFrame（必须含 trade_date, close）
        model_name:     "lightgbm" / "xgboost" / "lstm"
        task_type:      "classification" / "regression"
        horizon:        "1d" / "5d" / "10d" / "20d"
        n_splits:       CV 折数
        model_params:   模型超参数覆盖
        news_df:        新闻情绪 DataFrame（可选）
        checkpoint_dir: checkpoint 保存目录

    Returns:
        TrainingReport
    """
    from .models import get_model

    loader = TimeSeriesDataLoader()
    dataset = loader.prepare(df, horizon=horizon, task_type=task_type, news_df=news_df)

    model = get_model(model_name, task_type=task_type, params=model_params)
    trainer = TimeSeriesCVTrainer(checkpoint_dir=checkpoint_dir)

    report = trainer.run(dataset, model, n_splits=n_splits)

    print(report.summary())

    # 输出特征重要性趋势
    if trainer.importance_tracker:
        print()
        print(trainer.importance_tracker.summary())

    return report


def train_advanced(
    df,
    model_name: str = "lightgbm",
    task_type: str = "classification",
    horizon: str = "5d",
    n_splits: int = 5,
    model_params: Optional[dict] = None,
    news_df=None,
    macro_df=None,
    top_n_features: int = 40,
    checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR,
) -> tuple:
    """进阶训练入口：FactorEngine 全因子 + FeatureSelector 筛选 + CV 训练

    Args:
        df:              OHLCV DataFrame
        model_name:      "lightgbm" / "xgboost" / "lstm"
        task_type:       "classification" / "regression"
        horizon:         "1d" / "5d" / "10d" / "20d"
        n_splits:        CV 折数
        model_params:    模型超参数覆盖
        news_df:         新闻情绪 DataFrame（可选）
        macro_df:        宏观经济 DataFrame（可选）
        top_n_features:  筛选后保留特征数
        checkpoint_dir:  checkpoint 保存目录

    Returns:
        (TrainingReport, SelectionResult, ImportanceTracker)
    """
    from .models import get_model

    loader = TimeSeriesDataLoader()
    dataset, selection_result = loader.prepare_advanced(
        df,
        horizon=horizon,
        task_type=task_type,
        news_df=news_df,
        macro_df=macro_df,
        top_n_features=top_n_features,
    )

    model = get_model(model_name, task_type=task_type, params=model_params)
    trainer = TimeSeriesCVTrainer(checkpoint_dir=checkpoint_dir)

    report = trainer.run(dataset, model, n_splits=n_splits)

    # 输出报告
    print(report.summary())

    # 输出特征筛选排名
    from .feature_selector import FeatureSelector
    temp_selector = FeatureSelector()
    temp_selector._result = selection_result
    print()
    print(temp_selector.print_ranking(top_n=20))

    # 输出特征重要性趋势
    if trainer.importance_tracker:
        print()
        print(trainer.importance_tracker.summary())

    return report, selection_result, trainer.importance_tracker


def train_with_optimization(
    df,
    model_name: str = "lightgbm",
    task_type: str = "classification",
    horizon: str = "5d",
    min_rounds: int = 50,
    max_rounds: int = 80,
    news_df=None,
    macro_df=None,
    top_n_features: int = 40,
    checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR,
):
    """终极入口：因子工程 + 特征筛选 + 自动调参 + 收敛检测

    集成全部优化能力，输入原始 DataFrame 即可输出最优模型。

    Args:
        df:              OHLCV DataFrame
        model_name:      模型名称
        task_type:       任务类型
        horizon:         预测周期
        min_rounds:      最少调参轮数
        max_rounds:      最多调参轮数
        news_df:         新闻情绪数据（可选）
        macro_df:        宏观数据（可选）
        top_n_features:  保留特征数
        checkpoint_dir:  保存目录

    Returns:
        OptimizationResult
    """
    from .auto_optimizer import auto_optimize

    return auto_optimize(
        df,
        model_name=model_name,
        task_type=task_type,
        horizon=horizon,
        min_rounds=min_rounds,
        max_rounds=max_rounds,
        news_df=news_df,
        macro_df=macro_df,
        top_n_features=top_n_features,
        checkpoint_dir=checkpoint_dir,
    )
