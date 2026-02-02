"""
财务数据 API 路由

提供财务指标、北向资金、龙虎榜相关的 REST API
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.data.financial_data import (
    financial_fetcher, northbound_fetcher, dragon_tiger_fetcher
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/financial", tags=["财务数据"])


# ============ 响应模型 ============

class FinancialIndicatorsResponse(BaseModel):
    """财务指标响应"""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


# ============ 财务指标 API ============

@router.get("/indicators/{symbol}")
async def get_financial_indicators(symbol: str):
    """获取股票财务指标
    
    包含：
    - 估值指标：PE/PB/PS/PCF/市值
    - 盈利能力：ROE/ROA/毛利率/净利率
    - 成长性：EPS/营收/净利润及同比增长
    - 偿债能力：资产负债率/流动比率
    - 分红：股息率
    """
    try:
        indicators = financial_fetcher.fetch_all_indicators(symbol)
        return FinancialIndicatorsResponse(
            success=True,
            data=indicators.to_dict(),
        )
    except Exception as e:
        logger.error(f"获取 {symbol} 财务指标失败: {e}", exc_info=True)
        return FinancialIndicatorsResponse(
            success=False,
            error=str(e),
        )


@router.get("/valuation/{symbol}")
async def get_valuation_indicators(symbol: str):
    """获取估值指标"""
    try:
        data = financial_fetcher.fetch_valuation_indicators(symbol)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/growth/{symbol}")
async def get_growth_indicators(symbol: str):
    """获取成长性指标"""
    try:
        data = financial_fetcher.fetch_growth_indicators(symbol)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/analyst-ratings/{symbol}")
async def get_analyst_ratings(symbol: str, days: int = Query(90, ge=1, le=365)):
    """获取机构评级"""
    try:
        ratings = financial_fetcher.fetch_analyst_ratings(symbol, days)
        return {
            "success": True,
            "data": [r.to_dict() for r in ratings],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 北向资金 API ============

@router.get("/northbound/daily")
async def get_northbound_daily_flow(trade_date: Optional[date] = None):
    """获取北向资金每日流向
    
    返回沪股通、深股通净流入及合计
    """
    try:
        data = northbound_fetcher.fetch_daily_flow(trade_date)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/northbound/holding/{symbol}")
async def get_northbound_holding(symbol: str):
    """获取个股北向持仓"""
    try:
        data = northbound_fetcher.fetch_stock_holding(symbol)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 龙虎榜 API ============

@router.get("/dragon-tiger/daily")
async def get_dragon_tiger_daily(trade_date: Optional[date] = None):
    """获取龙虎榜数据
    
    返回当日上榜股票及机构买卖情况
    """
    try:
        data = dragon_tiger_fetcher.fetch_daily_list(trade_date)
        return {
            "success": True,
            "data": data,
            "count": len(data),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/dragon-tiger/history/{symbol}")
async def get_dragon_tiger_history(symbol: str, days: int = Query(30, ge=1, le=180)):
    """获取个股龙虎榜历史"""
    try:
        data = dragon_tiger_fetcher.fetch_stock_lhb_history(symbol, days)
        return {
            "success": True,
            "data": data,
            "count": len(data),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 综合数据 API ============

@router.get("/comprehensive/{symbol}")
async def get_comprehensive_data(symbol: str):
    """获取股票综合财务数据
    
    一次性获取所有相关数据：
    - 财务指标
    - 北向持仓
    - 龙虎榜历史
    - 机构评级
    """
    try:
        result = {
            "symbol": symbol,
            "financial_indicators": None,
            "northbound_holding": None,
            "dragon_tiger": None,
            "analyst_ratings": None,
        }
        
        # 获取财务指标
        try:
            indicators = financial_fetcher.fetch_all_indicators(symbol)
            result["financial_indicators"] = indicators.to_dict()
        except Exception as e:
            logger.warning(f"获取财务指标失败: {e}")
        
        # 获取北向持仓
        try:
            holding = northbound_fetcher.fetch_stock_holding(symbol)
            result["northbound_holding"] = holding
        except Exception as e:
            logger.warning(f"获取北向持仓失败: {e}")
        
        # 获取龙虎榜
        try:
            lhb = dragon_tiger_fetcher.fetch_stock_lhb_history(symbol, 30)
            result["dragon_tiger"] = lhb
        except Exception as e:
            logger.warning(f"获取龙虎榜失败: {e}")
        
        # 获取机构评级
        try:
            ratings = financial_fetcher.fetch_analyst_ratings(symbol, 90)
            result["analyst_ratings"] = [r.to_dict() for r in ratings]
        except Exception as e:
            logger.warning(f"获取机构评级失败: {e}")
        
        return {"success": True, "data": result}
        
    except Exception as e:
        logger.error(f"获取综合数据失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
