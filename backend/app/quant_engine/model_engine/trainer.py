"""
训练编排器（Training Orchestrator）

负责：
1. 单股票训练流程编排
2. 批量训练（所有观察列表股票）
3. 增量训练 vs 全量训练
4. 训练任务管理（入库 qe_training_jobs）
5. 事件驱动再训练触发
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..feature_engineering.pipeline import FeaturePipeline
from ..models import QETrainingJob, QETrainingJobStatus
from ..data_layer.market_data import get_watchlist_symbols
from .registry import ModelManager
from .base import ModelMeta

logger = logging.getLogger(__name__)


class TrainingOrchestrator:
    """训练编排器

    用法：
        orchestrator = TrainingOrchestrator(session)
        result = orchestrator.train_single("600519.SH", horizon="5d")
        results = orchestrator.train_all(horizon="5d")
    """

    def __init__(self, session: Session):
        self.session = session
        self.pipeline = FeaturePipeline(session)
        self.model_manager = ModelManager(session)

    def train_single(
        self,
        symbol: str,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
        start_date: Optional[date] = None,
        auto_select: bool = False,
        dual_model: bool = True,
    ) -> dict:
        """训练单只股票的模型

        Args:
            symbol:      股票代码
            task:        预测任务
            algo:        算法类型（auto_select=True 时忽略）
            horizon:     预测周期
            start_date:  数据起始日
            auto_select: 是否自动选择最优算法
            dual_model:  是否同时训练分类+回归双模型

        Returns:
            训练结果字典
        """
        # 创建训练任务记录
        job = QETrainingJob(
            symbol=symbol,
            job_type="full_train" if start_date is None else "incremental",
            trigger="manual",
            status=QETrainingJobStatus.RUNNING.value,
            config_json={"task": task, "algo": algo, "horizon": horizon, "dual_model": dual_model},
            started_at=datetime.utcnow(),
        )
        self.session.add(job)
        self.session.flush()

        try:
            # ---- 分类模型训练（方向预测） ----
            X_cls, y_cls, feature_names = self.pipeline.build(
                symbol=symbol,
                start_date=start_date,
                horizon=horizon,
                task_type="classification",
            )
            if X_cls.empty:
                raise ValueError(f"特征构建失败: {symbol} 数据不足")

            if auto_select:
                model_cls, best_algo, comparison = self.model_manager.auto_select_best_model(
                    symbol, task, X_cls, y_cls
                )
                algo = best_algo
            else:
                model_cls, db_model_cls = self.model_manager.get_or_create_model(symbol, task, algo)
                model_cls.fit(X_cls, y_cls)

            model_cls, db_model_cls = self.model_manager.get_or_create_model(symbol, task, algo)

            # 保存分类模型版本
            train_dates = self.pipeline._load_and_merge(symbol, start_date, None)
            t_start = train_dates["trade_date"].min().date() if not train_dates.empty else None
            t_end = train_dates["trade_date"].max().date() if not train_dates.empty else None

            version_cls = self.model_manager.save_version(
                db_model_cls, model_cls, train_start=t_start, train_end=t_end
            )

            result = {
                "symbol": symbol,
                "task": task,
                "algo": algo,
                "version": version_cls.version,
                "metrics": model_cls.meta.metrics,
                "feature_count": len(feature_names),
                "train_samples": len(X_cls),
                "status": "completed",
            }

            # ---- 回归模型训练（收益率预测） ----
            if dual_model:
                try:
                    reg_task = task.replace("direction", "return")
                    X_reg, y_reg, _ = self.pipeline.build(
                        symbol=symbol,
                        start_date=start_date,
                        horizon=horizon,
                        task_type="regression",
                    )
                    if not X_reg.empty:
                        model_reg, db_model_reg = self.model_manager.get_or_create_model(
                            symbol, reg_task, algo
                        )
                        model_reg.fit(X_reg, y_reg)
                        version_reg = self.model_manager.save_version(
                            db_model_reg, model_reg, train_start=t_start, train_end=t_end
                        )
                        result["regression"] = {
                            "task": reg_task,
                            "version": version_reg.version,
                            "metrics": model_reg.meta.metrics,
                        }
                        logger.info(
                            "回归模型训练完成: symbol=%s, metrics=%s",
                            symbol, model_reg.meta.metrics
                        )
                except Exception as e:
                    logger.warning("回归模型训练失败（不影响分类模型）: symbol=%s, error=%s", symbol, e)
                    result["regression"] = {"status": "failed", "error": str(e)}

            # 更新任务状态
            job.status = QETrainingJobStatus.COMPLETED.value
            job.finished_at = datetime.utcnow()
            job.result_json = result
            self.session.commit()

            return result

        except Exception as e:
            job.status = QETrainingJobStatus.FAILED.value
            job.finished_at = datetime.utcnow()
            job.error_message = str(e)
            self.session.commit()
            logger.error("训练失败: symbol=%s, error=%s", symbol, e, exc_info=True)
            return {"symbol": symbol, "status": "failed", "error": str(e)}

    def train_all(
        self,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
        pinned_only: bool = True,
        auto_select: bool = False,
    ) -> list[dict]:
        """批量训练所有观察列表股票"""
        symbols = get_watchlist_symbols(self.session, pinned_only=pinned_only)
        if not symbols:
            logger.warning("无可训练股票")
            return []

        logger.info("开始批量训练: %d 只股票, algo=%s, horizon=%s", len(symbols), algo, horizon)
        results = []
        for symbol in symbols:
            result = self.train_single(symbol, task, algo, horizon, auto_select=auto_select)
            results.append(result)

        completed = sum(1 for r in results if r.get("status") == "completed")
        logger.info("批量训练完成: 成功=%d, 失败=%d", completed, len(results) - completed)
        return results

    def trigger_retrain(
        self,
        symbol: str,
        reason: str = "event_driven",
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
    ) -> dict:
        """事件触发的再训练

        当重大新闻出现时触发（由事件驱动模块调用）。
        """
        logger.info("事件驱动再训练: symbol=%s, reason=%s", symbol, reason)

        job = QETrainingJob(
            symbol=symbol,
            job_type="retrain",
            trigger="event",
            status=QETrainingJobStatus.PENDING.value,
            config_json={"task": task, "algo": algo, "horizon": horizon, "reason": reason},
        )
        self.session.add(job)
        self.session.flush()

        return self.train_single(symbol, task, algo, horizon)
