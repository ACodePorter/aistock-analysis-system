"""
每日分析中心 API 路由

提供以下功能:
- 每日分析数据查询
- 历史分析记录
- 每日综合报告（即时分析+纵向趋势分析双版本）
- 投资潜力评估
- 观察列表管理
- 调度状态查询
- 阶段性报告（周/月/季/年）
"""

import logging
import json
import os
from datetime import date, datetime, timedelta
from typing import Optional, List
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, desc, func, or_, case, Integer
from sqlalchemy.orm import Session

from app.core.db import get_session as get_db
from app.core.models import (
    Watchlist, DailyAnalysis, DailyReport, SimulatedTrade, AnalysisHistory
)
from app.analysis.analysis_engine import AnalysisEngine
from app.analysis.report_generator import DailyReportGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["Analysis Center"])


# ==================== 报告类型枚举 ====================

class ReportType(str, Enum):
    INSTANT = "instant"      # 即时分析（基于最新数据）
    LONGITUDINAL = "longitudinal"  # 纵向趋势分析（基于历史数据）


class PeriodType(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


# ==================== Pydantic Models ====================

class ScoreBreakdownResponse(BaseModel):
    technical: float
    fundamental: float
    sentiment: float
    fund_flow: float
    cycle: float
    total: float


class StockAnalysisResponse(BaseModel):
    symbol: str
    name: Optional[str]
    sector: Optional[str]
    analysis_date: str
    scores: ScoreBreakdownResponse
    recommendation: str
    risk_level: str
    confidence: float
    close_price: Optional[float]
    pct_change: Optional[float]
    volume: Optional[int]
    ma5: Optional[float]
    ma20: Optional[float]
    rsi: Optional[float]
    macd: Optional[float]
    news_count: int
    news_sentiment_avg: Optional[float]
    analysis_summary: str
    key_factors: List[str]
    risk_factors: List[str]


class DailyAnalysisSummary(BaseModel):
    analysis_date: str
    total_stocks: int
    buy_count: int
    hold_count: int
    sell_count: int
    avg_score: float
    status: str


class DailyReportResponse(BaseModel):
    report_date: str
    total_stocks: int
    buy_count: int
    hold_count: int
    sell_count: int
    market_sentiment: str
    market_summary: str
    buy_recommendations: List[dict]
    hold_recommendations: List[dict]
    sell_recommendations: List[dict]
    comprehensive_analysis: str
    risk_warnings: List[dict]
    opportunities: List[dict]
    sector_analysis: dict
    generated_at: Optional[str]
    generation_model: Optional[str]


class InvestmentPotentialResponse(BaseModel):
    symbol: str
    evaluation_date: str
    lookback_days: int
    analysis_count: int
    trade_count: int
    avg_score: float
    score_trend: str
    total_profit_loss: float
    win_rate: float
    investment_potential: float
    should_remove: bool
    remove_reason: Optional[str]


class WatchlistItemResponse(BaseModel):
    symbol: str
    name: Optional[str]
    sector: Optional[str]
    enabled: bool
    source: str
    score: Optional[float]
    investment_potential: Optional[float]
    remove_suggested: bool
    remove_reason: Optional[str]
    added_at: str
    last_analysis_at: Optional[str]
    observation_days: int


class AddToWatchlistRequest(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    source: str = "manual"


class RunAnalysisRequest(BaseModel):
    symbols: Optional[List[str]] = None  # 如果为空则分析整个观察列表
    generate_report: bool = True


# ==================== 每日分析接口 ====================

@router.get("/daily/{analysis_date}", response_model=List[StockAnalysisResponse])
async def get_daily_analysis(
    analysis_date: str,
    recommendation: Optional[str] = Query(None, description="筛选推荐类型: buy/hold/sell"),
    risk_level: Optional[str] = Query(None, description="筛选风险等级: low/medium/high"),
    min_score: Optional[float] = Query(None, description="最低评分"),
    sort_by: str = Query("score", description="排序字段: score/pct_change/name"),
    db: Session = Depends(get_db)
):
    """获取指定日期的分析结果"""
    try:
        target_date = date.fromisoformat(analysis_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    query = select(DailyAnalysis).where(DailyAnalysis.analysis_date == target_date)
    
    if recommendation:
        query = query.where(DailyAnalysis.recommendation == recommendation)
    if risk_level:
        query = query.where(DailyAnalysis.risk_level == risk_level)
    if min_score is not None:
        query = query.where(DailyAnalysis.total_score >= min_score)
    
    # 排序
    if sort_by == "score":
        query = query.order_by(desc(DailyAnalysis.total_score))
    elif sort_by == "pct_change":
        query = query.order_by(desc(DailyAnalysis.pct_change))
    else:
        query = query.order_by(DailyAnalysis.symbol)
    
    analyses = db.execute(query).scalars().all()
    
    results = []
    for a in analyses:
        # 获取股票名称
        watchlist = db.execute(
            select(Watchlist).where(Watchlist.symbol == a.symbol)
        ).scalar_one_or_none()
        
        results.append(StockAnalysisResponse(
            symbol=a.symbol,
            name=watchlist.name if watchlist else None,
            sector=watchlist.sector if watchlist else None,
            analysis_date=a.analysis_date.isoformat(),
            scores=ScoreBreakdownResponse(
                technical=a.technical_score or 50,
                fundamental=a.fundamental_score or 50,
                sentiment=a.sentiment_score or 50,
                fund_flow=a.fund_flow_score or 50,
                cycle=a.cycle_score or 50,
                total=a.total_score or 50
            ),
            recommendation=a.recommendation or 'hold',
            risk_level=a.risk_level or 'medium',
            confidence=a.confidence or 0.5,
            close_price=a.close_price,
            pct_change=a.pct_change,
            volume=a.volume,
            ma5=a.ma5,
            ma20=a.ma20,
            rsi=a.rsi,
            macd=a.macd,
            news_count=a.news_count or 0,
            news_sentiment_avg=a.news_sentiment_avg,
            analysis_summary=a.analysis_summary or '',
            key_factors=json.loads(a.key_factors) if a.key_factors else [],
            risk_factors=json.loads(a.risk_factors) if a.risk_factors else []
        ))
    
    return results


@router.get("/stock/{symbol}/history")
async def get_stock_analysis_history(
    symbol: str,
    days: int = Query(30, ge=1, le=365, description="历史天数"),
    db: Session = Depends(get_db)
):
    """获取单只股票的历史分析记录"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    analyses = db.execute(
        select(DailyAnalysis).where(
            and_(
                DailyAnalysis.symbol == symbol,
                DailyAnalysis.analysis_date >= start_date,
                DailyAnalysis.analysis_date <= end_date
            )
        ).order_by(desc(DailyAnalysis.analysis_date))
    ).scalars().all()
    
    return {
        "symbol": symbol,
        "period": f"{start_date.isoformat()} to {end_date.isoformat()}",
        "total_records": len(analyses),
        "history": [
            {
                "date": a.analysis_date.isoformat(),
                "score": a.total_score,
                "recommendation": a.recommendation,
                "risk_level": a.risk_level,
                "close_price": a.close_price,
                "pct_change": a.pct_change
            }
            for a in analyses
        ]
    }


@router.get("/history", response_model=List[DailyAnalysisSummary])
async def get_analysis_history(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """获取分析历史索引"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    # 聚合每日分析统计
    results = db.execute(
        select(
            DailyAnalysis.analysis_date,
            func.count(DailyAnalysis.id).label('total'),
            func.avg(DailyAnalysis.total_score).label('avg_score'),
            func.sum(case((DailyAnalysis.recommendation == 'buy', 1), else_=0)).label('buy_count'),
            func.sum(case((DailyAnalysis.recommendation == 'hold', 1), else_=0)).label('hold_count'),
            func.sum(case((DailyAnalysis.recommendation == 'sell', 1), else_=0)).label('sell_count')
        ).where(
            and_(
                DailyAnalysis.analysis_date >= start_date,
                DailyAnalysis.analysis_date <= end_date
            )
        ).group_by(DailyAnalysis.analysis_date).order_by(desc(DailyAnalysis.analysis_date))
    ).all()
    
    return [
        DailyAnalysisSummary(
            analysis_date=r.analysis_date.isoformat(),
            total_stocks=r.total,
            buy_count=r.buy_count or 0,
            hold_count=r.hold_count or 0,
            sell_count=r.sell_count or 0,
            avg_score=float(r.avg_score) if r.avg_score else 50.0,
            status="completed"
        )
        for r in results
    ]


# ==================== 每日报告接口 ====================

@router.get("/report/latest", response_model=DailyReportResponse)
async def get_latest_report(
    report_type: ReportType = Query(ReportType.INSTANT, description="报告类型: instant=即时分析, longitudinal=纵向趋势"),
    db: Session = Depends(get_db)
):
    """获取最新的综合报告
    
    - instant: 基于当日最新数据的即时分析
    - longitudinal: 基于历史趋势的纵向分析
    """
    report = db.execute(
        select(DailyReport).order_by(desc(DailyReport.report_date)).limit(1)
    ).scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="No reports available")
    
    generator = DailyReportGenerator(db)
    return DailyReportResponse(**generator.get_report(report.report_date))


@router.get("/report/{report_date}", response_model=DailyReportResponse)
async def get_daily_report(
    report_date: str,
    db: Session = Depends(get_db)
):
    """获取指定日期的综合报告"""
    try:
        target_date = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    generator = DailyReportGenerator(db)
    report = generator.get_report(target_date)
    
    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for {report_date}")
    
    return DailyReportResponse(**report)


# ==================== 运行分析 ====================

@router.post("/run")
async def run_analysis(
    request: RunAnalysisRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """手动触发分析任务"""
    analysis_date = date.today()
    
    engine = AnalysisEngine(db)
    
    if request.symbols:
        # 分析指定股票
        results = []
        for symbol in request.symbols:
            result = engine.analyze_stock(symbol, analysis_date)
            if result:
                results.append(result)
    else:
        # 分析整个观察列表
        results = engine.analyze_watchlist(analysis_date)
    
    # 保存结果
    saved_count = engine.save_analysis_results(results)
    
    # 生成报告
    report_generated = False
    if request.generate_report and results:
        generator = DailyReportGenerator(db)
        report = generator.generate_report(analysis_date, results)
        report_generated = report is not None
    
    return {
        "status": "success",
        "analysis_date": analysis_date.isoformat(),
        "stocks_analyzed": len(results),
        "results_saved": saved_count,
        "report_generated": report_generated,
        "summary": {
            "buy": sum(1 for r in results if r.recommendation == 'buy'),
            "hold": sum(1 for r in results if r.recommendation == 'hold'),
            "sell": sum(1 for r in results if r.recommendation == 'sell')
        }
    }


# ==================== 投资潜力评估 ====================

@router.get("/potential/{symbol}", response_model=InvestmentPotentialResponse)
async def evaluate_potential(
    symbol: str,
    lookback_days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db)
):
    """评估股票投资潜力"""
    engine = AnalysisEngine(db)
    result = engine.evaluate_investment_potential(symbol, lookback_days)
    return InvestmentPotentialResponse(**result)


@router.post("/potential/evaluate-all")
async def evaluate_all_potential(
    lookback_days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db)
):
    """评估所有观察列表股票的投资潜力"""
    watchlist = db.execute(
        select(Watchlist).where(Watchlist.enabled == True)
    ).scalars().all()
    
    engine = AnalysisEngine(db)
    results = []
    
    for item in watchlist:
        result = engine.evaluate_investment_potential(item.symbol, lookback_days)
        results.append(result)
        
        # 更新 Watchlist 的投资潜力评估
        item.investment_potential = result['investment_potential']
        if result['should_remove']:
            item.remove_suggested = True
            item.remove_reason = result['remove_reason']
    
    db.commit()
    
    # 统计
    should_remove = [r for r in results if r['should_remove']]
    
    return {
        "status": "success",
        "total_evaluated": len(results),
        "suggested_removals": len(should_remove),
        "removal_suggestions": [
            {
                "symbol": r['symbol'],
                "potential": r['investment_potential'],
                "reason": r['remove_reason']
            }
            for r in should_remove
        ]
    }


# ==================== 观察列表管理 ====================

@router.get("/watchlist", response_model=List[WatchlistItemResponse])
async def get_watchlist(
    enabled_only: bool = Query(True),
    include_removal_suggestions: bool = Query(False),
    sort_by: str = Query("score", description="排序: score/added_at/name"),
    db: Session = Depends(get_db)
):
    """获取观察列表"""
    query = select(Watchlist)
    
    if enabled_only:
        query = query.where(Watchlist.enabled == True)
    
    if include_removal_suggestions:
        query = query.where(Watchlist.remove_suggested == True)
    
    # 排序
    if sort_by == "score":
        query = query.order_by(desc(Watchlist.score))
    elif sort_by == "added_at":
        query = query.order_by(desc(Watchlist.added_at))
    else:
        query = query.order_by(Watchlist.symbol)
    
    items = db.execute(query).scalars().all()
    
    now = datetime.utcnow()
    
    return [
        WatchlistItemResponse(
            symbol=item.symbol,
            name=item.name,
            sector=item.sector,
            enabled=item.enabled,
            source=item.source or 'manual',
            score=item.score,
            investment_potential=item.investment_potential,
            remove_suggested=item.remove_suggested,
            remove_reason=item.remove_reason,
            added_at=item.added_at.isoformat() if item.added_at else '',
            last_analysis_at=item.last_analysis_at.isoformat() if item.last_analysis_at else None,
            observation_days=(now - item.added_at).days if item.added_at else 0
        )
        for item in items
    ]


@router.post("/watchlist/add")
async def add_to_watchlist(
    request: AddToWatchlistRequest,
    db: Session = Depends(get_db)
):
    """添加股票到观察列表"""
    # 检查是否已存在
    existing = db.execute(
        select(Watchlist).where(Watchlist.symbol == request.symbol)
    ).scalar_one_or_none()
    
    if existing:
        # 如果已存在但被禁用，重新启用
        if not existing.enabled:
            existing.enabled = True
            existing.remove_suggested = False
            existing.remove_reason = None
            db.commit()
            return {"status": "re-enabled", "symbol": request.symbol}
        return {"status": "already_exists", "symbol": request.symbol}
    
    # 添加新记录
    item = Watchlist(
        symbol=request.symbol,
        name=request.name,
        sector=request.sector,
        source=request.source,
        enabled=True
    )
    db.add(item)
    db.commit()
    
    return {"status": "added", "symbol": request.symbol}


@router.delete("/watchlist/{symbol}")
async def remove_from_watchlist(
    symbol: str,
    permanent: bool = Query(False, description="是否永久删除"),
    db: Session = Depends(get_db)
):
    """从观察列表移除股票"""
    item = db.execute(
        select(Watchlist).where(Watchlist.symbol == symbol)
    ).scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found in watchlist")
    
    if permanent:
        db.delete(item)
    else:
        item.enabled = False
    
    db.commit()
    
    return {"status": "removed", "symbol": symbol, "permanent": permanent}


@router.post("/watchlist/sync-from-homepage")
async def sync_from_homepage(db: Session = Depends(get_db)):
    """从首页市场总览同步股票到观察列表
    
    这里假设首页手动添加的股票存储在 Watchlist 表中，source='manual'
    """
    # 获取所有手动添加的股票
    manual_items = db.execute(
        select(Watchlist).where(Watchlist.source == 'manual')
    ).scalars().all()
    
    # 确保它们都在观察列表中且启用
    synced = 0
    for item in manual_items:
        if not item.enabled:
            item.enabled = True
            item.remove_suggested = False
            synced += 1
    
    db.commit()
    
    return {
        "status": "success",
        "total_manual": len(manual_items),
        "re_enabled": synced
    }


@router.get("/watchlist/removal-suggestions")
async def get_removal_suggestions(db: Session = Depends(get_db)):
    """获取建议移除的股票列表"""
    items = db.execute(
        select(Watchlist).where(
            and_(
                Watchlist.enabled == True,
                Watchlist.remove_suggested == True
            )
        )
    ).scalars().all()
    
    return {
        "total": len(items),
        "suggestions": [
            {
                "symbol": item.symbol,
                "name": item.name,
                "investment_potential": item.investment_potential,
                "reason": item.remove_reason,
                "observation_days": (datetime.utcnow() - item.added_at).days if item.added_at else 0
            }
            for item in items
        ]
    }


@router.post("/watchlist/{symbol}/confirm-removal")
async def confirm_removal(
    symbol: str,
    db: Session = Depends(get_db)
):
    """确认移除建议移除的股票"""
    item = db.execute(
        select(Watchlist).where(Watchlist.symbol == symbol)
    ).scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    
    if not item.remove_suggested:
        raise HTTPException(status_code=400, detail=f"Symbol {symbol} is not suggested for removal")
    
    item.enabled = False
    db.commit()
    
    return {"status": "removed", "symbol": symbol}


# ==================== 调度状态接口 ====================

class SchedulerStatusResponse(BaseModel):
    """调度器状态响应"""
    analysis_enabled: bool
    last_analysis_time: Optional[str]
    next_analysis_time: Optional[str]
    analysis_cron: str
    jobs: List[dict]


@router.get("/scheduler/status")
async def get_scheduler_status(db: Session = Depends(get_db)):
    """获取分析调度器状态
    
    返回最近一次分析时间、下次计划时间等信息，
    前端据此展示自动化分析状态而非手动触发按钮。
    """
    # 获取分析 CRON 配置
    analysis_hour = int(os.getenv('ANALYSIS_CRON_HOUR', '18'))
    analysis_minute = int(os.getenv('ANALYSIS_CRON_MINUTE', '0'))
    
    # 获取最近分析记录
    last_analysis = db.execute(
        select(DailyAnalysis.analysis_date)
        .order_by(desc(DailyAnalysis.analysis_date))
        .limit(1)
    ).scalar_one_or_none()
    
    # 获取最近报告生成时间
    last_report = db.execute(
        select(DailyReport.generated_at)
        .order_by(desc(DailyReport.generated_at))
        .limit(1)
    ).scalar_one_or_none()
    
    # 计算下次分析时间
    now = datetime.now()
    today_scheduled = now.replace(hour=analysis_hour, minute=analysis_minute, second=0, microsecond=0)
    if now > today_scheduled:
        next_analysis = today_scheduled + timedelta(days=1)
    else:
        next_analysis = today_scheduled
    
    # 调度任务列表
    jobs = [
        {
            "id": "daily_analysis_job",
            "name": "每日分析",
            "schedule": f"每天 {analysis_hour:02d}:{analysis_minute:02d}",
            "status": "active"
        },
        {
            "id": "weekly_potential_evaluation",
            "name": "每周投资潜力评估",
            "schedule": "每周日 02:00",
            "status": "active"
        }
    ]
    
    return {
        "analysis_enabled": True,
        "last_analysis_time": last_analysis.isoformat() if last_analysis else None,
        "last_report_time": last_report.isoformat() if last_report else None,
        "next_analysis_time": next_analysis.isoformat(),
        "analysis_cron": f"{analysis_minute} {analysis_hour} * * *",
        "jobs": jobs
    }


# ==================== 涨跌幅分析接口 ====================

class MoverAnalysisResponse(BaseModel):
    """涨跌幅分析响应"""
    symbol: str
    name: Optional[str]
    pct_change: float
    close_price: float
    volume: int
    analysis_date: str
    in_watchlist: bool
    analysis: Optional[dict] = None


@router.get("/movers/{analysis_date}")
async def get_movers_analysis(
    analysis_date: str,
    limit: int = Query(20, ge=5, le=50),
    mover_type: str = Query("both", description="gainers=涨幅榜, losers=跌幅榜, both=两者"),
    db: Session = Depends(get_db)
):
    """获取指定日期的涨跌幅分析
    
    返回当日涨跌幅最大的股票及其分析结果（如果在观察列表中）。
    """
    try:
        target_date = date.fromisoformat(analysis_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    from app.core.models import PriceDaily
    
    # 获取当日所有价格数据
    price_query = select(PriceDaily).where(PriceDaily.trade_date == target_date)
    
    if mover_type == "gainers":
        price_query = price_query.order_by(desc(PriceDaily.pct_chg)).limit(limit)
    elif mover_type == "losers":
        price_query = price_query.order_by(PriceDaily.pct_chg).limit(limit)
    else:
        # 获取涨幅榜和跌幅榜各一半
        half = limit // 2
        gainers = db.execute(
            select(PriceDaily).where(PriceDaily.trade_date == target_date)
            .order_by(desc(PriceDaily.pct_chg)).limit(half)
        ).scalars().all()
        losers = db.execute(
            select(PriceDaily).where(PriceDaily.trade_date == target_date)
            .order_by(PriceDaily.pct_chg).limit(half)
        ).scalars().all()
        prices = gainers + losers
    
    if mover_type != "both":
        prices = db.execute(price_query).scalars().all()
    
    # 获取观察列表股票
    watchlist_symbols = set(
        row[0] for row in db.execute(
            select(Watchlist.symbol).where(Watchlist.enabled == True)
        ).all()
    )
    
    results = []
    for p in prices:
        # 检查是否在观察列表中
        in_watchlist = p.symbol in watchlist_symbols
        
        # 如果在观察列表中，获取分析结果
        analysis = None
        if in_watchlist:
            analysis_result = db.execute(
                select(DailyAnalysis).where(
                    and_(
                        DailyAnalysis.symbol == p.symbol,
                        DailyAnalysis.analysis_date == target_date
                    )
                )
            ).scalar_one_or_none()
            
            if analysis_result:
                analysis = {
                    "score": analysis_result.total_score,
                    "recommendation": analysis_result.recommendation,
                    "risk_level": analysis_result.risk_level,
                    "summary": analysis_result.analysis_summary
                }
        
        # 获取股票名称
        watchlist_item = db.execute(
            select(Watchlist).where(Watchlist.symbol == p.symbol)
        ).scalar_one_or_none()
        
        results.append({
            "symbol": p.symbol,
            "name": watchlist_item.name if watchlist_item else None,
            "pct_change": float(p.pct_chg) if p.pct_chg else 0.0,
            "close_price": float(p.close) if p.close else 0.0,
            "volume": int(p.vol) if p.vol else 0,
            "analysis_date": target_date.isoformat(),
            "in_watchlist": in_watchlist,
            "analysis": analysis
        })
    
    # 按涨跌幅排序
    gainers_list = [r for r in results if r["pct_change"] > 0]
    losers_list = [r for r in results if r["pct_change"] < 0]
    gainers_list.sort(key=lambda x: x["pct_change"], reverse=True)
    losers_list.sort(key=lambda x: x["pct_change"])
    
    return {
        "analysis_date": target_date.isoformat(),
        "gainers": gainers_list,
        "losers": losers_list,
        "total_gainers": len(gainers_list),
        "total_losers": len(losers_list)
    }


# ==================== 阶段性报告接口 ====================

class PeriodReportResponse(BaseModel):
    """阶段性报告响应"""
    period_type: str
    start_date: str
    end_date: str
    total_trading_days: int
    market_trend: str
    avg_score: float
    score_change: float
    buy_signals_count: int
    sell_signals_count: int
    top_performers: List[dict]
    worst_performers: List[dict]
    sector_performance: dict
    comprehensive_analysis: str
    key_insights: List[str]
    risk_warnings: List[str]
    generated_at: str


@router.get("/report/period/{period_type}")
async def get_period_report(
    period_type: PeriodType,
    reference_date: Optional[str] = Query(None, description="参考日期（默认今天）"),
    db: Session = Depends(get_db)
):
    """获取阶段性总结报告
    
    - weekly: 本周/上周行情分析
    - monthly: 本月/上月行情分析
    - quarterly: 本季度行情分析
    - yearly: 本年度行情分析
    """
    # 确定日期范围
    if reference_date:
        try:
            ref_date = date.fromisoformat(reference_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    else:
        ref_date = date.today()
    
    # 根据周期类型计算起止日期
    if period_type == PeriodType.WEEKLY:
        # 本周（周一到今天）
        start_date = ref_date - timedelta(days=ref_date.weekday())
        end_date = ref_date
        period_name = "本周"
    elif period_type == PeriodType.MONTHLY:
        # 本月
        start_date = ref_date.replace(day=1)
        end_date = ref_date
        period_name = "本月"
    elif period_type == PeriodType.QUARTERLY:
        # 本季度
        quarter = (ref_date.month - 1) // 3
        start_month = quarter * 3 + 1
        start_date = ref_date.replace(month=start_month, day=1)
        end_date = ref_date
        period_name = f"Q{quarter + 1}"
    else:  # YEARLY
        # 本年度
        start_date = ref_date.replace(month=1, day=1)
        end_date = ref_date
        period_name = f"{ref_date.year}年"
    
    # 获取期间的分析数据
    analyses = db.execute(
        select(DailyAnalysis).where(
            and_(
                DailyAnalysis.analysis_date >= start_date,
                DailyAnalysis.analysis_date <= end_date
            )
        ).order_by(DailyAnalysis.analysis_date)
    ).scalars().all()
    
    if not analyses:
        raise HTTPException(
            status_code=404, 
            detail=f"No analysis data available for {period_name} ({start_date} to {end_date})"
        )
    
    # 统计交易日数
    trading_days = len(set(a.analysis_date for a in analyses))
    
    # 平均评分
    avg_score = sum(a.total_score or 50 for a in analyses) / len(analyses)
    
    # 评分变化趋势
    first_day_scores = [a.total_score for a in analyses if a.analysis_date == start_date]
    last_day_scores = [a.total_score for a in analyses if a.analysis_date == end_date]
    first_avg = sum(first_day_scores) / len(first_day_scores) if first_day_scores else avg_score
    last_avg = sum(last_day_scores) / len(last_day_scores) if last_day_scores else avg_score
    score_change = last_avg - first_avg
    
    # 市场趋势判断
    if score_change > 5:
        market_trend = "上升"
    elif score_change < -5:
        market_trend = "下降"
    else:
        market_trend = "震荡"
    
    # 买卖信号统计
    buy_signals = sum(1 for a in analyses if a.recommendation == 'buy')
    sell_signals = sum(1 for a in analyses if a.recommendation == 'sell')
    
    # 表现最好/最差的股票
    stock_performance = {}
    for a in analyses:
        if a.symbol not in stock_performance:
            stock_performance[a.symbol] = {
                "symbol": a.symbol,
                "name": None,
                "scores": [],
                "pct_changes": []
            }
        stock_performance[a.symbol]["scores"].append(a.total_score or 50)
        if a.pct_change:
            stock_performance[a.symbol]["pct_changes"].append(a.pct_change)
    
    # 补充股票名称
    for symbol in stock_performance:
        w = db.execute(select(Watchlist).where(Watchlist.symbol == symbol)).scalar_one_or_none()
        if w:
            stock_performance[symbol]["name"] = w.name
    
    # 计算每只股票的综合表现
    for data in stock_performance.values():
        data["avg_score"] = sum(data["scores"]) / len(data["scores"])
        data["total_return"] = sum(data["pct_changes"]) if data["pct_changes"] else 0
    
    sorted_by_score = sorted(stock_performance.values(), key=lambda x: x["avg_score"], reverse=True)
    top_performers = [
        {"symbol": s["symbol"], "name": s["name"], "avg_score": round(s["avg_score"], 1), "total_return": round(s["total_return"], 2)}
        for s in sorted_by_score[:5]
    ]
    worst_performers = [
        {"symbol": s["symbol"], "name": s["name"], "avg_score": round(s["avg_score"], 1), "total_return": round(s["total_return"], 2)}
        for s in sorted_by_score[-5:]
    ]
    
    # 行业表现分析
    sector_data = {}
    for a in analyses:
        w = db.execute(select(Watchlist).where(Watchlist.symbol == a.symbol)).scalar_one_or_none()
        sector = w.sector if w and w.sector else "未分类"
        if sector not in sector_data:
            sector_data[sector] = {"scores": [], "count": 0}
        sector_data[sector]["scores"].append(a.total_score or 50)
        sector_data[sector]["count"] += 1
    
    sector_performance = {
        sector: {
            "avg_score": round(sum(data["scores"]) / len(data["scores"]), 1),
            "stock_count": data["count"] // trading_days if trading_days else 0
        }
        for sector, data in sector_data.items()
    }
    
    # 生成综合分析文本
    comprehensive_analysis = _generate_period_analysis(
        period_name, start_date, end_date, trading_days, 
        avg_score, score_change, market_trend,
        buy_signals, sell_signals, top_performers, worst_performers
    )
    
    # 关键洞察
    key_insights = []
    if market_trend == "上升":
        key_insights.append(f"{period_name}整体市场情绪偏多，平均评分上升 {abs(score_change):.1f} 分")
    elif market_trend == "下降":
        key_insights.append(f"{period_name}整体市场情绪偏空，平均评分下降 {abs(score_change):.1f} 分")
    
    if buy_signals > sell_signals * 2:
        key_insights.append(f"买入信号明显多于卖出信号，比例 {buy_signals}:{sell_signals}")
    elif sell_signals > buy_signals * 2:
        key_insights.append(f"卖出信号明显多于买入信号，比例 {sell_signals}:{buy_signals}")
    
    if top_performers:
        key_insights.append(f"表现最佳: {top_performers[0]['name'] or top_performers[0]['symbol']} (评分 {top_performers[0]['avg_score']})")
    
    # 风险警告
    risk_warnings = []
    if avg_score < 45:
        risk_warnings.append("整体市场评分偏低，建议谨慎操作")
    if sell_signals > buy_signals:
        risk_warnings.append("卖出信号多于买入信号，注意防范风险")
    
    return PeriodReportResponse(
        period_type=period_type.value,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        total_trading_days=trading_days,
        market_trend=market_trend,
        avg_score=round(avg_score, 1),
        score_change=round(score_change, 1),
        buy_signals_count=buy_signals,
        sell_signals_count=sell_signals,
        top_performers=top_performers,
        worst_performers=worst_performers,
        sector_performance=sector_performance,
        comprehensive_analysis=comprehensive_analysis,
        key_insights=key_insights,
        risk_warnings=risk_warnings,
        generated_at=datetime.utcnow().isoformat()
    )


def _generate_period_analysis(
    period_name: str, start_date: date, end_date: date, trading_days: int,
    avg_score: float, score_change: float, market_trend: str,
    buy_signals: int, sell_signals: int,
    top_performers: List[dict], worst_performers: List[dict]
) -> str:
    """生成阶段性分析文本"""
    
    lines = []
    lines.append(f"## {period_name}行情总结")
    lines.append(f"")
    lines.append(f"**统计周期**: {start_date} 至 {end_date} ({trading_days}个交易日)")
    lines.append(f"")
    lines.append(f"### 市场概览")
    lines.append(f"- 整体趋势: {market_trend}")
    lines.append(f"- 平均评分: {avg_score:.1f} 分")
    lines.append(f"- 评分变化: {'+' if score_change >= 0 else ''}{score_change:.1f} 分")
    lines.append(f"")
    lines.append(f"### 信号统计")
    lines.append(f"- 买入信号: {buy_signals} 次")
    lines.append(f"- 卖出信号: {sell_signals} 次")
    lines.append(f"- 信号比: {buy_signals}:{sell_signals}")
    lines.append(f"")
    
    if top_performers:
        lines.append(f"### 表现最佳")
        for i, p in enumerate(top_performers[:3], 1):
            name = p.get('name') or p['symbol']
            lines.append(f"{i}. {name} - 评分 {p['avg_score']}，累计涨幅 {p['total_return']:.2f}%")
        lines.append(f"")
    
    if worst_performers:
        lines.append(f"### 表现最弱")
        for i, p in enumerate(worst_performers[:3], 1):
            name = p.get('name') or p['symbol']
            lines.append(f"{i}. {name} - 评分 {p['avg_score']}，累计涨幅 {p['total_return']:.2f}%")
    
    return "\n".join(lines)
