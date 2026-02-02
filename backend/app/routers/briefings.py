"""
简报路由 - API端点

Endpoints:
- GET  /api/briefings
- GET  /api/briefings/{briefing_id}
- GET  /api/briefings/symbol/{symbol}
- POST /api/briefings/regenerate
"""

from fastapi import APIRouter, Query
from typing import Optional
from datetime import date

router = APIRouter(prefix="/api/briefings", tags=["briefings"])


@router.get("")
async def list_briefings(
    symbol: Optional[str] = Query(None),
    period: Optional[str] = Query(None),  # daily / weekly
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """
    列出简报
    
    Query Parameters:
    - symbol: 股票代码
    - period: daily / weekly
    - start_date / end_date: 时间范围
    - skip / limit: 分页
    """
    # TODO: 实现
    pass


@router.get("/{briefing_id}")
async def get_briefing(briefing_id: str):
    """获取简报详情"""
    # TODO: 实现
    pass


@router.get("/symbol/{symbol}")
async def list_briefings_by_symbol(
    symbol: str,
    period: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    """获取某股票的简报列表"""
    # TODO: 实现
    pass


@router.get("/latest/market")
async def get_latest_market_briefing():
    """获取最新市场综合日报"""
    # TODO: 实现
    pass


@router.post("/regenerate/{briefing_id}")
async def regenerate_briefing(briefing_id: str):
    """重新生成指定简报"""
    # TODO: 实现
    pass


@router.post("/generate/daily")
async def trigger_daily_generation(date_str: str):
    """
    手动触发日报生成
    
    Query Params:
    - date: 报告日期 (YYYY-MM-DD)
    """
    # TODO: 实现
    pass


@router.post("/generate/weekly")
async def trigger_weekly_generation(week_start: str):
    """
    手动触发周报生成
    
    Query Params:
    - week_start: 周开始日期 (YYYY-MM-DD)
    """
    # TODO: 实现
    pass
