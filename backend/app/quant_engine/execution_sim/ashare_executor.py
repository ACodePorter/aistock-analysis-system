"""A-share execution simulator for Task T9.

This module is intentionally standalone:
- no database operations
- no external dependencies
"""

from __future__ import annotations

import datetime
from typing import Optional

from .schema import ExecutionResult, ExecutionStatus


class AShareExecutor:
    """Simple A-share order execution simulator.

    Supported constraints:
    - T+1 sell restriction via in-memory bought_today tracking
    - limit up/down checks
    - slippage and fee calculation
    """

    def __init__(
        self,
        *,
        commission_rate: float = 0.0003,
        stamp_tax_rate: float = 0.001,
        min_commission: float = 5.0,
        slippage_rate: float = 0.001,
    ) -> None:
        self.commission_rate = float(commission_rate)
        self.stamp_tax_rate = float(stamp_tax_rate)
        self.min_commission = float(min_commission)
        self.slippage_rate = float(slippage_rate)

        # Tracks whether a symbol was bought on a specific day (T+1 lock).
        self.bought_today: dict[str, datetime.date] = {}

    @staticmethod
    def _ensure_date(value: datetime.date | str) -> datetime.date:
        if isinstance(value, datetime.date):
            return value
        return datetime.date.fromisoformat(value)

    def check_limit_up(
        self,
        *,
        price: float,
        prev_close: float,
        is_st: bool = False,
        limit_pct: Optional[float] = None,
    ) -> bool:
        """Return True if price is at or above daily limit-up price."""
        pct = float(limit_pct) if limit_pct is not None else (0.05 if is_st else 0.10)
        limit_up = float(prev_close) * (1.0 + pct)
        return float(price) >= limit_up

    def check_limit_down(
        self,
        *,
        price: float,
        prev_close: float,
        is_st: bool = False,
        limit_pct: Optional[float] = None,
    ) -> bool:
        """Return True if price is at or below daily limit-down price."""
        pct = float(limit_pct) if limit_pct is not None else (0.05 if is_st else 0.10)
        limit_down = float(prev_close) * (1.0 - pct)
        return float(price) <= limit_down

    def _apply_slippage(self, *, side: str, price: float) -> float:
        if side == "buy":
            return float(price) * (1.0 + self.slippage_rate)
        return float(price) * (1.0 - self.slippage_rate)

    def _calculate_fee(self, *, side: str, amount: float) -> tuple[float, float]:
        commission = max(self.min_commission, float(amount) * self.commission_rate)
        stamp_tax = float(amount) * self.stamp_tax_rate if side == "sell" else 0.0
        return commission, stamp_tax

    def execute_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        order_price: float,
        prev_close: float,
        order_date: datetime.date | str,
        available_sellable: Optional[int] = None,
        is_st: bool = False,
        limit_pct: Optional[float] = None,
    ) -> ExecutionResult:
        """Execute one order under A-share constraints.

        Parameters are intentionally simple to keep this module standalone.
        """
        trade_date = self._ensure_date(order_date)
        side_norm = side.lower().strip()

        result = ExecutionResult(
            decision_id=None,
            symbol=symbol,
            order_type=side_norm,
            order_date=trade_date,
            target_qty=int(quantity),
            target_price=float(order_price),
            status=ExecutionStatus.PENDING,
        )

        if side_norm not in ("buy", "sell"):
            result.status = ExecutionStatus.REJECTED
            result.failure_reason = f"invalid side: {side}"
            return result
        if quantity <= 0:
            result.status = ExecutionStatus.REJECTED
            result.failure_reason = "quantity must be positive"
            return result
        if order_price <= 0 or prev_close <= 0:
            result.status = ExecutionStatus.REJECTED
            result.failure_reason = "order_price and prev_close must be positive"
            return result

        # T+1 restriction: shares bought today cannot be sold today.
        if side_norm == "sell":
            if self.bought_today.get(symbol) == trade_date:
                result.status = ExecutionStatus.REJECTED
                result.is_t1_locked = True
                result.failure_reason = "T+1 restriction: bought today cannot be sold today"
                return result

            if available_sellable is not None and int(quantity) > int(available_sellable):
                result.status = ExecutionStatus.REJECTED
                result.failure_reason = "insufficient sellable quantity"
                return result

        # Limit checks.
        if side_norm == "buy" and self.check_limit_up(
            price=order_price,
            prev_close=prev_close,
            is_st=is_st,
            limit_pct=limit_pct,
        ):
            result.status = ExecutionStatus.REJECTED
            result.is_limit_up_blocked = True
            result.failure_reason = "blocked by limit-up"
            return result

        if side_norm == "sell" and self.check_limit_down(
            price=order_price,
            prev_close=prev_close,
            is_st=is_st,
            limit_pct=limit_pct,
        ):
            result.status = ExecutionStatus.REJECTED
            result.is_limit_down_blocked = True
            result.failure_reason = "blocked by limit-down"
            return result

        # Slippage and final execution price.
        exec_price = self._apply_slippage(side=side_norm, price=order_price)
        slippage_amount = abs(exec_price - float(order_price)) * int(quantity)

        amount = exec_price * int(quantity)
        commission, stamp_tax = self._calculate_fee(side=side_norm, amount=amount)

        result.executed_qty = int(quantity)
        result.executed_price = exec_price
        result.status = ExecutionStatus.FILLED
        result.slippage = slippage_amount
        result.commission = commission
        result.stamp_tax = stamp_tax

        # Buy uses cash outflow; sell uses net inflow.
        if side_norm == "buy":
            result.actual_cost = amount + commission + stamp_tax
            self.bought_today[symbol] = trade_date
        else:
            result.actual_cost = amount - commission - stamp_tax

        result.metadata.update(
            {
                "side": side_norm,
                "amount": amount,
                "slippage_rate": self.slippage_rate,
                "commission_rate": self.commission_rate,
                "stamp_tax_rate": self.stamp_tax_rate,
            }
        )
        return result
