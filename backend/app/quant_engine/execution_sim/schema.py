"""
Execution simulation schemas - Task T2.

Defines execution-layer result data structures only.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ExecutionStatus(str, Enum):
    """Order execution status."""

    PENDING = "pending"
    RUNNING = "running"
    FILLED = "filled"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class ExecutionResult:
    """Execution result for one simulated order."""

    # tracking
    decision_id: Optional[int]
    symbol: str
    order_type: str
    order_date: datetime.date

    # target/executed
    target_qty: int
    executed_qty: int = 0
    target_price: Optional[float] = None
    executed_price: Optional[float] = None

    # status and reason
    status: ExecutionStatus = ExecutionStatus.PENDING
    failure_reason: Optional[str] = None

    # costs
    commission: float = 0.0
    stamp_tax: float = 0.0
    slippage: float = 0.0
    actual_cost: float = 0.0

    # A-share constraints flags
    is_t1_locked: bool = False
    is_limit_up_blocked: bool = False
    is_limit_down_blocked: bool = False

    # extension
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict for transport or storage."""
        return {
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "order_type": self.order_type,
            "order_date": self.order_date.isoformat(),
            "target_qty": self.target_qty,
            "executed_qty": self.executed_qty,
            "target_price": self.target_price,
            "executed_price": self.executed_price,
            "status": self.status.value,
            "failure_reason": self.failure_reason,
            "commission": self.commission,
            "stamp_tax": self.stamp_tax,
            "slippage": self.slippage,
            "actual_cost": self.actual_cost,
            "is_t1_locked": self.is_t1_locked,
            "is_limit_up_blocked": self.is_limit_up_blocked,
            "is_limit_down_blocked": self.is_limit_down_blocked,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionResult":
        """Deserialize from dict."""
        return cls(
            decision_id=data.get("decision_id"),
            symbol=data["symbol"],
            order_type=data["order_type"],
            order_date=datetime.date.fromisoformat(data["order_date"]),
            target_qty=data["target_qty"],
            executed_qty=data.get("executed_qty", 0),
            target_price=data.get("target_price"),
            executed_price=data.get("executed_price"),
            status=ExecutionStatus(data.get("status", ExecutionStatus.PENDING.value)),
            failure_reason=data.get("failure_reason"),
            commission=data.get("commission", 0.0),
            stamp_tax=data.get("stamp_tax", 0.0),
            slippage=data.get("slippage", 0.0),
            actual_cost=data.get("actual_cost", 0.0),
            is_t1_locked=data.get("is_t1_locked", False),
            is_limit_up_blocked=data.get("is_limit_up_blocked", False),
            is_limit_down_blocked=data.get("is_limit_down_blocked", False),
            metadata=data.get("metadata", {}),
        )
