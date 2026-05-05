from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.models import PriceDaily, StockProfile, UserPortfolio, UserPosition, UserTradeLedger
from ..data.data_source import normalize_symbol


DEFAULT_PORTFOLIO_ID = "default"
SIDE_ERROR = "side must be buy or sell"


def _to_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class RecomputedPosition:
    symbol: str
    quantity: int
    avg_cost: Optional[float]
    total_cost: Optional[float]
    realized_pnl: float
    first_entry_date: Optional[date]
    last_trade_date: Optional[date]
    source: str


def ensure_default_portfolio(session: Session, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> UserPortfolio:
    portfolio = session.execute(
        select(UserPortfolio).where(UserPortfolio.portfolio_id == portfolio_id)
    ).scalar_one_or_none()
    if portfolio:
        return portfolio
    portfolio = UserPortfolio(
        portfolio_id=portfolio_id,
        name="我的持仓" if portfolio_id == DEFAULT_PORTFOLIO_ID else portfolio_id,
        is_default=(portfolio_id == DEFAULT_PORTFOLIO_ID),
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def _ordered_trades(session: Session, portfolio_id: str, symbol: str) -> list[UserTradeLedger]:
    return list(session.execute(
        select(UserTradeLedger)
        .where(UserTradeLedger.portfolio_id == portfolio_id, UserTradeLedger.symbol == symbol)
        .order_by(UserTradeLedger.trade_date.asc(), UserTradeLedger.id.asc())
    ).scalars().all())


def _compute_position_from_trades(trades: list[UserTradeLedger], *, allow_negative: bool = False) -> RecomputedPosition:
    if not trades:
        raise ValueError("no trades to recompute")

    symbol = trades[0].symbol
    quantity = 0
    total_cost = 0.0
    realized_pnl = 0.0
    first_entry_date: Optional[date] = None
    last_trade_date: Optional[date] = None
    source = "manual"

    for trade in trades:
        side = (trade.side or "").lower()
        trade_quantity = int(trade.quantity or 0)
        price = _to_float(trade.price)
        fees = _to_float(trade.fees)
        tax = _to_float(trade.tax)
        if trade_quantity <= 0 or price <= 0:
            raise ValueError(f"invalid trade for {trade.symbol}: quantity and price must be positive")
        last_trade_date = trade.trade_date
        source = trade.source or source

        if side == "buy":
            if quantity == 0:
                first_entry_date = trade.trade_date
            quantity += trade_quantity
            total_cost += price * trade_quantity + fees + tax
        elif side == "sell":
            if trade_quantity > quantity and not allow_negative:
                raise ValueError(f"sell quantity exceeds holding for {symbol}: sell={trade_quantity}, holding={quantity}")
            avg_cost = total_cost / quantity if quantity > 0 else 0.0
            proceeds = price * trade_quantity - fees - tax
            realized_pnl += proceeds - avg_cost * trade_quantity
            quantity -= trade_quantity
            total_cost -= avg_cost * trade_quantity
            if quantity <= 0:
                quantity = 0
                total_cost = 0.0
                first_entry_date = None
        else:
            raise ValueError(SIDE_ERROR)

    avg_cost = total_cost / quantity if quantity > 0 else None
    return RecomputedPosition(
        symbol=symbol,
        quantity=quantity,
        avg_cost=avg_cost,
        total_cost=total_cost if quantity > 0 else None,
        realized_pnl=realized_pnl,
        first_entry_date=first_entry_date,
        last_trade_date=last_trade_date,
        source=source,
    )


def recompute_position(session: Session, portfolio_id: str, symbol: str) -> Optional[UserPosition]:
    symbol = normalize_symbol(symbol)
    trades = _ordered_trades(session, portfolio_id, symbol)
    existing = session.execute(
        select(UserPosition).where(UserPosition.portfolio_id == portfolio_id, UserPosition.symbol == symbol)
    ).scalar_one_or_none()
    if not trades:
        if existing:
            session.delete(existing)
            session.flush()
        return None

    computed = _compute_position_from_trades(trades)
    if existing is None:
        existing = UserPosition(portfolio_id=portfolio_id, symbol=symbol)
        session.add(existing)

    existing.quantity = computed.quantity
    existing.avg_cost = computed.avg_cost
    existing.total_cost = computed.total_cost
    existing.realized_pnl = computed.realized_pnl
    existing.first_entry_date = computed.first_entry_date
    existing.last_trade_date = computed.last_trade_date
    existing.source = computed.source
    existing.updated_at = _utcnow()
    if computed.quantity <= 0:
        session.delete(existing)
        session.flush()
        return None
    session.flush()
    return existing


def recompute_portfolio(session: Session, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> int:
    symbols = [row[0] for row in session.execute(
        select(UserTradeLedger.symbol).where(UserTradeLedger.portfolio_id == portfolio_id).distinct()
    ).all()]
    changed = 0
    for symbol in symbols:
        recompute_position(session, portfolio_id, symbol)
        changed += 1
    return changed


def add_trade(
    session: Session,
    *,
    symbol: str,
    side: str,
    trade_date: date,
    price: float,
    quantity: int,
    portfolio_id: str = DEFAULT_PORTFOLIO_ID,
    fees: float = 0.0,
    tax: float = 0.0,
    source: str = "manual",
    external_trade_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> UserTradeLedger:
    ensure_default_portfolio(session, portfolio_id)
    symbol = normalize_symbol(symbol)
    side = side.lower().strip()
    if side not in {"buy", "sell"}:
        raise ValueError(SIDE_ERROR)
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if price <= 0:
        raise ValueError("price must be positive")
    if external_trade_id:
        exists = session.execute(
            select(UserTradeLedger).where(
                UserTradeLedger.portfolio_id == portfolio_id,
                UserTradeLedger.source == source,
                UserTradeLedger.external_trade_id == external_trade_id,
            )
        ).scalar_one_or_none()
        if exists:
            return exists

    trade = UserTradeLedger(
        portfolio_id=portfolio_id,
        symbol=symbol,
        side=side,
        trade_date=trade_date,
        price=price,
        quantity=quantity,
        fees=fees,
        tax=tax,
        source=source,
        external_trade_id=external_trade_id,
        notes=notes,
    )
    session.add(trade)
    session.flush()
    recompute_position(session, portfolio_id, symbol)
    return trade


def update_trade(session: Session, trade_id: int, **updates: Any) -> UserTradeLedger:
    trade = session.get(UserTradeLedger, trade_id)
    if trade is None:
        raise ValueError("trade not found")
    old_symbol = trade.symbol
    old_portfolio = trade.portfolio_id
    if "symbol" in updates and updates["symbol"]:
        trade.symbol = normalize_symbol(updates["symbol"])
    if "side" in updates and updates["side"]:
        side = str(updates["side"]).lower().strip()
        if side not in {"buy", "sell"}:
            raise ValueError(SIDE_ERROR)
        trade.side = side
    for field in ("trade_date", "price", "quantity", "fees", "tax", "source", "external_trade_id", "notes"):
        if field in updates:
            setattr(trade, field, updates[field])
    if trade.quantity <= 0 or trade.price <= 0:
        raise ValueError("quantity and price must be positive")
    trade.updated_at = _utcnow()
    session.flush()
    recompute_position(session, old_portfolio, old_symbol)
    if old_symbol != trade.symbol or old_portfolio != trade.portfolio_id:
        recompute_position(session, trade.portfolio_id, trade.symbol)
    return trade


def delete_trade(session: Session, trade_id: int) -> bool:
    trade = session.get(UserTradeLedger, trade_id)
    if trade is None:
        return False
    portfolio_id = trade.portfolio_id
    symbol = trade.symbol
    session.delete(trade)
    session.flush()
    recompute_position(session, portfolio_id, symbol)
    return True


def list_trades(session: Session, *, portfolio_id: str = DEFAULT_PORTFOLIO_ID, symbol: Optional[str] = None, limit: int = 200) -> list[UserTradeLedger]:
    stmt = select(UserTradeLedger).where(UserTradeLedger.portfolio_id == portfolio_id)
    if symbol:
        stmt = stmt.where(UserTradeLedger.symbol == normalize_symbol(symbol))
    return list(session.execute(stmt.order_by(UserTradeLedger.trade_date.desc(), UserTradeLedger.id.desc()).limit(limit)).scalars().all())


def _latest_price_map(session: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        row = session.execute(
            select(PriceDaily).where(PriceDaily.symbol == symbol).order_by(PriceDaily.trade_date.desc()).limit(1)
        ).scalar_one_or_none()
        if row:
            out[symbol] = {"price": _to_float(row.close, None), "price_date": row.trade_date.isoformat() if row.trade_date else None}
    return out


def list_positions(session: Session, *, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> list[dict[str, Any]]:
    rows = list(session.execute(
        select(UserPosition).where(UserPosition.portfolio_id == portfolio_id, UserPosition.quantity > 0).order_by(UserPosition.symbol.asc())
    ).scalars().all())
    symbols = [row.symbol for row in rows]
    price_map = _latest_price_map(session, symbols)
    profiles = {
        profile.symbol: profile
        for profile in session.execute(select(StockProfile).where(StockProfile.symbol.in_(symbols))).scalars().all()
    } if symbols else {}
    total_value = 0.0
    values: dict[str, float] = {}
    for row in rows:
        price = price_map.get(row.symbol, {}).get("price") or row.avg_cost or 0.0
        market_value = price * row.quantity
        values[row.symbol] = market_value
        total_value += market_value

    out = []
    today = date.today()
    for row in rows:
        latest = price_map.get(row.symbol, {})
        current_price = latest.get("price")
        market_value = values.get(row.symbol, 0.0)
        total_cost = _to_float(row.total_cost, 0.0)
        unrealized = market_value - total_cost if current_price is not None and total_cost else None
        unrealized_pct = (unrealized / total_cost * 100.0) if unrealized is not None and total_cost else None
        holding_days = (today - row.first_entry_date).days if row.first_entry_date else None
        profile = profiles.get(row.symbol)
        out.append({
            "portfolio_id": row.portfolio_id,
            "symbol": row.symbol,
            "name": profile.company_name if profile else None,
            "industry": profile.industry if profile else None,
            "quantity": row.quantity,
            "avg_cost": _round(row.avg_cost),
            "total_cost": _round(row.total_cost),
            "current_price": _round(current_price),
            "price_date": latest.get("price_date"),
            "market_value": _round(market_value, 2),
            "unrealized_pnl": _round(unrealized, 2),
            "unrealized_pnl_pct": _round(unrealized_pct, 2),
            "realized_pnl": _round(row.realized_pnl, 2),
            "weight_pct": _round(market_value / total_value * 100.0, 2) if total_value else None,
            "first_entry_date": row.first_entry_date.isoformat() if row.first_entry_date else None,
            "last_trade_date": row.last_trade_date.isoformat() if row.last_trade_date else None,
            "holding_days": holding_days,
            "source": row.source,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return out


def clear_portfolio(session: Session, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> None:
    session.execute(delete(UserTradeLedger).where(UserTradeLedger.portfolio_id == portfolio_id))
    session.execute(delete(UserPosition).where(UserPosition.portfolio_id == portfolio_id))