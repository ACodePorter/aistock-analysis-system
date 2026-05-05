"""
模型基类（Base Model Interface）

定义所有量化模型必须实现的接口，用于统一管理和切换模型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class ModelMeta:
    """模型元数据"""
    algo: str                             # 算法名称（lightgbm / xgboost / lstm）
    task: str                             # 任务类型（classification / regression）
    version: int = 0                      # 版本号
    params: dict = field(default_factory=dict)  # 超参数
    feature_names: list[str] = field(default_factory=list)
    train_samples: int = 0
    metrics: dict = field(default_factory=dict)


@dataclass
class PredictionResult:
    """预测结果数据类"""
    symbol: str
    predict_date: str
    horizon: str
    # 分类输出
    direction_prob_up: Optional[float] = None
    direction_prob_down: Optional[float] = None
    predicted_direction: Optional[int] = None  # 1=up, 0=down
    # 回归输出
    predicted_return: Optional[float] = None
    # 可解释性
    feature_importance: Optional[dict[str, float]] = None
    confidence: Optional[float] = None


class BaseQuantModel(ABC):
    """量化模型抽象基类

    所有模型实现必须继承此类并实现以下方法：
    - fit: 训练
    - predict: 推理
    - predict_proba: 概率预测（分类任务）
    - save / load: 持久化
    - get_feature_importance: 特征重要性
    """

    def __init__(self, meta: ModelMeta):
        self.meta = meta
        self._model: Any = None
        self._scaler: Any = None
        self._is_fitted: bool = False

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> dict:
        """训练模型

        Args:
            X: 特征矩阵
            y: 标签

        Returns:
            训练指标字典
        """
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """推理预测"""
        ...

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """概率预测（分类任务返回 [n_samples, 2]，回归任务返回置信区间）"""
        ...

    @abstractmethod
    def save(self, path: str) -> str:
        """保存模型到指定路径，返回实际保存路径"""
        ...

    @abstractmethod
    def load(self, path: str) -> None:
        """从指定路径加载模型"""
        ...

    @abstractmethod
    def get_feature_importance(self) -> dict[str, float]:
        """返回特征重要性字典"""
        ...

    def get_prediction_result(
        self,
        X: pd.DataFrame,
        symbol: str,
        predict_date: str,
        horizon: str,
    ) -> PredictionResult:
        """统一的预测结果生成"""
        result = PredictionResult(
            symbol=symbol,
            predict_date=predict_date,
            horizon=horizon,
        )

        if self.meta.task == "classification":
            probas = self.predict_proba(X)
            if probas.ndim == 2 and probas.shape[1] == 2:
                result.direction_prob_down = float(probas[0, 0])
                result.direction_prob_up = float(probas[0, 1])
                result.predicted_direction = int(probas[0, 1] > 0.5)
                result.confidence = float(max(probas[0, 0], probas[0, 1]))
        else:
            pred = self.predict(X)
            result.predicted_return = float(pred[0])
            result.confidence = 0.6  # 回归任务的默认置信度

        result.feature_importance = self.get_feature_importance()
        return result

    def merge_regression_result(
        self,
        pred_result: PredictionResult,
        regression_model: "BaseQuantModel",
        X: pd.DataFrame,
    ) -> PredictionResult:
        """将回归模型的预测收益率合并到分类模型的预测结果中"""
        try:
            reg_pred = regression_model.predict(X)
            pred_result.predicted_return = float(reg_pred[0])
        except Exception:
            pass
        return pred_result
