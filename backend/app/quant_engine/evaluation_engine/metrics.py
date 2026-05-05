"""
评估指标计算模块

包含：
- 分类任务指标：accuracy, precision, recall, f1, AUC
- 回归任务指标：RMSE, MAE, R²
- 交易模拟指标：PnL, 最大回撤, 夏普比率, 胜率
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: Optional[np.ndarray] = None,
) -> dict[str, float]:
    """计算分类任务的评估指标

    Args:
        y_true: 真实标签（0/1）
        y_pred: 预测标签（0/1）
        y_prob: 上涨概率（用于 AUC）

    Returns:
        指标字典
    """
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score,
        f1_score, roc_auc_score, confusion_matrix,
    )

    metrics: dict[str, float] = {}

    try:
        metrics["accuracy"] = float(accuracy_score(y_true, y_pred))
        metrics["precision"] = float(precision_score(y_true, y_pred, zero_division=0))
        metrics["recall"] = float(recall_score(y_true, y_pred, zero_division=0))
        metrics["f1"] = float(f1_score(y_true, y_pred, zero_division=0))

        if y_prob is not None and len(np.unique(y_true)) > 1:
            metrics["auc"] = float(roc_auc_score(y_true, y_prob))
        else:
            metrics["auc"] = 0.0

        cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
        metrics["true_positive"] = int(cm[1][1]) if cm.shape == (2, 2) else 0
        metrics["false_positive"] = int(cm[0][1]) if cm.shape == (2, 2) else 0
        metrics["true_negative"] = int(cm[0][0]) if cm.shape == (2, 2) else 0
        metrics["false_negative"] = int(cm[1][0]) if cm.shape == (2, 2) else 0

    except Exception as e:
        logger.warning("分类指标计算异常: %s", e)
        metrics.setdefault("accuracy", 0.0)

    return metrics


def compute_regression_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> dict[str, float]:
    """计算回归任务的评估指标"""
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

    metrics: dict[str, float] = {}
    try:
        metrics["rmse"] = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        metrics["mae"] = float(mean_absolute_error(y_true, y_pred))
        metrics["r2"] = float(r2_score(y_true, y_pred))
        # 方向准确率（回归任务也可用）
        direction_correct = ((y_true > 0) == (y_pred > 0)).mean()
        metrics["direction_accuracy"] = float(direction_correct)
    except Exception as e:
        logger.warning("回归指标计算异常: %s", e)

    return metrics


def compute_pnl_metrics(
    returns: pd.Series,
    risk_free_rate: float = 0.03,
    annual_trading_days: int = 242,
) -> dict[str, float]:
    """计算交易模拟指标（基于收益率序列）

    Args:
        returns:           每期收益率序列
        risk_free_rate:    年化无风险利率（默认3%）
        annual_trading_days: 年化交易日数（A股约242天）

    Returns:
        pnl, max_drawdown, sharpe, win_rate, profit_factor 等
    """
    metrics: dict[str, float] = {}

    if returns.empty:
        return {"total_pnl": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "win_rate": 0.0}

    returns = returns.fillna(0)

    # 累计收益
    cumulative = (1 + returns).cumprod()
    metrics["total_pnl"] = float(cumulative.iloc[-1] - 1)
    metrics["total_return_pct"] = float(metrics["total_pnl"] * 100)

    # 最大回撤
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    metrics["max_drawdown"] = float(drawdown.min())
    metrics["max_drawdown_pct"] = float(abs(metrics["max_drawdown"]) * 100)

    # 夏普比率
    daily_rf = risk_free_rate / annual_trading_days
    excess = returns - daily_rf
    std = excess.std()
    if std > 0:
        metrics["sharpe"] = float(excess.mean() / std * np.sqrt(annual_trading_days))
    else:
        metrics["sharpe"] = 0.0

    # 胜率
    wins = (returns > 0).sum()
    total = len(returns)
    metrics["win_rate"] = float(wins / total) if total > 0 else 0.0

    # 盈亏比
    avg_win = returns[returns > 0].mean() if wins > 0 else 0
    losses = (returns < 0).sum()
    avg_loss = abs(returns[returns < 0].mean()) if losses > 0 else 0
    metrics["profit_factor"] = float(avg_win / avg_loss) if avg_loss > 0 else 0.0

    # 交易天数
    metrics["trading_days"] = int(total)

    # 年化收益率
    if total > 0:
        metrics["annualized_return"] = float(
            (cumulative.iloc[-1] ** (annual_trading_days / total)) - 1
        )
    else:
        metrics["annualized_return"] = 0.0

    # Calmar 比率（年化收益 / 最大回撤）
    if abs(metrics["max_drawdown"]) > 0:
        metrics["calmar_ratio"] = float(
            metrics["annualized_return"] / abs(metrics["max_drawdown"])
        )
    else:
        metrics["calmar_ratio"] = 0.0

    # Sortino 比率（使用下行偏差）
    neg_returns = excess.where(excess < 0, 0)
    downside_std = neg_returns.std()
    if downside_std > 0:
        metrics["sortino_ratio"] = float(
            excess.mean() / downside_std * np.sqrt(annual_trading_days)
        )
    else:
        metrics["sortino_ratio"] = 0.0

    return metrics
