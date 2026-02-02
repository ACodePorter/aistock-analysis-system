"""
事件路由 - API端点

Endpoints:
- GET  /api/events
- GET  /api/events/{event_id}
- GET  /api/events/symbol/{symbol}
- POST /api/events/regenerate
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from datetime import date

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    symbol: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    source_level: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """
    列出事件
    
    Query Parameters:
    - symbol: 股票代码
    - event_type: 事件类型
    - source_level: 信源等级 (L1/L2/L3/L4)
    - start_date / end_date: 时间范围
    - skip / limit: 分页
    """
    # TODO: 实现
    pass


@router.get("/{event_id}")
async def get_event(event_id: str):
    """获取事件详情"""
    # TODO: 实现
    pass


@router.get("/symbol/{symbol}")
async def list_events_by_symbol(
    symbol: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    """获取某股票的所有事件"""
    # TODO: 实现
    pass


@router.post("/merge")
async def merge_events(event_ids: List[str]):
    """
    手动合并事件
    
    RequestBody:
    {
        "event_ids": ["evt_xxx", "evt_yyy"]
    }
    """
    # TODO: 实现
    pass


@router.post("/refresh")
async def refresh_events_confidence(symbol: Optional[str] = None):
    """
    刷新事件置信度
    
    Query Params:
    - symbol: 可选，仅刷新某股票的事件
    """
    # TODO: 实现
    pass
