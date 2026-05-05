"""潜力股票机会发现 API。"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..services.opportunity_discovery_service import approve_candidate, discover_opportunities, list_opportunity_candidates


router = APIRouter(
    prefix="/api/opportunities",
    tags=["opportunities"],
    responses={
        404: {"description": "Opportunity candidate not found"},
        500: {"description": "Opportunity discovery operation failed"},
    },
)

DbSession = Annotated[Session, Depends(get_session)]


class DiscoverRequest(BaseModel):
    scan_limit: int = Field(120, ge=10, le=1000)
    max_candidates: int = Field(20, ge=1, le=100)
    auto_pin: bool = True
    portfolio_id: str = "default"


class ApproveRequest(BaseModel):
    notes: Optional[str] = None


@router.post("/discover")
def discover(payload: DiscoverRequest, db: DbSession):
    try:
        result = discover_opportunities(
            db,
            scan_limit=payload.scan_limit,
            max_candidates=payload.max_candidates,
            auto_pin=payload.auto_pin,
            portfolio_id=payload.portfolio_id,
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"机会发现失败: {exc}")


@router.get("")
def list_candidates(
    db: DbSession,
    status: Annotated[Optional[str], Query(description="pending/auto_pinned/approved/rejected")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return {"candidates": list_opportunity_candidates(db, status=status, limit=limit)}


@router.post("/{symbol}/approve")
def approve(symbol: str, payload: ApproveRequest, db: DbSession):
    try:
        candidate = approve_candidate(db, symbol, notes=payload.notes)
        db.commit()
        return {"ok": True, "candidate": candidate}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"确认候选失败: {exc}")