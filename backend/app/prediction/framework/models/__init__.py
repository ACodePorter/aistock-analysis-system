"""
可插拔模型注册中心

使用方式：
    from .models import MODEL_REGISTRY, get_model
    model = get_model("lightgbm", task_type="classification", params={...})
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from .base_model import BaseModel, TrainResult, IterationLog

# 延迟导入避免强依赖
_REGISTRY: Dict[str, Type[BaseModel]] = {}


def register_model(name: str, cls: Type[BaseModel]) -> None:
    _REGISTRY[name] = cls


def get_model(name: str, task_type: str = "regression", params: Optional[dict] = None) -> BaseModel:
    """工厂方法：按名称获取模型实例"""
    if name not in _REGISTRY:
        _try_lazy_register(name)
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "(none)"
        raise ValueError(f"Unknown model '{name}'. Available: {available}")
    return _REGISTRY[name](task_type=task_type, params=params)


def list_models() -> list[str]:
    for n in ("xgboost", "lightgbm", "lstm"):
        _try_lazy_register(n)
    return sorted(_REGISTRY.keys())


def _try_lazy_register(name: str) -> None:
    """按需导入并注册模型"""
    if name in _REGISTRY:
        return
    try:
        if name == "xgboost":
            from .xgboost_model import XGBoostModel
            register_model("xgboost", XGBoostModel)
        elif name == "lightgbm":
            from .lightgbm_model import LightGBMModel
            register_model("lightgbm", LightGBMModel)
        elif name == "lstm":
            from .lstm_model import LSTMModel
            register_model("lstm", LSTMModel)
    except ImportError:
        pass


__all__ = [
    "BaseModel", "TrainResult", "IterationLog",
    "get_model", "list_models", "register_model",
]
