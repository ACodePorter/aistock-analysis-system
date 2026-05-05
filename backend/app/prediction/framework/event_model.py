"""
事件驱动预测模型（Event-driven Model）

独立于主模型的轻量级模型，专门学习事件对股价的影响。
可独立使用，也可与主模型融合为 ensemble。

功能：
1. 仅使用事件特征训练，预测事件后 N 天收益方向/幅度
2. 支持 GradientBoosting (默认) 和 LightGBM
3. 提供与主模型一致的 train/predict/evaluate 接口
4. 事件发生时自动激活，无事件时退化为 hold 信号
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.metrics import accuracy_score, f1_score, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


@dataclass
class EventModelResult:
    """事件模型训练/评估结果"""
    model_type: str = "event_gradient_boosting"
    task_type: str = "classification"
    n_samples: int = 0
    n_features: int = 0
    n_event_samples: int = 0
    cv_scores: List[float] = field(default_factory=list)
    mean_score: float = 0.0
    feature_importance: Dict[str, float] = field(default_factory=dict)
    best_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EventPrediction:
    """事件模型的预测输出"""
    symbol: str
    prediction_date: datetime.date
    predicted_direction: int = 0  # 1=up, -1=down, 0=neutral
    predicted_return: float = 0.0
    confidence: float = 0.0
    event_triggered: bool = False
    active_events: List[str] = field(default_factory=list)
    event_intensity: float = 0.0


class EventDrivenModel:
    """事件驱动预测模型

    Args:
        task_type:          classification / regression
        event_threshold:    最小事件强度（低于此值视为无事件）
        n_splits:           时间序列交叉验证折数
        min_event_samples:  最少事件样本数（不足则跳过训练）
    """

    def __init__(
        self,
        task_type: str = "classification",
        event_threshold: float = 0.1,
        n_splits: int = 5,
        min_event_samples: int = 30,
    ):
        self.task_type = task_type
        self.event_threshold = event_threshold
        self.n_splits = n_splits
        self.min_event_samples = min_event_samples

        self.model = None
        self.scaler = StandardScaler()
        self.feature_names: List[str] = []
        self.is_trained = False

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        event_mask: Optional[np.ndarray] = None,
    ) -> EventModelResult:
        """训练事件模型

        Args:
            X:              特征矩阵（事件因子 + 少量基础因子）
            y:              标签（方向/收益率）
            feature_names:  特征列名
            event_mask:     布尔数组，True 表示该样本存在事件
        """
        self.feature_names = feature_names or [f"f{i}" for i in range(X.shape[1])]

        # 仅使用有事件的样本训练（如提供 event_mask）
        if event_mask is not None:
            n_events = int(event_mask.sum())
            if n_events < self.min_event_samples:
                logger.warning(
                    "Event samples (%d) below minimum (%d), using all samples",
                    n_events, self.min_event_samples,
                )
            else:
                X = X[event_mask]
                y = y[event_mask]
                logger.info("Training on %d event samples (of %d total)", n_events, len(event_mask))

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = self.scaler.fit_transform(X)

        if self.task_type == "classification":
            self.model = GradientBoostingClassifier(
                n_estimators=150,
                learning_rate=0.05,
                max_depth=4,
                min_samples_leaf=10,
                subsample=0.8,
                random_state=42,
            )
        else:
            self.model = GradientBoostingRegressor(
                n_estimators=150,
                learning_rate=0.05,
                max_depth=4,
                min_samples_leaf=10,
                subsample=0.8,
                random_state=42,
            )

        # 时间序列交叉验证
        n_effective_splits = min(self.n_splits, max(2, len(X_scaled) // 30))
        tscv = TimeSeriesSplit(n_splits=n_effective_splits)
        cv_scores = []

        for train_idx, val_idx in tscv.split(X_scaled):
            X_tr, X_val = X_scaled[train_idx], X_scaled[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]

            self.model.fit(X_tr, y_tr)
            y_pred = self.model.predict(X_val)

            if self.task_type == "classification":
                score = accuracy_score(y_val, y_pred)
            else:
                score = -mean_squared_error(y_val, y_pred)
            cv_scores.append(score)

        # 用全部数据做最终训练
        self.model.fit(X_scaled, y)
        self.is_trained = True

        # 特征重要性
        importance = dict(zip(
            self.feature_names,
            self.model.feature_importances_.tolist(),
        ))
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

        result = EventModelResult(
            task_type=self.task_type,
            n_samples=len(X),
            n_features=X.shape[1],
            n_event_samples=int(event_mask.sum()) if event_mask is not None else len(X),
            cv_scores=cv_scores,
            mean_score=float(np.mean(cv_scores)) if cv_scores else 0.0,
            feature_importance=importance,
        )

        logger.info(
            "Event model trained: %d samples, %d features, mean_cv=%.4f",
            result.n_samples, result.n_features, result.mean_score,
        )
        return result

    def predict(
        self,
        X: np.ndarray,
        event_intensities: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """预测

        无事件的样本返回 0（hold / zero return）。
        """
        if not self.is_trained or self.model is None:
            return np.zeros(len(X))

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = self.scaler.transform(X)
        predictions = self.model.predict(X_scaled)

        # 无事件时退化为 neutral
        if event_intensities is not None:
            no_event_mask = event_intensities < self.event_threshold
            predictions[no_event_mask] = 0

        return predictions

    def predict_single(
        self,
        features: Dict[str, float],
        event_intensity: float = 0.0,
        symbol: str = "",
        prediction_date: Optional[datetime.date] = None,
    ) -> EventPrediction:
        """单条预测（用于实时推理）"""
        if prediction_date is None:
            prediction_date = datetime.date.today()

        x = np.array([[features.get(f, 0.0) for f in self.feature_names]])
        pred = self.predict(x, np.array([event_intensity]))

        direction = 0
        ret = 0.0
        if self.task_type == "classification":
            direction = int(pred[0])
            ret = direction * 0.01
        else:
            ret = float(pred[0])
            direction = 1 if ret > 0.002 else (-1 if ret < -0.002 else 0)

        active = []
        for cat_name in ("earnings_count", "policy_count", "industry_count", "breaking_count"):
            if features.get(cat_name, 0) > 0:
                active.append(cat_name.replace("_count", ""))

        return EventPrediction(
            symbol=symbol,
            prediction_date=prediction_date,
            predicted_direction=direction,
            predicted_return=ret,
            confidence=min(1.0, event_intensity) if event_intensity > self.event_threshold else 0.0,
            event_triggered=event_intensity >= self.event_threshold,
            active_events=active,
            event_intensity=event_intensity,
        )

    def evaluate(
        self,
        X: np.ndarray,
        y: np.ndarray,
        event_mask: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """评估模型性能

        分别输出全样本指标和事件样本指标。
        """
        if not self.is_trained:
            return {"error": -1}

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = self.scaler.transform(X)
        y_pred = self.model.predict(X_scaled)

        metrics = {}
        if self.task_type == "classification":
            metrics["accuracy_all"] = accuracy_score(y, y_pred)
            metrics["f1_all"] = f1_score(y, y_pred, average="macro", zero_division=0)
        else:
            metrics["mse_all"] = mean_squared_error(y, y_pred)
            direction_correct = ((y_pred > 0) == (y > 0)).mean()
            metrics["direction_accuracy_all"] = float(direction_correct)

        if event_mask is not None and event_mask.sum() > 5:
            y_evt = y[event_mask]
            pred_evt = y_pred[event_mask]
            if self.task_type == "classification":
                metrics["accuracy_event"] = accuracy_score(y_evt, pred_evt)
                metrics["f1_event"] = f1_score(y_evt, pred_evt, average="macro", zero_division=0)
            else:
                metrics["mse_event"] = mean_squared_error(y_evt, pred_evt)
                dir_corr = ((pred_evt > 0) == (y_evt > 0)).mean()
                metrics["direction_accuracy_event"] = float(dir_corr)

        return metrics


# ===================================================================
# 融合接口：事件模型 + 主模型
# ===================================================================

def blend_predictions(
    main_predictions: np.ndarray,
    event_predictions: np.ndarray,
    event_intensities: np.ndarray,
    event_weight_base: float = 0.3,
    intensity_scaling: bool = True,
) -> np.ndarray:
    """融合主模型和事件模型的预测

    事件发生时提高事件模型权重；无事件时仅使用主模型。

    Args:
        main_predictions:    主模型预测
        event_predictions:   事件模型预测
        event_intensities:   事件强度（0~1+）
        event_weight_base:   事件模型基础权重
        intensity_scaling:   是否根据事件强度动态调整权重
    """
    n = len(main_predictions)
    blended = np.zeros(n)

    for i in range(n):
        intensity = event_intensities[i]

        if intensity < 0.1:
            blended[i] = main_predictions[i]
        else:
            if intensity_scaling:
                event_w = min(0.7, event_weight_base + 0.2 * intensity)
            else:
                event_w = event_weight_base
            main_w = 1.0 - event_w
            blended[i] = main_w * main_predictions[i] + event_w * event_predictions[i]

    return blended
