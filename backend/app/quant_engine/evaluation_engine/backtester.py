"""
回测引擎（Backtester）

核心功能：
1. Walk-forward 回测：按时间滚动训练+预测，验证真实场景表现
2. Holdout 回测：固定训练/测试集分割
3. 预测回填：对比历史预测 vs 实际结果
4. 结果汇总存储至 qe_evaluation_runs / qe_evaluation_metrics

关键设计：
- 时间严格分离，防止未来信息泄漏
- 支持分类（方向预测）和回归（收益率预测）两种模式
- 每次回测自动记录评估运行并持久化指标
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select, and_, update
from sqlalchemy.orm import Session

from ..models import (
    QEPrediction, QEEvaluationRun, QEEvaluationMetric,
    QEStockModel, QEModelVersion,
)
from ..feature_engineering.pipeline import FeaturePipeline
from ..model_engine.registry import ModelManager
from .metrics import (
    compute_classification_metrics,
    compute_regression_metrics,
    compute_pnl_metrics,
)

logger = logging.getLogger(__name__)

# 预测周期到天数映射
HORIZON_DAYS = {"1d": 1, "5d": 5, "10d": 10, "20d": 20}


class Backtester:
    """回测引擎

    用法：
        bt = Backtester(session)
        # Walk-forward 回测
        result = bt.walk_forward("600519.SH", train_window=500, test_window=20)
        # 预测 vs 实际回填
        bt.backfill_actuals("600519.SH")
    """

    def __init__(self, session: Session):
        self.session = session
        self.pipeline = FeaturePipeline(session)
        self.model_manager = ModelManager(session)

    # -------------------------------------------------------
    # Walk-Forward 回测
    # -------------------------------------------------------
    def walk_forward(
        self,
        symbol: str,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
        train_window: int = 500,
        test_window: int = 20,
        step: int = 20,
    ) -> dict:
        """Walk-forward 滚动回测

        把历史数据分成多个时间窗口，每个窗口：
        1. 用前 train_window 个样本训练
        2. 用后 test_window 个样本预测
        3. 对比预测和实际结果

        Args:
            symbol:        股票代码
            train_window:  训练窗口大小（交易日数）
            test_window:   测试窗口大小
            step:          窗口滑动步长

        Returns:
            {'run_id': ..., 'metrics': ..., 'predictions': [...]}
        """
        logger.info(
            "开始 Walk-Forward 回测: symbol=%s, train=%d, test=%d, step=%d",
            symbol, train_window, test_window, step,
        )

        # 构建全量数据
        X_all, y_all, feature_names = self.pipeline.build(
            symbol=symbol, horizon=horizon, normalize="zscore"
        )
        if len(X_all) < train_window + test_window:
            return {"error": f"数据不足: 需要至少 {train_window + test_window} 样本, 现有 {len(X_all)}"}

        all_predictions = []
        all_actuals = []
        all_probs = []

        n = len(X_all)
        start = 0
        while start + train_window + test_window <= n:
            train_end = start + train_window
            test_end = min(train_end + test_window, n)

            X_train = X_all.iloc[start:train_end]
            y_train = y_all.iloc[start:train_end]
            X_test = X_all.iloc[train_end:test_end]
            y_test = y_all.iloc[train_end:test_end]

            # 训练
            model, _ = self.model_manager.get_or_create_model(symbol, task, algo)
            model.fit(X_train, y_train)

            # 预测
            preds = model.predict(X_test)
            probs = model.predict_proba(X_test)

            all_predictions.extend(preds.tolist())
            all_actuals.extend(y_test.tolist())
            if probs is not None:
                if getattr(probs, "ndim", 1) == 2 and probs.shape[1] >= 2:
                    all_probs.extend(probs[:, 1].tolist())
                else:
                    all_probs.extend(np.asarray(probs).reshape(-1).tolist())

            start += step

        # 计算指标
        y_true = np.array(all_actuals)
        y_pred = np.array(all_predictions)
        y_prob = np.array(all_probs) if all_probs else None

        cls_metrics = compute_classification_metrics(y_true, y_pred, y_prob)

        # 模拟 PnL（方向正确则获得实际收益，否则损失）
        simulated_returns = pd.Series(dtype=float)
        horizon_days = HORIZON_DAYS.get(horizon, 5)
        if len(y_true) > 0:
            # 简化：假设方向预测正确时收益=+abs(收益)，错误时=-abs(收益)
            # 这里用真实方向和预测方向的一致性
            correct = (y_true == y_pred).astype(float)
            # 假设每笔固定回报率 0.5%（正确时为正，错误时为负）
            base_ret = 0.005 * horizon_days
            simulated_returns = pd.Series(
                np.where(correct, base_ret, -base_ret)
            )

        pnl_metrics = compute_pnl_metrics(simulated_returns)

        all_metrics = {**cls_metrics, **pnl_metrics}

        # 存储评估结果
        run = QEEvaluationRun(
            run_type="walk_forward",
            scope="symbol",
            symbols={"symbols": [symbol]},
            period_start=None,
            period_end=None,
            status="completed",
            summary_json=all_metrics,
        )
        self.session.add(run)
        self.session.flush()

        for name, value in all_metrics.items():
            self.session.add(QEEvaluationMetric(
                evaluation_run_id=run.id,
                metric_name=name,
                metric_value=float(value) if value is not None else None,
                symbol=symbol,
                horizon=horizon,
            ))
        self.session.commit()

        logger.info(
            "Walk-Forward 完成: symbol=%s, accuracy=%.4f, sharpe=%.2f",
            symbol, cls_metrics.get("accuracy", 0), pnl_metrics.get("sharpe", 0),
        )

        return {
            "run_id": run.id,
            "symbol": symbol,
            "total_predictions": len(all_predictions),
            "metrics": all_metrics,
        }

    # -------------------------------------------------------
    # Holdout 回测
    # -------------------------------------------------------
    def holdout_evaluation(
        self,
        symbol: str,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
        test_ratio: float = 0.2,
    ) -> dict:
        """Holdout 回测：按时间分割训练/测试集"""
        X_all, y_all, feature_names = self.pipeline.build(
            symbol=symbol, horizon=horizon, normalize="zscore"
        )
        if len(X_all) < 50:
            return {"error": f"数据不足: 需要至少 50 样本, 现有 {len(X_all)}"}

        split_idx = int(len(X_all) * (1 - test_ratio))
        X_train, X_test = X_all.iloc[:split_idx], X_all.iloc[split_idx:]
        y_train, y_test = y_all.iloc[:split_idx], y_all.iloc[split_idx:]

        model, _ = self.model_manager.get_or_create_model(symbol, task, algo)
        model.fit(X_train, y_train)

        preds = model.predict(X_test)
        probs = model.predict_proba(X_test)
        probs_for_auc = probs[:, 1] if probs is not None and getattr(probs, "ndim", 1) == 2 and probs.shape[1] >= 2 else probs

        cls_metrics = compute_classification_metrics(
            y_test.values, preds, probs_for_auc
        )

        run = QEEvaluationRun(
            run_type="holdout",
            scope="symbol",
            symbols={"symbols": [symbol]},
            status="completed",
            summary_json=cls_metrics,
        )
        self.session.add(run)
        self.session.flush()

        for name, value in cls_metrics.items():
            self.session.add(QEEvaluationMetric(
                evaluation_run_id=run.id,
                metric_name=name,
                metric_value=float(value) if value is not None else None,
                symbol=symbol,
                horizon=horizon,
            ))
        self.session.commit()

        return {
            "run_id": run.id,
            "symbol": symbol,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "metrics": cls_metrics,
        }

    # -------------------------------------------------------
    # 预测回填（对比预测 vs 实际）
    # -------------------------------------------------------
    def backfill_actuals(self, symbol: Optional[str] = None) -> int:
        """对已到期的预测记录回填实际收益率和方向

        查找 target_date <= today 且 actual_return IS NULL 的预测记录，
        从 PriceDaily 中获取实际收益率并更新。

        Returns:
            更新的记录数
        """
        from ...core.models import PriceDaily

        today = date.today()

        query = (
            select(QEPrediction)
            .where(
                and_(
                    QEPrediction.target_date <= today,
                    QEPrediction.actual_return.is_(None),
                )
            )
        )
        if symbol:
            query = query.where(QEPrediction.symbol == symbol)

        predictions = self.session.execute(query).scalars().all()
        if not predictions:
            return 0

        updated = 0
        for pred in predictions:
            # 获取预测日和目标日的价格
            prices = self.session.execute(
                select(PriceDaily.trade_date, PriceDaily.close)
                .where(
                    and_(
                        PriceDaily.symbol == pred.symbol,
                        PriceDaily.trade_date.in_([pred.predict_date, pred.target_date]),
                    )
                )
                .order_by(PriceDaily.trade_date)
            ).all()

            if len(prices) < 2:
                continue

            price_map = {p[0]: p[1] for p in prices}
            p_start = price_map.get(pred.predict_date)
            p_end = price_map.get(pred.target_date)

            if p_start and p_end and p_start > 0:
                actual_ret = (p_end - p_start) / p_start
                pred.actual_return = actual_ret
                pred.actual_direction = 1 if actual_ret > 0 else 0
                updated += 1

        if updated > 0:
            self.session.commit()

        logger.info("预测回填完成: %d 条记录已更新", updated)
        return updated

    # -------------------------------------------------------
    # 批量回测所有观察列表
    # -------------------------------------------------------
    def backtest_all(
        self,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
        method: str = "holdout",
    ) -> list[dict]:
        """批量回测所有观察列表股票"""
        from ..data_layer.market_data import get_watchlist_symbols

        symbols = get_watchlist_symbols(self.session)
        results = []
        for sym in symbols:
            if method == "walk_forward":
                r = self.walk_forward(sym, task, algo, horizon)
            else:
                r = self.holdout_evaluation(sym, task, algo, horizon)
            results.append(r)
        return results

    # -------------------------------------------------------
    # 回归模型 Walk-Forward 回测
    # -------------------------------------------------------
    def walk_forward_regression(
        self,
        symbol: str,
        algo: str = "lightgbm",
        horizon: str = "5d",
        train_window: int = 500,
        test_window: int = 20,
        step: int = 20,
    ) -> dict:
        """Walk-forward 滚动回测（回归模式：预测收益率）

        训练回归模型预测未来收益率，使用收益率回测PnL指标。
        """
        reg_task = "next_day_return"
        logger.info("开始回归 Walk-Forward: symbol=%s", symbol)

        X_all, y_all, feature_names = self.pipeline.build(
            symbol=symbol, horizon=horizon, normalize="zscore",
            task_type="regression",
        )
        if len(X_all) < train_window + test_window:
            return {"error": f"数据不足: 需要至少 {train_window + test_window}, 现有 {len(X_all)}"}

        all_preds = []
        all_actuals = []

        n = len(X_all)
        start = 0
        while start + train_window + test_window <= n:
            train_end = start + train_window
            test_end = min(train_end + test_window, n)

            X_train = X_all.iloc[start:train_end]
            y_train = y_all.iloc[start:train_end]
            X_test = X_all.iloc[train_end:test_end]
            y_test = y_all.iloc[train_end:test_end]

            model, _ = self.model_manager.get_or_create_model(symbol, reg_task, algo)
            model.fit(X_train, y_train)
            preds = model.predict(X_test)

            all_preds.extend(preds.tolist())
            all_actuals.extend(y_test.tolist())
            start += step

        y_true = np.array(all_actuals)
        y_pred = np.array(all_preds)

        reg_metrics = compute_regression_metrics(y_true, y_pred)

        # 使用预测收益率模拟交易（预测为正则做多，否则空仓）
        simulated_returns = pd.Series(
            np.where(y_pred > 0, y_true, 0)
        )
        pnl_metrics = compute_pnl_metrics(simulated_returns)

        all_metrics = {**reg_metrics, **pnl_metrics}

        run = QEEvaluationRun(
            run_type="walk_forward_regression",
            scope="symbol",
            symbols={"symbols": [symbol]},
            status="completed",
            summary_json=all_metrics,
        )
        self.session.add(run)
        self.session.flush()

        for name, value in all_metrics.items():
            self.session.add(QEEvaluationMetric(
                evaluation_run_id=run.id,
                metric_name=name,
                metric_value=float(value) if value is not None else None,
                symbol=symbol,
                horizon=horizon,
            ))
        self.session.commit()

        logger.info(
            "回归 Walk-Forward 完成: symbol=%s, rmse=%.4f, sharpe=%.2f, direction_acc=%.4f",
            symbol, reg_metrics.get("rmse", 0), pnl_metrics.get("sharpe", 0),
            reg_metrics.get("direction_accuracy", 0),
        )

        return {
            "run_id": run.id,
            "symbol": symbol,
            "total_predictions": len(all_preds),
            "metrics": all_metrics,
        }
