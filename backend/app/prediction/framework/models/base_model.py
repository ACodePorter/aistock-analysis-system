"""
统一模型基类（Abstract Base Model）

所有可插拔模型必须继承 BaseModel 并实现全部抽象方法。
设计原则：
- train() 返回迭代级别的训练日志，便于后续绘制 loss 曲线
- predict() / predict_proba() 分别用于回归和分类
- evaluate() 由外部 Evaluator 调用，模型自身只负责推理
- save() / load() 负责序列化，训练器负责「何时存」
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class IterationLog:
    """单次迭代（boosting round / epoch）的指标记录"""
    iteration: int
    train_loss: float
    val_loss: Optional[float] = None
    extra_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrainResult:
    """单次 train() 调用的完整输出"""
    model_name: str
    task_type: str                              # classification / regression
    iteration_logs: List[IterationLog] = field(default_factory=list)
    best_iteration: int = 0
    best_val_loss: float = float("inf")
    final_metrics: Dict[str, float] = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    train_samples: int = 0
    val_samples: int = 0


class BaseModel(ABC):
    """可插拔模型的统一接口

    子类须实现：train / predict / predict_proba / save / load / name
    """

    def __init__(self, task_type: str = "regression", params: Optional[Dict] = None):
        """
        Args:
            task_type: "classification" 或 "regression"
            params:    模型超参数（可覆盖默认值）
        """
        self.task_type = task_type
        self.params = params or {}
        self._is_fitted = False

    @property
    @abstractmethod
    def name(self) -> str:
        """模型名称标识，如 'xgboost' / 'lightgbm' / 'lstm'"""
        ...

    @abstractmethod
    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
    ) -> TrainResult:
        """训练模型

        Args:
            X_train / y_train: 训练集
            X_val / y_val:     验证集（若为 None 则不做 early stopping）
            feature_names:     特征名列表

        Returns:
            TrainResult: 包含逐迭代指标
        """
        ...

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """回归预测 / 分类标签"""
        ...

    @abstractmethod
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """分类概率 shape=(n, 2)；回归任务可返回 point estimate"""
        ...

    @abstractmethod
    def save(self, path: str) -> str:
        """保存模型到 path，返回实际路径"""
        ...

    @abstractmethod
    def load(self, path: str) -> None:
        """从 path 加载模型"""
        ...

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    def get_default_params(self) -> Dict[str, Any]:
        """返回该模型的默认超参数（子类可覆盖）"""
        return {}

    def _merge_params(self) -> Dict[str, Any]:
        """合并默认参数 + 用户传入参数"""
        merged = self.get_default_params()
        merged.update(self.params)
        return merged
