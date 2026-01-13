#!/usr/bin/env python3
"""
企业档案管理 API 路由

提供 RESTful API 接口用于：
1. 查询企业档案
2. 手动触发档案更新
3. 查看变更历史
4. 管理企业状态

作者: AI Assistant
日期: 2025-11-30
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from app.news.company_profile_scheduler import (
    CompanyProfileScheduler,
    ProfileStatus,
    ChangeType
)
from app.database import get_mongodb_client


# ==================== 数据模型 ====================

class ProfileResponse(BaseModel):
    """档案响应模型"""
    stock_code: str
    company_name: str
    status: ProfileStatus
    initialized_at: Optional[datetime]
    last_updated: Optional[datetime]
    profile: dict
    change_history: List[dict]
    update_metadata: dict


class UpdateRequest(BaseModel):
    """更新请求模型"""
    stock_codes: List[str] = Field(..., description="股票代码列表")
    force_reinit: bool = Field(False, description="是否强制重新初始化")


class UpdateResponse(BaseModel):
    """更新响应模型"""
    success: bool
    message: str
    stats: Optional[dict] = None


class DelistingRequest(BaseModel):
    """退市请求模型"""
    stock_code: str = Field(..., description="股票代码")
    reason: str = Field("退市", description="退市原因")


# ==================== API 路由 ====================

router = APIRouter(prefix="/api/profiles", tags=["企业档案管理"])


def get_scheduler() -> CompanyProfileScheduler:
    """获取调度器实例（依赖注入）"""
    client = get_mongodb_client()
    return CompanyProfileScheduler(client)


@router.get("/", summary="获取企业档案列表")
async def list_profiles(
    status: Optional[ProfileStatus] = Query(None, description="按状态筛选"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(50, ge=1, le=1000, description="返回记录数"),
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """
    获取企业档案列表
    
    支持分页和状态筛选
    """
    query = {}
    if status:
        query["status"] = status
    
    cursor = scheduler.collection.find(query).skip(skip).limit(limit)
    profiles = await cursor.to_list(length=limit)
    
    # 转换 ObjectId 为字符串
    for profile in profiles:
        profile["_id"] = str(profile["_id"])
    
    total = await scheduler.collection.count_documents(query)
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "profiles": profiles
    }


@router.get("/{stock_code}", summary="获取单个企业档案")
async def get_profile(
    stock_code: str,
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """根据股票代码获取企业档案"""
    profile = await scheduler.get_company_profile(stock_code)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"未找到股票代码 {stock_code} 的档案")
    
    # 转换 ObjectId
    profile["_id"] = str(profile["_id"])
    
    return profile


@router.get("/{stock_code}/history", summary="获取企业变更历史")
async def get_change_history(
    stock_code: str,
    limit: int = Query(20, ge=1, le=100, description="返回历史记录数"),
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """获取企业的变更历史记录"""
    profile = await scheduler.get_company_profile(stock_code)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"未找到股票代码 {stock_code} 的档案")
    
    history = profile.get("change_history", [])
    
    # 按时间倒序排列，返回最近的记录
    history.sort(key=lambda x: x.get("timestamp", datetime.min), reverse=True)
    
    return {
        "stock_code": stock_code,
        "company_name": profile.get("company_name"),
        "total_changes": len(history),
        "recent_changes": history[:limit]
    }


@router.post("/initialize", summary="初始化企业档案")
async def initialize_profile(
    stock_code: str = Query(..., description="股票代码"),
    company_name: str = Query(..., description="企业名称"),
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """手动初始化单个企业档案"""
    try:
        profile = await scheduler.initialize_company_profile(stock_code, company_name)
        
        # 转换 ObjectId
        profile["_id"] = str(profile["_id"])
        
        return {
            "success": True,
            "message": f"企业档案初始化成功: {company_name}",
            "profile": profile
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"初始化失败: {str(e)}")


@router.post("/update", summary="批量更新企业档案")
async def update_profiles(
    request: UpdateRequest,
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """
    批量更新企业档案
    
    可以选择强制重新初始化
    """
    try:
        stats = await scheduler.run_weekly_update(
            stock_codes=request.stock_codes,
            batch_size=10
        )
        
        return UpdateResponse(
            success=True,
            message=f"批量更新完成，共 {stats['total']} 家企业",
            stats=stats
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.post("/update/{stock_code}", summary="更新单个企业档案")
async def update_single_profile(
    stock_code: str,
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """手动触发单个企业档案的更新"""
    try:
        # 检查档案是否存在
        existing = await scheduler.get_company_profile(stock_code)
        
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"股票代码 {stock_code} 的档案不存在，请先初始化"
            )
        
        # 执行更新
        updated_profile = await scheduler.update_company_profile(stock_code)
        
        # 转换 ObjectId
        updated_profile["_id"] = str(updated_profile["_id"])
        
        return {
            "success": True,
            "message": f"档案更新成功: {stock_code}",
            "profile": updated_profile
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.post("/delist", summary="标记企业退市")
async def mark_delisted(
    request: DelistingRequest,
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """标记企业为退市状态"""
    try:
        await scheduler.mark_company_delisted(
            stock_code=request.stock_code,
            delisting_reason=request.reason
        )
        
        return {
            "success": True,
            "message": f"企业 {request.stock_code} 已标记为退市"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"标记失败: {str(e)}")


@router.get("/stats/overview", summary="获取档案统计信息")
async def get_stats_overview(
    scheduler: CompanyProfileScheduler = Depends(get_scheduler)
):
    """获取企业档案的整体统计信息"""
    pipeline = [
        {
            "$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }
        }
    ]
    
    status_counts = await scheduler.collection.aggregate(pipeline).to_list(length=None)
    
    # 统计总数
    total = await scheduler.collection.count_documents({})
    
    # 统计本周更新数
    from datetime import timedelta
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    updated_this_week = await scheduler.collection.count_documents({
        "last_updated": {"$gte": one_week_ago}
    })
    
    return {
        "total": total,
        "status_breakdown": {item["_id"]: item["count"] for item in status_counts},
        "updated_this_week": updated_this_week
    }


# ==================== 集成到主应用 ====================

def register_routes(app):
    """注册路由到 FastAPI 应用"""
    app.include_router(router)
