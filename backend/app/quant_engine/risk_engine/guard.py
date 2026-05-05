from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import math

__all__ = ["TradeRiskGuard", "PortfolioRiskGuard", "RiskCheckResult", "RiskViolation"]


@dataclass
class RiskViolation:
    code: str
    message: str
    severity: str  # one of: 'reject', 'adjust', 'flag'


@dataclass
class RiskCheckResult:
    passed: bool
    violations: List[RiskViolation] = field(default_factory=list)
    suggested_action: str = "approve"  # approve | reject | adjust | flag
    details: Dict[str, Any] = field(default_factory=dict)


class TradeRiskGuard:
    """Simple rule-based trade risk guard.

    This class provides synchronous, deterministic checks for trade proposals.
    It intentionally does NOT perform any DB writes or network calls.

    Methods return `RiskCheckResult` objects describing pass/fail and suggestions.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        # thresholds and defaults (tunable via config)
        self.max_loss_absolute = cfg.get("RISK_MAX_LOSS_ABSOLUTE")  # cash units
        self.max_loss_pct = cfg.get("RISK_MAX_LOSS_PCT", 0.02)  # fraction of account
        self.min_rr = cfg.get("RISK_MIN_RR", 1.5)
        self.stoploss_min_distance_pct = cfg.get("RISK_STOPLOSS_MIN_DISTANCE_PCT", 0.005)
        self.enable_symbol_check = cfg.get("RISK_INVALID_SYMBOL_CHECK", True)

    def _make_result(self) -> RiskCheckResult:
        return RiskCheckResult(passed=True, violations=[], suggested_action="approve")

    def _add_violation(self, res: RiskCheckResult, code: str, msg: str, severity: str = "reject") -> None:
        res.violations.append(RiskViolation(code=code, message=msg, severity=severity))
        if severity == "reject":
            res.suggested_action = "reject"
            res.passed = False
        elif severity == "adjust" and res.suggested_action != "reject":
            res.suggested_action = "adjust"
            res.passed = False
        elif severity == "flag" and res.suggested_action not in ("reject", "adjust"):
            res.suggested_action = "flag"

    def check_stop_loss(
        self,
        entry_price: float,
        stop_loss_price: float,
        side: str,
        min_distance_pct: Optional[float] = None,
    ) -> RiskCheckResult:
        """Validate stop loss placement.

        - For `long`, stop_loss_price must be < entry_price.
        - For `short`, stop_loss_price must be > entry_price.
        - The distance between entry and stop must be >= min_distance_pct (defaults to config).
        """
        res = self._make_result()
        if entry_price is None or stop_loss_price is None:
            self._add_violation(res, "missing_price", "entry or stop price missing", "reject")
            return res

        if side not in ("long", "short"):
            self._add_violation(res, "invalid_side", f"unknown side: {side}", "reject")
            return res

        if side == "long":
            if not (stop_loss_price < entry_price):
                self._add_violation(res, "stop_direction", "stop loss must be below entry for long", "reject")
        else:
            if not (stop_loss_price > entry_price):
                self._add_violation(res, "stop_direction", "stop loss must be above entry for short", "reject")

        min_dist = self.stoploss_min_distance_pct if min_distance_pct is None else min_distance_pct
        try:
            dist = abs(entry_price - stop_loss_price) / float(entry_price)
        except Exception:
            dist = 0.0

        if dist < float(min_dist):
            self._add_violation(
                res,
                "stop_too_close",
                f"stop loss distance {dist:.4f} below minimum {min_dist}",
                "adjust",
            )

        res.details.update({"stop_distance_pct": dist})
        return res

    def check_risk_reward(
        self,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: Optional[float],
        side: str,
        min_rr: Optional[float] = None,
    ) -> RiskCheckResult:
        """Calculate and validate risk/reward ratio.

        If `take_profit_price` is None, we flag but do not reject.
        """
        res = self._make_result()
        if take_profit_price is None:
            self._add_violation(res, "no_tp", "no take-profit provided", "flag")
            return res

        # direction checks for TP
        if side == "long" and not (take_profit_price > entry_price):
            self._add_violation(res, "tp_direction", "take-profit must be above entry for long", "reject")
        if side == "short" and not (take_profit_price < entry_price):
            self._add_violation(res, "tp_direction", "take-profit must be below entry for short", "reject")

        risk = abs(entry_price - stop_loss_price)
        reward = abs(take_profit_price - entry_price)
        if risk <= 0:
            self._add_violation(res, "zero_risk", "zero or negative risk (stop==entry)", "reject")
            return res

        rr = reward / risk if risk else math.inf
        min_rr_val = self.min_rr if min_rr is None else min_rr
        res.details.update({"risk": risk, "reward": reward, "rr": rr})
        if rr < float(min_rr_val):
            self._add_violation(
                res,
                "low_rr",
                f"risk/reward {rr:.2f} below minimum {min_rr_val}",
                "reject",
            )

        return res

    def check_max_loss(
        self,
        position_size: float,
        entry_price: float,
        stop_loss_price: float,
        max_loss_absolute: Optional[float] = None,
        max_loss_pct: Optional[float] = None,
        account_balance: Optional[float] = None,
    ) -> RiskCheckResult:
        """Estimate worst-case loss for the trade and compare to thresholds.

        - `position_size` is in units (e.g., number of shares). This is intentionally simple.
        - If account_balance is provided and max_loss_pct set, compare pct-based threshold.
        """
        res = self._make_result()
        if position_size is None or entry_price is None or stop_loss_price is None:
            self._add_violation(res, "missing_position", "position or price missing", "reject")
            return res

        loss_per_unit = abs(entry_price - stop_loss_price)
        potential_loss = loss_per_unit * float(position_size)
        res.details.update({"loss_per_unit": loss_per_unit, "potential_loss": potential_loss})

        # absolute cap
        cap = max_loss_absolute if max_loss_absolute is not None else self.max_loss_absolute
        if cap is not None and potential_loss > float(cap):
            self._add_violation(
                res,
                "max_loss_abs",
                f"potential loss {potential_loss} exceeds absolute cap {cap}",
                "reject",
            )

        # pct cap
        pct = max_loss_pct if max_loss_pct is not None else self.max_loss_pct
        if pct is not None and account_balance is not None:
            allowed = float(pct) * float(account_balance)
            res.details["allowed_loss_by_pct"] = allowed
            if potential_loss > allowed:
                self._add_violation(
                    res,
                    "max_loss_pct",
                    f"potential loss {potential_loss} exceeds {pct*100:.2f}% of account ({allowed})",
                    "reject",
                )
        elif pct is not None and account_balance is None:
            # cannot fully evaluate pct without account balance — flag
            self._add_violation(
                res,
                "missing_account",
                "account balance required for pct-based max loss check",
                "flag",
            )

        return res

    def check_symbol_validity(self, symbol: str, symbol_meta: Optional[Dict[str, Any]] = None) -> RiskCheckResult:
        """Basic symbol checks. `symbol_meta` may include boolean flags:
        - 'is_st', 'is_suspended', 'is_delisted', 'tradeable'

        If `symbol_meta` is not provided, a simple heuristic is used (e.g., prefix 'ST').
        """
        res = self._make_result()
        if not symbol:
            self._add_violation(res, "missing_symbol", "symbol not provided", "reject")
            return res

        meta = symbol_meta or {}
        is_st = bool(meta.get("is_st", False) or str(symbol).upper().startswith("ST"))
        is_suspended = bool(meta.get("is_suspended", False))
        is_delisted = bool(meta.get("is_delisted", False))
        tradeable = meta.get("tradeable")

        if is_delisted:
            self._add_violation(res, "delisted", "symbol is delisted", "reject")
        if is_st:
            self._add_violation(res, "st_symbol", "symbol is ST (special treatment)", "reject")
        if is_suspended:
            self._add_violation(res, "suspended", "symbol is suspended", "reject")
        if tradeable is False:
            self._add_violation(res, "not_tradeable", "symbol marked not tradeable", "reject")

        return res

    def validate_trade(
        self,
        *,
        symbol: str,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: Optional[float],
        side: str,
        position_size: float,
        account_balance: Optional[float] = None,
        symbol_meta: Optional[Dict[str, Any]] = None,
    ) -> RiskCheckResult:
        """Run all checks and return aggregated `RiskCheckResult`.

        The returned `RiskCheckResult` contains all violations and a suggested action.
        """
        agg = self._make_result()

        # symbol check
        if self.enable_symbol_check:
            sym_res = self.check_symbol_validity(symbol, symbol_meta)
            for v in sym_res.violations:
                self._add_violation(agg, v.code, v.message, v.severity)

        # stop loss
        sl_res = self.check_stop_loss(entry_price, stop_loss_price, side)
        for v in sl_res.violations:
            self._add_violation(agg, v.code, v.message, v.severity)

        # risk/reward
        rr_res = self.check_risk_reward(entry_price, stop_loss_price, take_profit_price, side)
        for v in rr_res.violations:
            self._add_violation(agg, v.code, v.message, v.severity)

        # max loss
        ml_res = self.check_max_loss(position_size, entry_price, stop_loss_price, None, None, account_balance)
        for v in ml_res.violations:
            self._add_violation(agg, v.code, v.message, v.severity)

        # details aggregation (shallow merge)
        agg.details.update({"symbol": symbol, "side": side})
        agg.details.setdefault("stop_check", {}).update(sl_res.details)
        agg.details.setdefault("rr_check", {}).update(rr_res.details)
        agg.details.setdefault("max_loss_check", {}).update(ml_res.details)

        return agg


class PortfolioRiskGuard:
    """Simple rule-based portfolio risk guard.

    This class evaluates portfolio-level limits without database operations
    or external dependencies.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        self.max_daily_loss_abs = cfg.get("PORTFOLIO_MAX_DAILY_LOSS_ABS")
        self.max_daily_loss_pct = cfg.get("PORTFOLIO_MAX_DAILY_LOSS_PCT")
        self.max_positions = cfg.get("PORTFOLIO_MAX_POSITIONS", 10)
        self.max_sector_concentration_pct = cfg.get("PORTFOLIO_MAX_SECTOR_CONCENTRATION_PCT", 0.35)
        self.allowed_regimes = set(cfg.get("PORTFOLIO_ALLOWED_REGIMES", []))

    def _make_result(self) -> RiskCheckResult:
        return RiskCheckResult(passed=True, violations=[], suggested_action="approve")

    def _add_violation(self, res: RiskCheckResult, code: str, msg: str, severity: str = "reject") -> None:
        res.violations.append(RiskViolation(code=code, message=msg, severity=severity))
        if severity == "reject":
            res.suggested_action = "reject"
            res.passed = False
        elif severity == "adjust" and res.suggested_action != "reject":
            res.suggested_action = "adjust"
            res.passed = False
        elif severity == "flag" and res.suggested_action not in ("reject", "adjust"):
            res.suggested_action = "flag"

    def check_max_daily_loss(
        self,
        daily_pnl: float,
        portfolio_equity: Optional[float] = None,
        max_daily_loss_abs: Optional[float] = None,
        max_daily_loss_pct: Optional[float] = None,
    ) -> RiskCheckResult:
        """Check daily loss limits.

        `daily_pnl` should be negative when losing money.
        """
        res = self._make_result()
        loss = max(0.0, -float(daily_pnl))
        res.details["daily_loss"] = loss

        abs_cap = self.max_daily_loss_abs if max_daily_loss_abs is None else max_daily_loss_abs
        if abs_cap is not None and loss > float(abs_cap):
            self._add_violation(
                res,
                "max_daily_loss_abs",
                f"daily loss {loss} exceeds absolute limit {abs_cap}",
                "reject",
            )

        pct_cap = self.max_daily_loss_pct if max_daily_loss_pct is None else max_daily_loss_pct
        if pct_cap is not None:
            if portfolio_equity is None or float(portfolio_equity) <= 0:
                self._add_violation(
                    res,
                    "missing_equity",
                    "portfolio equity required for percentage daily loss check",
                    "flag",
                )
            else:
                allowed = float(pct_cap) * float(portfolio_equity)
                res.details["daily_loss_allowed_by_pct"] = allowed
                if loss > allowed:
                    self._add_violation(
                        res,
                        "max_daily_loss_pct",
                        f"daily loss {loss} exceeds {pct_cap*100:.2f}% limit ({allowed})",
                        "reject",
                    )

        return res

    def check_max_positions(
        self,
        current_positions: int,
        incoming_positions: int = 1,
        max_positions: Optional[int] = None,
    ) -> RiskCheckResult:
        """Check portfolio max positions limit."""
        res = self._make_result()
        cap = self.max_positions if max_positions is None else max_positions
        projected = int(current_positions) + int(incoming_positions)
        res.details.update({"projected_positions": projected, "max_positions": cap})

        if cap is not None and projected > int(cap):
            self._add_violation(
                res,
                "max_positions",
                f"projected positions {projected} exceed limit {cap}",
                "reject",
            )

        return res

    def check_sector_concentration(
        self,
        sector_weights: Dict[str, float],
        candidate_sector: Optional[str] = None,
        candidate_weight: float = 0.0,
        max_sector_concentration_pct: Optional[float] = None,
    ) -> RiskCheckResult:
        """Check sector concentration limit.

        `sector_weights` are current normalized weights (0-1).
        If candidate sector is provided, candidate_weight is added to that sector.
        """
        res = self._make_result()
        cap = (
            self.max_sector_concentration_pct
            if max_sector_concentration_pct is None
            else max_sector_concentration_pct
        )
        projected = dict(sector_weights or {})
        if candidate_sector:
            projected[candidate_sector] = float(projected.get(candidate_sector, 0.0)) + float(candidate_weight)

        if not projected:
            res.details["projected_sector_max"] = 0.0
            return res

        max_sector = max(projected, key=lambda k: projected[k])
        max_weight = float(projected[max_sector])
        res.details.update({"projected_sector_max": max_weight, "projected_sector_name": max_sector, "cap": cap})

        if cap is not None and max_weight > float(cap):
            self._add_violation(
                res,
                "sector_concentration",
                f"sector {max_sector} concentration {max_weight:.4f} exceeds limit {cap}",
                "reject",
            )
        elif cap is not None and max_weight >= float(cap) * 0.9:
            self._add_violation(
                res,
                "sector_near_limit",
                f"sector {max_sector} concentration {max_weight:.4f} is near limit {cap}",
                "adjust",
            )

        return res

    def check_market_regime_restriction(
        self,
        current_regime: Optional[str],
        allowed_regimes: Optional[List[str]] = None,
    ) -> RiskCheckResult:
        """Check whether current market regime is allowed for opening risk."""
        res = self._make_result()
        allowed = set(allowed_regimes or self.allowed_regimes)
        res.details.update({"current_regime": current_regime, "allowed_regimes": sorted(list(allowed))})

        if not allowed:
            return res
        if current_regime is None:
            self._add_violation(res, "missing_regime", "market regime missing", "flag")
            return res
        if current_regime not in allowed:
            self._add_violation(
                res,
                "regime_restricted",
                f"market regime {current_regime} is not allowed",
                "reject",
            )

        return res

    def validate_portfolio(
        self,
        *,
        daily_pnl: float,
        current_positions: int,
        sector_weights: Dict[str, float],
        current_regime: Optional[str],
        portfolio_equity: Optional[float] = None,
        incoming_positions: int = 1,
        candidate_sector: Optional[str] = None,
        candidate_weight: float = 0.0,
    ) -> RiskCheckResult:
        """Run all portfolio-level checks and aggregate results."""
        agg = self._make_result()

        daily_res = self.check_max_daily_loss(daily_pnl=daily_pnl, portfolio_equity=portfolio_equity)
        pos_res = self.check_max_positions(
            current_positions=current_positions,
            incoming_positions=incoming_positions,
        )
        sector_res = self.check_sector_concentration(
            sector_weights=sector_weights,
            candidate_sector=candidate_sector,
            candidate_weight=candidate_weight,
        )
        regime_res = self.check_market_regime_restriction(current_regime=current_regime)

        for check_res in (daily_res, pos_res, sector_res, regime_res):
            for v in check_res.violations:
                self._add_violation(agg, v.code, v.message, v.severity)

        agg.details.setdefault("daily_loss_check", {}).update(daily_res.details)
        agg.details.setdefault("positions_check", {}).update(pos_res.details)
        agg.details.setdefault("sector_check", {}).update(sector_res.details)
        agg.details.setdefault("regime_check", {}).update(regime_res.details)
        return agg
