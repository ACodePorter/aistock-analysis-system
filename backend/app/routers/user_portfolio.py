"""用户持仓与交易流水 API。"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..services.user_portfolio_service import (
    DEFAULT_PORTFOLIO_ID,
    add_trade,
    delete_trade,
    ensure_default_portfolio,
    list_positions,
    list_trades,
    recompute_portfolio,
    update_trade,
)


router = APIRouter(
    prefix="/api/user-portfolio",
    tags=["user-portfolio"],
    responses={
        400: {"description": "Invalid trade or portfolio request"},
        404: {"description": "Trade not found"},
        500: {"description": "User portfolio operation failed"},
    },
)

DbSession = Annotated[Session, Depends(get_session)]


class TradeIn(BaseModel):
    symbol: str = Field(..., description="股票代码，如 600519.SH / 600519")
    side: str = Field(..., description="buy/sell")
    trade_date: date
    price: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    fees: float = Field(0.0, ge=0)
    tax: float = Field(0.0, ge=0)
    source: str = Field("manual", description="manual/broker_import")
    external_trade_id: Optional[str] = None
    notes: Optional[str] = None


class TradeUpdate(BaseModel):
    symbol: Optional[str] = None
    side: Optional[str] = None
    trade_date: Optional[date] = None
    price: Optional[float] = Field(None, gt=0)
    quantity: Optional[int] = Field(None, gt=0)
    fees: Optional[float] = Field(None, ge=0)
    tax: Optional[float] = Field(None, ge=0)
    source: Optional[str] = None
    external_trade_id: Optional[str] = None
    notes: Optional[str] = None


def _trade_to_dict(trade) -> dict:
    return {
        "id": trade.id,
        "portfolio_id": trade.portfolio_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "trade_date": trade.trade_date.isoformat() if trade.trade_date else None,
        "price": trade.price,
        "quantity": trade.quantity,
        "fees": trade.fees,
        "tax": trade.tax,
        "source": trade.source,
        "external_trade_id": trade.external_trade_id,
        "notes": trade.notes,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "updated_at": trade.updated_at.isoformat() if trade.updated_at else None,
    }


@router.get("/positions")
def get_positions(
    db: DbSession,
    portfolio_id: Annotated[str, Query()] = DEFAULT_PORTFOLIO_ID,
):
    ensure_default_portfolio(db, portfolio_id)
    positions = list_positions(db, portfolio_id=portfolio_id)
    return {"portfolio_id": portfolio_id, "positions": positions, "count": len(positions)}


@router.get("/trades")
def get_trades(
    db: DbSession,
    portfolio_id: Annotated[str, Query()] = DEFAULT_PORTFOLIO_ID,
    symbol: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    ensure_default_portfolio(db, portfolio_id)
    trades = list_trades(db, portfolio_id=portfolio_id, symbol=symbol, limit=limit)
    return {"portfolio_id": portfolio_id, "trades": [_trade_to_dict(t) for t in trades], "count": len(trades)}


@router.post("/trades")
def create_trade(
    payload: TradeIn,
    db: DbSession,
    portfolio_id: Annotated[str, Query()] = DEFAULT_PORTFOLIO_ID,
):
    try:
        trade = add_trade(db, portfolio_id=portfolio_id, **payload.dict())
        db.commit()
        db.refresh(trade)
        return {"ok": True, "trade": _trade_to_dict(trade)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建交易流水失败: {exc}")


@router.put("/trades/{trade_id}")
def put_trade(trade_id: int, payload: TradeUpdate, db: DbSession):
    try:
        updates = {key: value for key, value in payload.dict().items() if value is not None}
        trade = update_trade(db, trade_id, **updates)
        db.commit()
        db.refresh(trade)
        return {"ok": True, "trade": _trade_to_dict(trade)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新交易流水失败: {exc}")


@router.delete("/trades/{trade_id}")
def remove_trade(trade_id: int, db: DbSession):
    try:
        ok = delete_trade(db, trade_id)
        if not ok:
            raise HTTPException(status_code=404, detail="trade not found")
        db.commit()
        return {"ok": True}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除交易流水失败: {exc}")


@router.post("/recompute")
def recompute(
    db: DbSession,
    portfolio_id: Annotated[str, Query()] = DEFAULT_PORTFOLIO_ID,
):
    try:
        ensure_default_portfolio(db, portfolio_id)
        changed = recompute_portfolio(db, portfolio_id=portfolio_id)
        db.commit()
        return {"ok": True, "portfolio_id": portfolio_id, "symbols_recomputed": changed}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"持仓重算失败: {exc}")