"""
股票池管理 REST API

路由前缀: /api/stock-pool
"""

import logging
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_

from ..core.db import SessionLocal
from ..core.models import StockPoolMember, StockProfile
from ..services.stock_pool_service import _calc_profile_completion
from ..services.stock_pool_service import (
    add_to_pool,
    check_pool_profile_status,
    daily_top_to_pool,
    get_backfill_status,
    get_import_all_status,
    get_pool_stats,
    get_profile_completion_status,
    remove_from_pool,
    search_stocks,
    start_backfill_background,
    start_import_all_background,
    start_profile_completion_background,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stock-pool", tags=["stock-pool"])


def _full_company_name_from_profile(profile: Optional[StockProfile]) -> Optional[str]:
    """从 profile_json 中提取公司全称（轻量业务字段，不依赖 DB schema 变更）。"""
    if not profile or not profile.profile_json:
        return None
    try:
        payload = json.loads(profile.profile_json)
        if isinstance(payload, dict):
            val = payload.get("full_company_name")
            if val and str(val).strip():
                return str(val).strip()
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AddStockRequest(BaseModel):
    symbol: str = Field(..., description="股票代码 (如 000001 / 000001.SZ)")
    name: Optional[str] = Field(None, description="公司名称（可选，自动获取）")
    notes: Optional[str] = None


class BackfillRequest(BaseModel):
    months: int = Field(6, ge=1, le=24)


class ProfileCompletionRequest(BaseModel):
    batch_limit: int = Field(0, ge=0, description="本次最多补全数量，0=不限")
    delay: float = Field(3.0, ge=0, le=60, description="相邻两只股票之间的延迟（秒）")
    force: bool = Field(False, description="强制刷新已有画像")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_pool(
    active: bool = Query(True),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    since: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    profile_filter: Optional[str] = Query(None, description="all/completed/incomplete"),
    sort: str = Query("default", description="default/company_name/last_seen_date/..."),
    order: str = Query("asc"),
    keyword: Optional[str] = Query(None, description="关键字快速检索：股票代码或公司名称"),
):
    """获取股票池列表，支持按画像完成度过滤、关键字检索。"""
    valid_sorts = {
        "default",
        "company_name",
        "first_seen_date",
        "last_seen_date",
        "symbol",
        "days_active",
        "profile_completion",
    }
    if sort not in valid_sorts:
        raise HTTPException(400, f"invalid sort, must be one of {valid_sorts}")
    if order not in ("asc", "desc"):
        raise HTTPException(400, "order must be asc or desc")

    _COMPLETION_THRESHOLD = 50.0

    with SessionLocal() as session:
        q = session.query(StockPoolMember)
        if active:
            q = q.filter(StockPoolMember.exit_date.is_(None))
        if since:
            try:
                q = q.filter(StockPoolMember.first_seen_date >= date.fromisoformat(since))
            except ValueError:
                raise HTTPException(400, "since format: YYYY-MM-DD")
        if industry:
            q = q.join(StockProfile, StockProfile.symbol == StockPoolMember.symbol).filter(
                StockProfile.industry == industry
            )
        if source:
            try:
                q = q.filter(StockPoolMember.source == source)
            except Exception:
                pass

        if profile_filter in ("completed", "incomplete") or sort in ("default", "company_name", "profile_completion"):
            all_members = q.all()
            all_symbols = [m.symbol for m in all_members]
            all_profiles = {}
            if all_symbols:
                for p in session.query(StockProfile).filter(StockProfile.symbol.in_(all_symbols)).all():
                    all_profiles[p.symbol] = p
            if profile_filter == "completed":
                all_members = [
                    m
                    for m in all_members
                    if _calc_profile_completion(all_profiles.get(m.symbol)) >= _COMPLETION_THRESHOLD
                ]
            elif profile_filter == "incomplete":
                all_members = [
                    m
                    for m in all_members
                    if _calc_profile_completion(all_profiles.get(m.symbol)) < _COMPLETION_THRESHOLD
                ]

            if keyword and keyword.strip():
                kw = keyword.strip().lower()
                def _match(m):
                    sym = (m.symbol or "").lower()
                    prof = all_profiles.get(m.symbol)
                    name = (prof.company_name or "").lower() if prof else ""
                    full_name = (_full_company_name_from_profile(prof) or "").lower() if prof else ""
                    return kw in sym or kw in name or kw in full_name
                all_members = [m for m in all_members if _match(m)]

            total = len(all_members)

            if sort == "default":
                # Default ordering:
                #   completed profiles first, then company_name A->Z within each group
                def _key_default(m: StockPoolMember):
                    prof = all_profiles.get(m.symbol)
                    completion = _calc_profile_completion(prof)
                    is_completed = completion >= _COMPLETION_THRESHOLD
                    name = (getattr(prof, "company_name", None) or m.symbol or "").strip().lower()
                    return (0 if is_completed else 1, name, (m.symbol or "").lower())

                all_members.sort(key=_key_default)
                if order == "desc":
                    all_members.reverse()
            elif sort == "company_name":
                def _key_name(m: StockPoolMember):
                    prof = all_profiles.get(m.symbol)
                    name = (getattr(prof, "company_name", None) or m.symbol or "").strip().lower()
                    return (name, (m.symbol or "").lower())

                all_members.sort(key=_key_name, reverse=(order == "desc"))
            elif sort == "profile_completion":
                all_members.sort(
                    key=lambda m: _calc_profile_completion(all_profiles.get(m.symbol)),
                    reverse=(order == "desc"),
                )
            elif sort == "days_active":
                all_members.sort(
                    key=lambda m: ((m.exit_date or date.today()) - m.first_seen_date).days if m.first_seen_date else 0,
                    reverse=(order == "desc"),
                )
            else:
                all_members.sort(key=lambda m: getattr(m, sort, "") or "", reverse=(order == "desc"))

            rows = all_members[offset:offset + limit]
            symbols = [r.symbol for r in rows]
            profiles = {s: all_profiles[s] for s in symbols if s in all_profiles}
        else:
            if keyword and keyword.strip():
                kw = keyword.strip()
                if industry:
                    q = q.filter(or_(
                        StockPoolMember.symbol.ilike(f"%{kw}%"),
                        StockProfile.company_name.ilike(f"%{kw}%"),
                    ))
                else:
                    q = q.outerjoin(StockProfile, StockProfile.symbol == StockPoolMember.symbol)
                    q = q.filter(or_(
                        StockPoolMember.symbol.ilike(f"%{kw}%"),
                        StockProfile.company_name.ilike(f"%{kw}%"),
                    ))
            total = q.count()
            if sort == "days_active":
                today_col = func.current_date()
                sort_col = case(
                    (StockPoolMember.exit_date.is_(None), today_col - StockPoolMember.first_seen_date),
                    else_=StockPoolMember.exit_date - StockPoolMember.first_seen_date,
                )
            elif sort == "profile_completion":
                sort_col = getattr(StockPoolMember, "last_seen_date")
            else:
                sort_col = getattr(StockPoolMember, sort)
            if order == "desc":
                sort_col = sort_col.desc()
            q = q.order_by(sort_col).offset(offset).limit(limit)
            rows = q.all()
            symbols = [r.symbol for r in rows]
            profiles = {}
            if symbols:
                for p in session.query(StockProfile).filter(StockProfile.symbol.in_(symbols)).all():
                    profiles[p.symbol] = p

        out = []
        for r in rows:
            prof = profiles.get(r.symbol)
            ref_end = r.exit_date or date.today()
            days_active = (ref_end - r.first_seen_date).days if r.first_seen_date else None
            src = "top_movers"
            try:
                src = r.source or "top_movers"
            except Exception:
                pass
            out.append({
                "symbol": r.symbol,
                "company_name": prof.company_name if prof else None,
                "full_company_name": _full_company_name_from_profile(prof),
                "first_seen_date": r.first_seen_date.isoformat() if r.first_seen_date else None,
                "last_seen_date": r.last_seen_date.isoformat() if r.last_seen_date else None,
                "exit_date": r.exit_date.isoformat() if r.exit_date else None,
                "source": src,
                "industry": prof.industry if prof else None,
                "days_active": days_active,
                "has_profile": bool(prof and prof.business_summary),
                "profile_completion": _calc_profile_completion(prof),
            })

        return {"count": len(out), "total": total, "rows": out, "limit": limit, "offset": offset}


@router.get("/search")
def search_endpoint(q: str = Query(..., min_length=1), limit: int = Query(20, le=50)):
    """搜索 A 股股票（代码或名称）。"""
    try:
        results = search_stocks(q, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error("[stock-pool/search] error: %s", e, exc_info=True)
        return {"results": [], "count": 0, "error": str(e)}


@router.post("/add")
def add_stock(req: AddStockRequest):
    """手动添加股票到股票池。"""
    try:
        result = add_to_pool(
            symbol=req.symbol,
            source="manual",
            company_name=req.name,
            notes=req.notes,
            enrich=True,
        )
        return result
    except Exception as e:
        logger.error("[stock-pool/add] error for %s: %s", req.symbol, e, exc_info=True)
        raise HTTPException(500, f"添加失败: {e}")


@router.delete("/{symbol}")
def delete_stock(symbol: str):
    """将股票标记退出股票池。"""
    ok = remove_from_pool(symbol)
    if not ok:
        raise HTTPException(404, "股票不在池中")
    return {"ok": True, "symbol": symbol}


@router.get("/stats")
def pool_stats():
    """获取股票池统计概览。"""
    try:
        return get_pool_stats()
    except Exception as e:
        logger.error("[stock-pool/stats] error: %s", e)
        return {
            "total_active": 0, "manual_count": 0, "auto_count": 0,
            "with_profile": 0, "profile_rate": 0, "latest_update": None,
        }


@router.post("/import-today")
def import_today_top(top_n: int = Query(10, ge=5, le=50)):
    """立即导入当日涨跌幅 Top N 到股票池。"""
    try:
        result = daily_top_to_pool(top_n=top_n)
        return result
    except Exception as e:
        logger.error("[stock-pool/import-today] error: %s", e, exc_info=True)
        raise HTTPException(500, f"导入失败: {e}")


@router.post("/backfill")
def trigger_backfill(req: BackfillRequest = BackfillRequest()):
    """触发历史 Top10 回填（后台执行）。"""
    status = get_backfill_status()
    if status["running"]:
        return {"message": "回填任务已在运行中", "status": status}
    start_backfill_background(months=req.months, top_n=10)
    return {"message": "回填任务已启动", "months": req.months}


@router.get("/backfill/status")
def backfill_status():
    """查询回填任务进度。"""
    return get_backfill_status()


@router.post("/import-all")
def import_all():
    """导入全部 A 股到股票池（后台执行）。"""
    status = get_import_all_status()
    if status["running"]:
        return {"message": "全量导入任务已在运行中", "status": status}
    start_import_all_background()
    return {"message": "全量 A 股导入任务已启动"}


@router.get("/import-all/status")
def import_all_status():
    """查询全量导入任务进度。"""
    return get_import_all_status()


# ---------------------------------------------------------------------------
# 画像状态检测 & 补全
# ---------------------------------------------------------------------------

@router.get("/profile-status")
def pool_profile_status():
    """检测股票池所有活跃股票的画像完成状态。

    返回:
    - total_active: 活跃股票总数
    - completed: 画像已完成数（≥50% 字段填充）
    - incomplete: 画像未完成数
    - avg_completion: 平均完成度
    - incomplete_stocks: 未完成股票详情列表
    """
    try:
        return check_pool_profile_status()
    except Exception as e:
        logger.error("[stock-pool/profile-status] error: %s", e, exc_info=True)
        raise HTTPException(500, f"画像状态检测失败: {e}")


@router.post("/profile-completion")
def trigger_profile_completion(req: ProfileCompletionRequest = ProfileCompletionRequest()):
    """触发后台任务，为未完成画像的股票池成员批量补全 Profile。"""
    status = get_profile_completion_status()
    if status["running"]:
        return {"message": "画像补全任务已在运行中", "status": status}

    start_profile_completion_background(
        batch_limit=req.batch_limit,
        delay=req.delay,
        force=req.force,
    )
    return {
        "message": "画像补全任务已启动",
        "batch_limit": req.batch_limit,
        "delay": req.delay,
        "force": req.force,
    }


@router.get("/profile-completion/status")
def profile_completion_progress():
    """查询画像补全任务的实时进度。"""
    return get_profile_completion_status()


# ---------------------------------------------------------------------------
# 单只股票画像详情 & 手动重构
# ---------------------------------------------------------------------------

class RebuildProfileRequest(BaseModel):
    supplementary_info: str = Field("", description="用户提供的补充信息，将与现有画像一起交给 LLM 重构")
    force: bool = Field(True, description="强制刷新画像")


@router.get("/{symbol}/profile")
def get_stock_profile(symbol: str):
    """获取单只股票的完整画像详情。"""
    with SessionLocal() as session:
        prof = session.query(StockProfile).filter(StockProfile.symbol == symbol).first()
        if not prof:
            raise HTTPException(404, f"未找到 {symbol} 的画像数据")

        import json as _json
        profile_json = None
        if prof.profile_json:
            try:
                profile_json = _json.loads(prof.profile_json)
            except Exception:
                profile_json = prof.profile_json

        return {
            "symbol": prof.symbol,
            "company_name": prof.company_name,
            "full_company_name": _full_company_name_from_profile(prof),
            "industry": prof.industry,
            "sub_industry": prof.sub_industry,
            "business_summary": prof.business_summary,
            "core_products": prof.core_products,
            "competitive_position": prof.competitive_position,
            "competitors": prof.competitors,
            "strategic_keywords": prof.strategic_keywords,
            "risk_factors": prof.risk_factors,
            "history_highlights": prof.history_highlights,
            "profile_json": profile_json,
            "last_refreshed": prof.last_refreshed.isoformat() if prof.last_refreshed else None,
            "updated_at": prof.updated_at.isoformat() if prof.updated_at else None,
            "profile_completion": _calc_profile_completion(prof),
        }


@router.post("/{symbol}/rebuild-profile")
def rebuild_stock_profile(symbol: str, req: RebuildProfileRequest = RebuildProfileRequest()):
    """手动触发单只股票的画像重构，支持传入补充信息交给 LLM。"""
    import threading

    with SessionLocal() as session:
        member = session.query(StockPoolMember).filter(
            StockPoolMember.symbol == symbol,
            StockPoolMember.exit_date.is_(None),
        ).first()
        prof = session.query(StockProfile).filter(StockProfile.symbol == symbol).first()

        if not member and not prof:
            raise HTTPException(404, f"股票 {symbol} 不在股票池中且没有画像数据")

        company_name = (prof.company_name if prof else None) or symbol

    def _run():
        try:
            from ..utils.stock_profile_enrichment import StockProfileEnricher
            from ..core.db import SessionLocal as _SL
            enricher = StockProfileEnricher()
            with _SL() as db:
                enricher.enrich_stock_profile_sync(
                    symbol=symbol,
                    company_name=company_name,
                    db=db,
                    force_refresh=req.force,
                    supplementary_info=req.supplementary_info or None,
                )
            logger.info("[stock-pool] rebuild-profile done for %s", symbol)
        except Exception as e:
            logger.error("[stock-pool] rebuild-profile failed for %s: %s", symbol, e, exc_info=True)

    threading.Thread(target=_run, daemon=True, name=f"rebuild-{symbol}").start()

    return {
        "message": f"画像重构任务已启动: {symbol} ({company_name})",
        "symbol": symbol,
        "supplementary_info_provided": bool(req.supplementary_info),
    }
