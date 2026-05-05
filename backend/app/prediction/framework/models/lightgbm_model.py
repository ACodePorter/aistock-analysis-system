"""
LightGBM 可插拔模型

特性：
- 支持 classification / regression
- 逐 boosting round 记录 train/val loss
- early stopping + log_evaluation 回调
- 特征重要性输出
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
from sklearn.preprocessing import StandardScaler

from .base_model import BaseModel, IterationLog, TrainResult

logger = logging.getLogger(__name__)


class _LGBMLogCallback:
    """采集 LightGBM 每轮 eval 指标"""

    def __init__(self):
        self.logs: List[Dict[str, float]] = []

    def __call__(self, env):
        row: Dict[str, float] = {"iteration": env.iteration}
        for ds_name, metric_name, val, is_higher in env.evaluation_result_list:
            row[f"{ds_name}_{metric_name}"] = float(val)
        self.logs.append(row)


class LightGBMModel(BaseModel):

    @property
    def name(self) -> str:
        return "lightgbm"

    def get_default_params(self) -> Dict[str, Any]:
        return {
            "n_estimators": 500,
            "learning_rate": 0.05,
            "max_depth": 6,
            "num_leaves": 31,
            "min_child_samples": 20,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "random_state": 42,
            "n_jobs": -1,
            "verbose": -1,
        }

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
    ) -> TrainResult:
        import lightgbm as lgb

        params = self._merge_params()

        self._scaler = StandardScaler()
        X_tr = self._scaler.fit_transform(X_train)
        X_va = self._scaler.transform(X_val) if X_val is not None else None

        eval_set = [(X_tr, y_train)]
        if X_va is not None:
            eval_set.append((X_va, y_val))

        log_cb = _LGBMLogCallback()
        callbacks = [
            lgb.early_stopping(50, verbose=False),
            log_cb,
        ]

        if self.task_type == "classification":
            self._model = lgb.LGBMClassifier(**params)
        else:
            self._model = lgb.LGBMRegressor(**params)

        self._model.fit(
            X_tr, y_train,
            eval_set=eval_set,
            callbacks=callbacks,
        )

        self._is_fitted = True
        self._feature_names = feature_names or []

        iteration_logs = self._parse_logs(log_cb.logs)

        best_iter = int(getattr(self._model, "best_iteration_", len(iteration_logs) - 1))
        best_val = float("inf")
        if iteration_logs and X_val is not None:
            val_losses = [l.val_loss for l in iteration_logs if l.val_loss is not None]
            if val_losses:
                best_val = min(val_losses)

        return TrainResult(
            model_name=self.name,
            task_type=self.task_type,
            iteration_logs=iteration_logs,
            best_iteration=best_iter,
            best_val_loss=best_val,
            feature_importance=self._get_importance(),
            train_samples=len(X_train),
            val_samples=len(X_val) if X_val is not None else 0,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("模型未训练")
        return self._model.predict(self._scaler.transform(X))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("模型未训练")
        X_s = self._scaler.transform(X)
        if self.task_type == "classification":
            return self._model.predict_proba(X_s)
        return self._model.predict(X_s).reshape(-1, 1)

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        artifact = {
            "model": self._model,
            "scaler": self._scaler,
            "task_type": self.task_type,
            "feature_names": self._feature_names,
            "params": self.params,
        }
        joblib.dump(artifact, path)
        logger.info("LightGBM model saved: %s", path)
        return path

    def load(self, path: str) -> None:
        artifact = joblib.load(path)
        self._model = artifact["model"]
        self._scaler = artifact["scaler"]
        self.task_type = artifact.get("task_type", self.task_type)
        self._feature_names = artifact.get("feature_names", [])
        self._is_fitted = True
        logger.info("LightGBM model loaded: %s", path)

    def _parse_logs(self, raw_logs: List[Dict]) -> List[IterationLog]:
        logs = []
        for row in raw_logs:
            it = row.get("iteration", len(logs))
            train_loss = None
            val_loss = None
            for k, v in row.items():
                if k == "iteration":
                    continue
                if "training" in k.lower() or "valid_0" in k.lower():
                    train_loss = v
                elif "valid_1" in k.lower():
                    val_loss = v
            logs.append(IterationLog(
                iteration=it,
                train_loss=train_loss if train_loss is not None else 0.0,
                val_loss=val_loss,
            ))
        return logs

    def _get_importance(self) -> Dict[str, float]:
        if not self._is_fitted or not hasattr(self._model, "feature_importances_"):
            return {}
        imp = self._model.feature_importances_
        names = self._feature_names
        if len(names) != len(imp):
            return {}
        total = float(imp.sum()) or 1.0
        return {n: float(v / total) for n, v in zip(names, imp)}
