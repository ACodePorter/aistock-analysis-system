"""
模型注册与版本管理（Model Registry）

负责：
- 每只股票的模型实例管理
- 模型版本持久化（数据库 + 文件系统）
- 模型热更新（加载最新版本到内存）
- 自动模型选择（AutoML-lite：比较 LightGBM vs XGBoost）
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, and_, update
from sqlalchemy.orm import Session

from ..models import (
    QEStockModel, QEModelVersion, QEModelStatus,
)
from .base import BaseQuantModel, ModelMeta
from .tree_models import LightGBMModel, XGBoostModel

logger = logging.getLogger(__name__)

# 模型文件存储根目录
MODEL_STORAGE_ROOT = os.environ.get(
    "QE_MODEL_STORAGE",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "storage", "qe_models")
)

# 支持的算法映射
ALGO_REGISTRY: dict[str, type[BaseQuantModel]] = {
    "lightgbm": LightGBMModel,
    "xgboost": XGBoostModel,
    # V2: "lstm": LSTMModel,
    # V3: "transformer": TransformerModel,
}


class ModelManager:
    """模型管理器

    管理每只股票的独立模型实例，支持：
    - 创建/注册新模型
    - 版本管理
    - 模型加载（热更新）
    - AutoML-lite 自动选择最优算法

    用法：
        manager = ModelManager(session)
        model = manager.get_or_create_model("600519.SH", "next_day_direction", "lightgbm")
    """

    def __init__(self, session: Session):
        self.session = session
        self._cache: dict[str, BaseQuantModel] = {}  # key = "symbol:task:algo"

    def get_or_create_model(
        self,
        symbol: str,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
    ) -> tuple[BaseQuantModel, QEStockModel]:
        """获取或创建股票模型实例

        Returns:
            (model_instance, db_record)
        """
        cache_key = f"{symbol}:{task}:{algo}"

        # 查找已有记录
        db_model = self.session.execute(
            select(QEStockModel).where(
                and_(
                    QEStockModel.symbol == symbol,
                    QEStockModel.task == task,
                    QEStockModel.algo == algo,
                )
            )
        ).scalar_one_or_none()

        if db_model is None:
            # 创建新记录
            db_model = QEStockModel(
                symbol=symbol,
                task=task,
                algo=algo,
                active_version=0,
                status=QEModelStatus.ACTIVE.value,
            )
            self.session.add(db_model)
            self.session.flush()
            logger.info("创建新模型记录: symbol=%s, task=%s, algo=%s", symbol, task, algo)

        # 尝试从缓存加载
        if cache_key in self._cache:
            return self._cache[cache_key], db_model

        # 尝试从文件加载最新版本
        model_instance = self._load_latest_version(db_model)
        if model_instance is None:
            # 新建空模型
            meta = ModelMeta(
                algo=algo,
                task="classification" if "direction" in task else "regression",
                version=0,
            )
            model_cls = ALGO_REGISTRY.get(algo, LightGBMModel)
            model_instance = model_cls(meta=meta)

        self._cache[cache_key] = model_instance
        return model_instance, db_model

    def save_version(
        self,
        db_model: QEStockModel,
        model_instance: BaseQuantModel,
        train_start: Optional[date] = None,
        train_end: Optional[date] = None,
    ) -> QEModelVersion:
        """保存新模型版本

        1. 创建版本记录
        2. 持久化模型文件
        3. 更新活跃版本
        """
        new_version = db_model.active_version + 1

        # 构造存储路径
        artifact_dir = os.path.join(
            MODEL_STORAGE_ROOT,
            db_model.symbol.replace(".", "_"),
            db_model.task,
            db_model.algo,
        )
        artifact_path = os.path.join(artifact_dir, f"v{new_version}.joblib")

        # 保存模型文件
        model_instance.save(artifact_path)

        # 取消旧版本的 is_active
        self.session.execute(
            update(QEModelVersion)
            .where(QEModelVersion.stock_model_id == db_model.id)
            .values(is_active=False)
        )

        # 创建新版本记录
        version_record = QEModelVersion(
            stock_model_id=db_model.id,
            version=new_version,
            artifact_path=artifact_path,
            features_used=model_instance.meta.feature_names,
            metrics_json=model_instance.meta.metrics,
            train_samples=model_instance.meta.train_samples,
            train_start=train_start,
            train_end=train_end,
            is_active=True,
        )
        self.session.add(version_record)

        # 更新主记录
        db_model.active_version = new_version
        db_model.updated_at = datetime.utcnow()
        self.session.flush()

        # 更新缓存
        cache_key = f"{db_model.symbol}:{db_model.task}:{db_model.algo}"
        self._cache[cache_key] = model_instance

        logger.info(
            "模型版本已保存: symbol=%s, task=%s, algo=%s, version=%d",
            db_model.symbol, db_model.task, db_model.algo, new_version
        )
        return version_record

    def _load_latest_version(self, db_model: QEStockModel) -> Optional[BaseQuantModel]:
        """从文件系统加载最新版本的模型"""
        version_record = self.session.execute(
            select(QEModelVersion)
            .where(
                and_(
                    QEModelVersion.stock_model_id == db_model.id,
                    QEModelVersion.is_active == True,  # noqa: E712
                )
            )
            .order_by(QEModelVersion.version.desc())
            .limit(1)
        ).scalar_one_or_none()

        if version_record is None or not version_record.artifact_path:
            return None

        if not os.path.exists(version_record.artifact_path):
            logger.warning("模型文件不存在: %s", version_record.artifact_path)
            return None

        model_cls = ALGO_REGISTRY.get(db_model.algo, LightGBMModel)
        model_instance = model_cls()
        model_instance.load(version_record.artifact_path)
        return model_instance

    def auto_select_best_model(
        self,
        symbol: str,
        task: str,
        X: "pd.DataFrame",
        y: "pd.Series",
        algos: Optional[list[str]] = None,
    ) -> tuple[BaseQuantModel, str, dict]:
        """AutoML-lite：在多个算法间自动选择最优模型

        Args:
            symbol: 股票代码
            task:   任务名称
            X:      特征矩阵
            y:      标签
            algos:  候选算法列表（默认 lightgbm + xgboost）

        Returns:
            (best_model, best_algo, comparison_metrics)
        """
        if algos is None:
            algos = ["lightgbm", "xgboost"]

        results: dict[str, dict] = {}
        best_model: Optional[BaseQuantModel] = None
        best_algo: str = algos[0]
        best_score: float = -float("inf")

        for algo in algos:
            model_cls = ALGO_REGISTRY.get(algo)
            if model_cls is None:
                continue

            task_type = "classification" if "direction" in task else "regression"
            meta = ModelMeta(algo=algo, task=task_type)
            model = model_cls(meta=meta)

            try:
                metrics = model.fit(X, y)
                results[algo] = metrics

                # 选择指标：分类用 AUC，回归用 R²
                score = metrics.get("auc", metrics.get("r2", 0))
                if score > best_score:
                    best_score = score
                    best_model = model
                    best_algo = algo

            except Exception as e:
                logger.error("算法 %s 训练失败: %s", algo, e)
                results[algo] = {"error": str(e)}

        logger.info(
            "AutoML 完成: symbol=%s, best_algo=%s, score=%.4f, comparison=%s",
            symbol, best_algo, best_score, results
        )
        return best_model, best_algo, results
