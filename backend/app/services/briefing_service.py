"""
简报生成服务

职责：
1. 日报/周报生成
2. 风险概括、趋势识别
3. 置信度加权摘要
4. LLM调用管理
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..core.models import Briefing, Event, Watchlist
from ..core.constants import (
    BriefingPeriodEnum, BRIEFING_CONFIG, BRIEFING_PROMPTS,
    DEFAULT_CONFIDENCE_SCORE, SOURCE_LEVEL_WEIGHTS
)

logger = logging.getLogger(__name__)


class BriefingService:
    """简报生成服务"""
    
    def __init__(self):
        """初始化"""
        self.config = BRIEFING_CONFIG
        self.prompts = BRIEFING_PROMPTS
        
    def _generate_briefing_id(self, symbol: str, period: str, period_date: date) -> str:
        """生成简报ID"""
        return f"brf_{symbol}_{period}_{period_date.strftime('%Y%m%d')}"
    
    def _get_period_events(self, symbol: str, period: str, period_date: date, 
                          db: Session) -> List[Event]:
        """获取指定周期的事件"""
        if period == BriefingPeriodEnum.DAILY.value:
            start_date = period_date
            end_date = period_date
        elif period == BriefingPeriodEnum.WEEKLY.value:
            # 周报：从period_date往前7天
            end_date = period_date
            start_date = period_date - timedelta(days=6)
        else:
            start_date = period_date
            end_date = period_date
        
        query = select(Event).where(
            and_(
                Event.symbol == symbol,
                Event.event_date >= start_date,
                Event.event_date <= end_date
            )
        ).order_by(Event.confidence.desc(), Event.event_date.desc())
        
        return list(db.execute(query).scalars().all())
    
    def _calculate_risk_level(self, events: List[Event]) -> str:
        """计算风险等级"""
        if not events:
            return "low"
        
        # 风险相关事件类型
        risk_event_types = {"penalty", "risk_alert", "litigation"}
        risk_events = [e for e in events if e.event_type in risk_event_types]
        
        # 高置信度风险事件
        high_confidence_risks = [e for e in risk_events if e.confidence >= 0.8]
        
        if len(high_confidence_risks) >= 2:
            return "high"
        elif len(high_confidence_risks) == 1 or len(risk_events) >= 2:
            return "medium"
        else:
            return "low"
    
    def _summarize_events(self, events: List[Event]) -> str:
        """生成事件摘要（置信度加权）"""
        if not events:
            return "本期无重要事件。"
        
        # 按置信度排序
        sorted_events = sorted(events, key=lambda e: e.confidence, reverse=True)
        
        # 取top事件生成摘要
        max_events = self.config.get("max_events_in_summary", 5)
        top_events = sorted_events[:max_events]
        
        summaries = []
        for e in top_events:
            confidence_label = "高可信" if e.confidence >= 0.8 else "中可信" if e.confidence >= 0.6 else "待确认"
            summaries.append(f"• [{e.event_type}] {e.summary} ({confidence_label})")
        
        return "\n".join(summaries)
    
    def _identify_trends(self, events: List[Event]) -> Dict[str, Any]:
        """识别趋势"""
        if not events:
            return {"trend": "neutral", "signals": []}
        
        trends = {
            "positive": [],
            "negative": [],
            "neutral": []
        }
        
        # 正面信号
        positive_types = {"earnings", "contract", "buyback"}
        # 负面信号
        negative_types = {"penalty", "risk_alert", "litigation"}
        
        for e in events:
            if e.event_type in positive_types and e.confidence >= 0.6:
                trends["positive"].append(e.summary[:50])
            elif e.event_type in negative_types and e.confidence >= 0.6:
                trends["negative"].append(e.summary[:50])
            else:
                trends["neutral"].append(e.summary[:50])
        
        # 判断整体趋势
        if len(trends["positive"]) > len(trends["negative"]) * 2:
            overall_trend = "positive"
        elif len(trends["negative"]) > len(trends["positive"]) * 2:
            overall_trend = "negative"
        else:
            overall_trend = "neutral"
        
        return {
            "trend": overall_trend,
            "signals": {
                "positive": trends["positive"][:3],
                "negative": trends["negative"][:3],
            }
        }
    
    async def generate_briefing(self, symbol: str, period: str, period_date: date,
                               db: Optional[Session] = None) -> dict:
        """
        生成某股票某周期的简报
        
        Returns:
            {
                "briefing_id": "brf_xxx",
                "symbol": "600519.SH",
                "period": "daily",
                "period_date": "2026-02-01",
                "risk_summary": "...",
                "event_highlights": [...],
                "trend_outlook": {...},
                "confidence_avg": 0.82
            }
        """
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            # 获取事件
            events = self._get_period_events(symbol, period, period_date, db)
            
            # 计算风险等级
            risk_level = self._calculate_risk_level(events)
            
            # 生成摘要
            summary = self._summarize_events(events)
            
            # 识别趋势
            trends = self._identify_trends(events)
            
            # 计算平均置信度
            confidence_avg = sum(e.confidence for e in events) / len(events) if events else 0.5
            
            # 构建事件亮点
            event_highlights = []
            for e in events[:10]:
                event_highlights.append({
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "summary": e.summary,
                    "confidence": e.confidence
                })
            
            briefing_data = {
                "briefing_id": self._generate_briefing_id(symbol, period, period_date),
                "symbol": symbol,
                "period": period,
                "period_date": period_date.isoformat(),
                "risk_summary": f"风险等级: {risk_level}\n\n{summary}",
                "event_highlights": event_highlights,
                "trend_outlook": trends,
                "confidence_avg": round(confidence_avg, 3),
                "total_events": len(events)
            }
            
            return briefing_data
            
        finally:
            if close_session:
                db.close()
    
    async def save_briefing(self, briefing_data: dict, db: Optional[Session] = None) -> str:
        """保存简报到数据库"""
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            # 检查是否已存在
            existing = db.execute(
                select(Briefing).where(Briefing.briefing_id == briefing_data["briefing_id"])
            ).scalar_one_or_none()
            
            if existing:
                # 更新
                existing.risk_summary = briefing_data["risk_summary"]
                existing.event_highlights = briefing_data["event_highlights"]
                existing.trend_outlook = briefing_data["trend_outlook"]
                existing.confidence_avg = briefing_data["confidence_avg"]
                existing.updated_at = datetime.utcnow()
                db.commit()
                logger.info(f"Updated briefing {existing.briefing_id}")
                return existing.briefing_id
            else:
                # 创建
                briefing = Briefing(
                    briefing_id=briefing_data["briefing_id"],
                    symbol=briefing_data["symbol"],
                    period=briefing_data["period"],
                    period_date=datetime.fromisoformat(briefing_data["period_date"]).date() if isinstance(briefing_data["period_date"], str) else briefing_data["period_date"],
                    risk_summary=briefing_data["risk_summary"],
                    event_highlights=briefing_data["event_highlights"],
                    trend_outlook=briefing_data["trend_outlook"],
                    confidence_avg=briefing_data["confidence_avg"],
                )
                db.add(briefing)
                db.commit()
                logger.info(f"Created briefing {briefing.briefing_id}")
                return briefing.briefing_id
                
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to save briefing: {e}")
            raise
        finally:
            if close_session:
                db.close()
    
    async def generate_and_save_daily(self, symbol: str, target_date: date = None,
                                     db: Optional[Session] = None) -> str:
        """生成并保存日报"""
        if target_date is None:
            target_date = date.today()
        
        briefing_data = await self.generate_briefing(
            symbol=symbol,
            period=BriefingPeriodEnum.DAILY.value,
            period_date=target_date,
            db=db
        )
        
        return await self.save_briefing(briefing_data, db)
    
    async def generate_and_save_weekly(self, symbol: str, week_end_date: date = None,
                                      db: Optional[Session] = None) -> str:
        """生成并保存周报"""
        if week_end_date is None:
            week_end_date = date.today()
        
        briefing_data = await self.generate_briefing(
            symbol=symbol,
            period=BriefingPeriodEnum.WEEKLY.value,
            period_date=week_end_date,
            db=db
        )
        
        return await self.save_briefing(briefing_data, db)
    
    def get_briefing_by_id(self, briefing_id: str, db: Optional[Session] = None) -> Optional[dict]:
        """获取简报详情"""
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            briefing = db.execute(
                select(Briefing).where(Briefing.briefing_id == briefing_id)
            ).scalar_one_or_none()
            
            if not briefing:
                return None
            
            return {
                "briefing_id": briefing.briefing_id,
                "symbol": briefing.symbol,
                "period": briefing.period,
                "period_date": briefing.period_date.isoformat(),
                "risk_summary": briefing.risk_summary,
                "event_highlights": briefing.event_highlights,
                "trend_outlook": briefing.trend_outlook,
                "confidence_avg": briefing.confidence_avg,
                "created_at": briefing.created_at.isoformat() if briefing.created_at else None,
                "updated_at": briefing.updated_at.isoformat() if briefing.updated_at else None,
            }
        finally:
            if close_session:
                db.close()
    
    def list_briefings_by_symbol(self, symbol: str, period: Optional[str] = None,
                                limit: int = 30, db: Optional[Session] = None) -> List[dict]:
        """列出某股票的简报"""
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            query = select(Briefing).where(Briefing.symbol == symbol)
            
            if period:
                query = query.where(Briefing.period == period)
            
            query = query.order_by(Briefing.period_date.desc()).limit(limit)
            
            results = db.execute(query).scalars().all()
            
            return [
                {
                    "briefing_id": b.briefing_id,
                    "symbol": b.symbol,
                    "period": b.period,
                    "period_date": b.period_date.isoformat(),
                    "confidence_avg": b.confidence_avg,
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                }
                for b in results
            ]
        finally:
            if close_session:
                db.close()

