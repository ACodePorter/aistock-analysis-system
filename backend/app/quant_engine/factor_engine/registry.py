"""
因子注册中心

管理所有因子的注册、查询、批量计算。
每个因子通过 @register_factor 装饰器注册到全局因子库。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FactorDefinition:
    """因子定义"""
    name: str
    category: str  # technical / news / macro / behavioral / cross_stock
    description: str = ""
    compute_fn: Optional[Callable] = None
    params: dict = field(default_factory=dict)
    data_type: str = "float"  # float / int / bool / category


class FactorRegistry:
    """全局因子注册中心（单例模式）"""

    _instance: Optional[FactorRegistry] = None
    _factors: dict[str, FactorDefinition]

    def __new__(cls) -> FactorRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._factors = {}
        return cls._instance

    def register(self, definition: FactorDefinition) -> None:
        """注册因子"""
        if definition.name in self._factors:
            logger.debug("覆盖已有因子注册: %s", definition.name)
        self._factors[definition.name] = definition

    def get(self, name: str) -> Optional[FactorDefinition]:
        return self._factors.get(name)

    def list_factors(self, category: Optional[str] = None) -> list[FactorDefinition]:
        """列出所有（或某类别的）已注册因子"""
        if category:
            return [f for f in self._factors.values() if f.category == category]
        return list(self._factors.values())

    def compute_factor(self, name: str, df: pd.DataFrame, **kwargs) -> pd.Series:
        """计算单个因子

        Args:
            name: 因子名称
            df:   包含必要源数据的 DataFrame（至少含 close 列）
            **kwargs: 覆写默认参数

        Returns:
            pd.Series，因子值序列（与 df 行对齐）
        """
        defn = self._factors.get(name)
        if defn is None:
            raise KeyError(f"因子未注册: {name}")
        if defn.compute_fn is None:
            raise ValueError(f"因子 {name} 无计算函数")
        params = {**defn.params, **kwargs}
        return defn.compute_fn(df, **params)

    def compute_all(
        self,
        df: pd.DataFrame,
        categories: Optional[list[str]] = None,
        factor_names: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """批量计算多个因子，返回包含所有因子列的 DataFrame

        Args:
            df:           源数据
            categories:   只计算指定类别（可选）
            factor_names: 只计算指定因子（可选，优先于 categories）
        """
        result = df.copy()
        targets = []

        if factor_names:
            for name in factor_names:
                defn = self._factors.get(name)
                if defn and defn.compute_fn:
                    targets.append(defn)
        else:
            for defn in self._factors.values():
                if defn.compute_fn is None:
                    continue
                if categories and defn.category not in categories:
                    continue
                targets.append(defn)

        for defn in targets:
            try:
                result[defn.name] = defn.compute_fn(df, **defn.params)
            except Exception as e:
                logger.warning("因子 %s 计算失败: %s", defn.name, e)
                result[defn.name] = float("nan")

        return result


def register_factor(
    name: str,
    category: str,
    description: str = "",
    params: Optional[dict] = None,
    data_type: str = "float",
):
    """装饰器：注册因子计算函数"""
    def decorator(fn: Callable) -> Callable:
        registry = FactorRegistry()
        registry.register(FactorDefinition(
            name=name,
            category=category,
            description=description,
            compute_fn=fn,
            params=params or {},
            data_type=data_type,
        ))
        return fn
    return decorator
