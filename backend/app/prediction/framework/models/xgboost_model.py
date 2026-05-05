"""
XGBoost 可插拔模型

特性：
- 支持 classification / regression
- 逐 boosting round 记录 train/val loss（通过 evals_result_）
- early stopping 防过拟合
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


class XGBoostModel(BaseModel):

    @property
    def name(self) -> str:
        return "xgboost"

    def get_default_params(self) -> Dict[str, Any]:
        return {
            "n_estimators": 500,
            "learning_rate": 0.05,
            "max_depth": 5,
            "min_child_weight": 3,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "n_jobs": -1,
            "verbosity": 0,
            "early_stopping_rounds": 50,
        }

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
    ) -> TrainResult:
        import xgboost as xgb

        params = self._merge_params()
        early_rounds = params.pop("early_stopping_rounds", 50)

        self._scaler = StandardScaler()
        X_tr = self._scaler.fit_transform(X_train)
        X_va = self._scaler.transform(X_val) if X_val is not None else None

        eval_set = [(X_tr, y_train)]
        if X_va is not None:
            eval_set.append((X_va, y_val))

        eval_metric = "logloss" if self.task_type == "classification" else "rmse"

        if self.task_type == "classification":
            self._model = xgb.XGBClassifier(
                eval_metric=eval_metric,
                early_stopping_rounds=early_rounds if X_va is not None else None,
                **params,
            )
        else:
            self._model = xgb.XGBRegressor(
                eval_metric=eval_metric,
                early_stopping_rounds=early_rounds if X_va is not None else None,
                **params,
            )

        self._model.fit(X_tr, y_train, eval_set=eval_set, verbose=False)

        self._is_fitted = True
        self._feature_names = feature_names or []

        # 通过 evals_result_ 获取逐迭代日志
        iteration_logs = self._parse_evals_result()

        best_iter = int(getattr(self._model, "best_iteration", len(iteration_logs) - 1))
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
        X_s = self._scaler.transform(X)
        return self._model.predict(X_s)

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
        logger.info("XGBoost model saved: %s", path)
        return path

    def load(self, path: str) -> None:
        artifact = joblib.load(path)
        self._model = artifact["model"]
        self._scaler = artifact["scaler"]
        self.task_type = artifact.get("task_type", self.task_type)
        self._feature_names = artifact.get("feature_names", [])
        self._is_fitted = True
        logger.info("XGBoost model loaded: %s", path)

    def _parse_evals_result(self) -> List[IterationLog]:
        """从 evals_result_ 解析逐迭代指标"""
        evals = getattr(self._model, "evals_result_", None)
        if not evals:
            return []
        logs = []
        ds_names = list(evals.keys())
        n_iters = max(len(v) for vals in evals.values() for v in vals.values()) if evals else 0
        for i in range(n_iters):
            train_loss = 0.0
            val_loss = None
            for ds_idx, ds_name in enumerate(ds_names):
                for metric_name, vals in evals[ds_name].items():
                    if i < len(vals):
                        if ds_idx == 0:
                            train_loss = float(vals[i])
                        elif ds_idx == 1:
                            val_loss = float(vals[i])
            logs.append(IterationLog(iteration=i, train_loss=train_loss, val_loss=val_loss))
        return logs

    def _get_importance(self) -> Dict[str, float]:
        if not self._is_fitted or not hasattr(self._model, "feature_importances_"):
            return {}
        imp = self._model.feature_importances_
        names = self._feature_names
        if len(names) != len(imp):
            return {}
        total = imp.sum() or 1.0
        return {n: float(v / total) for n, v in zip(names, imp)}
