from __future__ import annotations

from math import floor
from typing import Dict, Optional, Union

Number = Union[int, float]


def _round_down_to_lot(shares: Number, lot_size: int = 100) -> int:
    """Round down shares to nearest tradable lot size (default: 100 shares)."""
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    if shares <= 0:
        return 0
    return int(floor(float(shares) / lot_size) * lot_size)


def _resolve_risk_budget(account_equity: Number, risk_per_trade: Number) -> float:
    """Resolve risk budget from percent-or-absolute input.

    - If 0 < risk_per_trade <= 1: treat as percentage of account equity.
    - If risk_per_trade > 1: treat as absolute currency amount.
    """
    eq = float(account_equity)
    rpt = float(risk_per_trade)
    if eq <= 0:
        raise ValueError("account_equity must be positive")
    if rpt <= 0:
        raise ValueError("risk_per_trade must be positive")
    return eq * rpt if rpt <= 1 else rpt


def calculate_atr_position_size(
    *,
    account_equity: Number,
    risk_per_trade: Number,
    entry_price: Number,
    stop_loss_price: Number,
    atr_value: Optional[Number],
    atr_multiplier: Number = 1.0,
    available_cash: Optional[Number] = None,
    lot_size: int = 100,
) -> Dict[str, Union[int, float, str]]:
    """ATR-based position sizing.

    Required risk inputs:
    - account_equity
    - risk_per_trade
    - stop_loss distance (|entry_price - stop_loss_price|)
    """
    entry = float(entry_price)
    stop = float(stop_loss_price)
    atr_mult = float(atr_multiplier)

    if entry <= 0:
        raise ValueError("entry_price must be positive")
    if stop <= 0:
        raise ValueError("stop_loss_price must be positive")
    if atr_mult <= 0:
        raise ValueError("atr_multiplier must be positive")

    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return {
            "position_size": 0,
            "estimated_cost": 0.0,
            "max_loss_amount": 0.0,
            "stop_loss_distance": 0.0,
            "sizing_method": "atr_based",
            "warning": "invalid_stop_loss_distance",
        }

    risk_budget = _resolve_risk_budget(account_equity, risk_per_trade)

    # Conservative per-share risk: use the larger one.
    if atr_value is not None and float(atr_value) > 0:
        per_share_risk = max(stop_distance, float(atr_value) * atr_mult)
    else:
        per_share_risk = stop_distance

    raw_shares = risk_budget / per_share_risk

    if available_cash is not None and float(available_cash) > 0:
        raw_shares = min(raw_shares, float(available_cash) / entry)

    position_size = _round_down_to_lot(raw_shares, lot_size=lot_size)
    estimated_cost = position_size * entry
    max_loss_amount = position_size * stop_distance

    warning = ""
    if position_size == 0:
        warning = "insufficient_capital_or_risk_budget"

    return {
        "position_size": position_size,
        "estimated_cost": round(estimated_cost, 4),
        "max_loss_amount": round(max_loss_amount, 4),
        "stop_loss_distance": round(stop_distance, 8),
        "sizing_method": "atr_based",
        "warning": warning,
    }


def calculate_fixed_position_size(
    *,
    account_equity: Number,
    risk_per_trade: Number,
    entry_price: Number,
    stop_loss_price: Number,
    fixed_ratio: Number = 0.10,
    available_cash: Optional[Number] = None,
    lot_size: int = 100,
) -> Dict[str, Union[int, float, str]]:
    """Fixed-ratio fallback position sizing with risk cap.

    This fallback still enforces risk budget from stop-loss distance.
    """
    entry = float(entry_price)
    stop = float(stop_loss_price)
    ratio = float(fixed_ratio)

    if entry <= 0:
        raise ValueError("entry_price must be positive")
    if stop <= 0:
        raise ValueError("stop_loss_price must be positive")
    if ratio <= 0:
        raise ValueError("fixed_ratio must be positive")

    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return {
            "position_size": 0,
            "estimated_cost": 0.0,
            "max_loss_amount": 0.0,
            "stop_loss_distance": 0.0,
            "sizing_method": "fixed_ratio_fallback",
            "warning": "invalid_stop_loss_distance",
        }

    risk_budget = _resolve_risk_budget(account_equity, risk_per_trade)

    capital_budget = float(account_equity) * ratio
    if available_cash is not None and float(available_cash) > 0:
        capital_budget = min(capital_budget, float(available_cash))

    raw_shares_by_capital = capital_budget / entry
    raw_shares_by_risk = risk_budget / stop_distance
    raw_shares = min(raw_shares_by_capital, raw_shares_by_risk)

    position_size = _round_down_to_lot(raw_shares, lot_size=lot_size)
    estimated_cost = position_size * entry
    max_loss_amount = position_size * stop_distance

    warning = ""
    if position_size == 0:
        warning = "insufficient_capital_or_risk_budget"

    return {
        "position_size": position_size,
        "estimated_cost": round(estimated_cost, 4),
        "max_loss_amount": round(max_loss_amount, 4),
        "stop_loss_distance": round(stop_distance, 8),
        "sizing_method": "fixed_ratio_fallback",
        "warning": warning,
    }
