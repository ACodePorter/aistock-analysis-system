"""Prediction replay backtest and promotion gate helpers."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from ...core.models import AgentReviewRun, PredictionEvaluation, PriceDaily


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _gate(name: str, status: str, message: str, value=None, threshold=None) -> dict:
    return {"name": name, "status": status, "message": message, "value": value, "threshold": threshold}


def build_prediction_replay_backtest(
    session: Session,
    symbol: str,
    *,
    lookback_days: int = 120,
    buy_threshold_pct: float = 0.3,
    position_pct: float = 0.2,
    min_samples: int = 8,
) -> dict:
    """Replay evaluated predictions as a conservative long-only signal backtest."""
    sym = symbol.upper()
    cutoff = date.today() - timedelta(days=lookback_days)
    evals = list(session.execute(
        select(PredictionEvaluation)
        .where(
            PredictionEvaluation.symbol == sym,
            PredictionEvaluation.target_date >= cutoff,
            PredictionEvaluation.actual_price.is_not(None),
            PredictionEvaluation.predicted_price.is_not(None),
        )
        .order_by(PredictionEvaluation.target_date.asc(), PredictionEvaluation.prediction_date.asc())
    ).scalars().all())
    if not evals:
        return {
            "symbol": sym,
            "strategy": "prediction_replay_long_only",
            "lookback_days": lookback_days,
            "sample_count": 0,
            "trades": [],
            "metrics": {
                "total_return_pct": None,
                "win_rate": None,
                "avg_trade_return_pct": None,
                "max_drawdown_pct": None,
                "trade_count": 0,
            },
            "gate_result": _promotion_gate([], None),
            "disclaimer": "策略回放仅用于模型复盘与门禁，不构成投资建议。",
        }

    min_price_date = min(item.prediction_date for item in evals) - timedelta(days=10)
    max_price_date = max(item.target_date for item in evals)
    prices = list(session.execute(
        select(PriceDaily)
        .where(PriceDaily.symbol == sym, PriceDaily.trade_date >= min_price_date, PriceDaily.trade_date <= max_price_date)
        .order_by(PriceDaily.trade_date.asc())
    ).scalars().all())
    price_map = {row.trade_date: float(row.close) for row in prices if row.close is not None}
    sorted_dates = sorted(price_map)

    def price_on_or_before(day: date) -> Optional[float]:
        if day in price_map:
            return price_map[day]
        candidates = [trade_date for trade_date in sorted_dates if trade_date <= day]
        return price_map[candidates[-1]] if candidates else None

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    trades = []
    entered_returns = []
    for item in evals:
        base_price = price_on_or_before(item.prediction_date)
        if not base_price or base_price <= 0 or item.actual_price is None or item.predicted_price is None:
            continue
        predicted_return = (float(item.predicted_price) - base_price) / base_price * 100.0
        actual_return = (float(item.actual_price) - base_price) / base_price * 100.0
        action = "buy" if predicted_return >= buy_threshold_pct else "observe"
        realized = actual_return * position_pct if action == "buy" else 0.0
        equity *= 1 + realized / 100.0
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        if action == "buy":
            entered_returns.append(actual_return)
        trades.append({
            "prediction_date": item.prediction_date.isoformat(),
            "target_date": item.target_date.isoformat(),
            "action": action,
            "base_price": _round(base_price),
            "predicted_price": _round(float(item.predicted_price)),
            "actual_price": _round(float(item.actual_price)),
            "predicted_return_pct": _round(predicted_return),
            "actual_return_pct": _round(actual_return),
            "position_pct": position_pct if action == "buy" else 0.0,
            "equity": _round((equity - 1) * 100.0),
        })

    trade_count = len(entered_returns)
    wins = sum(1 for value in entered_returns if value > 0)
    total_return = (equity - 1) * 100.0
    win_rate = wins / trade_count * 100.0 if trade_count else None
    avg_return = sum(entered_returns) / trade_count if trade_count else None
    latest_review = None
    if inspect(session.get_bind()).has_table("agent_review_runs"):
        latest_review = session.execute(
            select(AgentReviewRun)
            .where(AgentReviewRun.symbol == sym)
            .order_by(AgentReviewRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    metrics = {
        "total_return_pct": _round(total_return),
        "win_rate": _round(win_rate, 1),
        "avg_trade_return_pct": _round(avg_return),
        "max_drawdown_pct": _round(max_drawdown),
        "trade_count": trade_count,
        "evaluated_count": len(evals),
    }
    return {
        "symbol": sym,
        "strategy": "prediction_replay_long_only",
        "lookback_days": lookback_days,
        "parameters": {
            "buy_threshold_pct": buy_threshold_pct,
            "position_pct": position_pct,
            "min_samples": min_samples,
        },
        "sample_count": len(evals),
        "trades": trades[-40:],
        "metrics": metrics,
        "gate_result": _promotion_gate(evals, latest_review, metrics=metrics, min_samples=min_samples),
        "latest_agent_gate": latest_review.gate_result if latest_review else None,
        "disclaimer": "策略回放仅用于模型复盘与门禁，不构成投资建议，也不会自动执行交易。",
    }


def _promotion_gate(evals: list, latest_review: Optional[AgentReviewRun], *, metrics: Optional[dict] = None, min_samples: int = 8) -> dict:
    metrics = metrics or {}
    checks = []
    sample_count = len(evals)
    checks.append(_gate(
        "data_gate",
        "passed" if sample_count >= min_samples else "warning",
        f"已评估样本 {sample_count}/{min_samples}",
        sample_count,
        min_samples,
    ))
    win_rate = metrics.get("win_rate")
    total_return = metrics.get("total_return_pct")
    performance_ok = win_rate is not None and win_rate >= 50 and total_return is not None and total_return > 0
    checks.append(_gate(
        "performance_gate",
        "passed" if performance_ok else "warning",
        "胜率与组合回放收益需同时为正向。",
        {"win_rate": win_rate, "total_return_pct": total_return},
        {"win_rate": 50, "total_return_pct": 0},
    ))
    max_drawdown = metrics.get("max_drawdown_pct")
    risk_ok = max_drawdown is not None and max_drawdown <= 12
    checks.append(_gate(
        "risk_gate",
        "passed" if risk_ok else "warning",
        "最大回撤需保持在受控范围。",
        max_drawdown,
        12,
    ))
    gate_status = (latest_review.gate_result or {}).get("status") if latest_review else None
    verification_ok = gate_status in {"candidate_allowed", "observation_only"}
    checks.append(_gate(
        "verification_gate",
        "passed" if verification_ok else "warning",
        "Agent 建议需先通过自动核实，至少进入受控观察。",
        gate_status or "missing",
        "candidate_allowed/observation_only",
    ))
    failed = [item for item in checks if item["status"] == "failed"]
    warnings = [item for item in checks if item["status"] == "warning"]
    if failed:
        status = "blocked"
        next_state = "blocked"
    elif warnings:
        status = "observation_only"
        next_state = "candidate_monitor"
    else:
        status = "candidate_allowed"
        next_state = "candidate"
    return {
        "status": status,
        "next_state": next_state,
        "checks": checks,
        "failed_checks": [item["name"] for item in failed],
        "warning_checks": [item["name"] for item in warnings],
        "message": "通过所有门禁，可进入候选观察。" if status == "candidate_allowed" else "门禁未完全通过，仅允许受控观察或继续等待样本。",
    }