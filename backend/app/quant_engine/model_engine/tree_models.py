"""
树模型实现（LightGBM / XGBoost）

V1 核心模型：支持分类（上涨/下跌）和回归（未来收益率）任务。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, roc_auc_score, mean_squared_error, r2_score

from .base import BaseQuantModel, ModelMeta

logger = logging.getLogger(__name__)


class LightGBMModel(BaseQuantModel):
    """LightGBM 模型

    支持：
    - 分类任务（binary）
    - 回归任务
    - 增量训练（warm start）
    - 特征重要性
    """

    def __init__(self, meta: Optional[ModelMeta] = None, **extra_params):
        if meta is None:
            meta = ModelMeta(algo="lightgbm", task="classification")
        super().__init__(meta)
        self._extra_params = extra_params

    def _get_default_params(self) -> dict:
        """默认超参数"""
        base = {
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
        base.update(self.meta.params)
        base.update(self._extra_params)
        return base

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        """训练 LightGBM

        支持自动划分验证集，early stopping 防过拟合。
        """
        import lightgbm as lgb

        params = self._get_default_params()
        val_size = kwargs.get("val_size", 0.15)

        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=val_size, shuffle=False  # 时序数据不打乱
        )

        # 标准化
        self._scaler = StandardScaler()
        X_train_scaled = pd.DataFrame(
            self._scaler.fit_transform(X_train),
            columns=X_train.columns, index=X_train.index
        )
        X_val_scaled = pd.DataFrame(
            self._scaler.transform(X_val),
            columns=X_val.columns, index=X_val.index
        )

        # 构建回调
        callbacks = [
            lgb.early_stopping(50, verbose=False),
            lgb.log_evaluation(period=0),  # 静默
        ]

        if self.meta.task == "classification":
            model = lgb.LGBMClassifier(**params)
            model.fit(
                X_train_scaled, y_train,
                eval_set=[(X_val_scaled, y_val)],
                callbacks=callbacks,
            )
            val_pred = model.predict(X_val_scaled)
            val_proba = model.predict_proba(X_val_scaled)[:, 1]

            metrics = {
                "accuracy": float(accuracy_score(y_val, val_pred)),
                "auc": float(roc_auc_score(y_val, val_proba)) if len(y_val.unique()) > 1 else 0.0,
                "val_samples": len(y_val),
                "best_iteration": model.best_iteration_,
            }
        else:
            model = lgb.LGBMRegressor(**params)
            model.fit(
                X_train_scaled, y_train,
                eval_set=[(X_val_scaled, y_val)],
                callbacks=callbacks,
            )
            val_pred = model.predict(X_val_scaled)
            metrics = {
                "rmse": float(np.sqrt(mean_squared_error(y_val, val_pred))),
                "r2": float(r2_score(y_val, val_pred)),
                "val_samples": len(y_val),
                "best_iteration": model.best_iteration_,
            }

        self._model = model
        self._is_fitted = True
        self.meta.feature_names = list(X.columns)
        self.meta.train_samples = len(X)
        self.meta.metrics = metrics

        logger.info("LightGBM 训练完成: task=%s, metrics=%s", self.meta.task, metrics)
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("模型未训练")
        X_scaled = self._scaler.transform(X)
        return self._model.predict(X_scaled)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("模型未训练")
        X_scaled = self._scaler.transform(X)
        if self.meta.task == "classification":
            return self._model.predict_proba(X_scaled)
        else:
            pred = self._model.predict(X_scaled)
            return np.column_stack([1 - pred, pred])

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        artifact = {
            "model": self._model,
            "scaler": self._scaler,
            "meta": self.meta,
        }
        joblib.dump(artifact, path)
        logger.info("模型已保存: %s", path)
        return path

    def load(self, path: str) -> None:
        artifact = joblib.load(path)
        self._model = artifact["model"]
        self._scaler = artifact["scaler"]
        self.meta = artifact["meta"]
        self._is_fitted = True
        logger.info("模型已加载: %s", path)

    def get_feature_importance(self) -> dict[str, float]:
        if not self._is_fitted:
            return {}
        importance = self._model.feature_importances_
        names = self.meta.feature_names
        if len(names) != len(importance):
            return {}
        total = importance.sum() or 1
        return {name: float(imp / total) for name, imp in zip(names, importance)}


class XGBoostModel(BaseQuantModel):
    """XGBoost 模型

    与 LightGBM 接口一致，可互换使用。
    """

    def __init__(self, meta: Optional[ModelMeta] = None, **extra_params):
        if meta is None:
            meta = ModelMeta(algo="xgboost", task="classification")
        super().__init__(meta)
        self._extra_params = extra_params

    def _get_default_params(self) -> dict:
        base = {
            "n_estimators": 500,
            "learning_rate": 0.05,
            "max_depth": 6,
            "min_child_weight": 3,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "n_jobs": -1,
            "verbosity": 0,
            "eval_metric": "logloss" if self.meta.task == "classification" else "rmse",
        }
        base.update(self.meta.params)
        base.update(self._extra_params)
        return base

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        import xgboost as xgb

        params = self._get_default_params()
        val_size = kwargs.get("val_size", 0.15)

        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=val_size, shuffle=False
        )

        self._scaler = StandardScaler()
        X_train_scaled = pd.DataFrame(
            self._scaler.fit_transform(X_train),
            columns=X_train.columns, index=X_train.index
        )
        X_val_scaled = pd.DataFrame(
            self._scaler.transform(X_val),
            columns=X_val.columns, index=X_val.index
        )

        if self.meta.task == "classification":
            model = xgb.XGBClassifier(**params)
            model.fit(
                X_train_scaled, y_train,
                eval_set=[(X_val_scaled, y_val)],
                verbose=False,
            )
            val_pred = model.predict(X_val_scaled)
            val_proba = model.predict_proba(X_val_scaled)[:, 1]
            metrics = {
                "accuracy": float(accuracy_score(y_val, val_pred)),
                "auc": float(roc_auc_score(y_val, val_proba)) if len(y_val.unique()) > 1 else 0.0,
                "val_samples": len(y_val),
                "best_iteration": int(model.best_iteration) if hasattr(model, "best_iteration") else 0,
            }
        else:
            model = xgb.XGBRegressor(**params)
            model.fit(
                X_train_scaled, y_train,
                eval_set=[(X_val_scaled, y_val)],
                verbose=False,
            )
            val_pred = model.predict(X_val_scaled)
            metrics = {
                "rmse": float(np.sqrt(mean_squared_error(y_val, val_pred))),
                "r2": float(r2_score(y_val, val_pred)),
                "val_samples": len(y_val),
            }

        self._model = model
        self._is_fitted = True
        self.meta.feature_names = list(X.columns)
        self.meta.train_samples = len(X)
        self.meta.metrics = metrics

        logger.info("XGBoost 训练完成: task=%s, metrics=%s", self.meta.task, metrics)
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("模型未训练")
        X_scaled = self._scaler.transform(X)
        return self._model.predict(X_scaled)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("模型未训练")
        X_scaled = self._scaler.transform(X)
        if self.meta.task == "classification":
            return self._model.predict_proba(X_scaled)
        else:
            pred = self._model.predict(X_scaled)
            return np.column_stack([1 - pred, pred])

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        artifact = {
            "model": self._model,
            "scaler": self._scaler,
            "meta": self.meta,
        }
        joblib.dump(artifact, path)
        return path

    def load(self, path: str) -> None:
        artifact = joblib.load(path)
        self._model = artifact["model"]
        self._scaler = artifact["scaler"]
        self.meta = artifact["meta"]
        self._is_fitted = True

    def get_feature_importance(self) -> dict[str, float]:
        if not self._is_fitted:
            return {}
        importance = self._model.feature_importances_
        names = self.meta.feature_names
        if len(names) != len(importance):
            return {}
        total = importance.sum() or 1
        return {name: float(imp / total) for name, imp in zip(names, importance)}
