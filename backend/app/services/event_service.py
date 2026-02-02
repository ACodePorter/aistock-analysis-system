"""
事件抽取与管理服务

职责：
1. 规则/LLM事件抽取
2. 事件结构化（type/date/entities/evidence）
3. 事件合并与置信度计算
4. 事件去重
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from datetime import date, datetime

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..core.models import Event, NewsArticle
from ..core.constants import (
    EventTypeEnum, SourceLevelEnum, SOURCE_LEVEL_WEIGHTS,
    EVENT_MERGE_RULES, EVENT_ID_PREFIX, DEFAULT_CONFIDENCE_SCORE
)

logger = logging.getLogger(__name__)


class EventService:
    """事件抽取和管理服务"""
    
    def __init__(self):
        """初始化"""
        # 事件类型关键词映射
        self.event_type_keywords = {
            EventTypeEnum.EARNINGS.value: ["业绩", "净利润", "营收", "盈利", "亏损", "财报", "年报", "季报"],
            EventTypeEnum.BUYBACK.value: ["回购", "股份回购", "注销"],
            EventTypeEnum.PENALTY.value: ["处罚", "罚款", "违规", "警告", "立案调查"],
            EventTypeEnum.MERGER.value: ["并购", "收购", "重组", "合并"],
            EventTypeEnum.CONTRACT.value: ["合同", "订单", "中标", "签约"],
            EventTypeEnum.RISK_ALERT.value: ["风险", "ST", "*ST", "退市", "暂停上市"],
            EventTypeEnum.LITIGATION.value: ["诉讼", "仲裁", "起诉", "被诉"],
            EventTypeEnum.ANNOUNCEMENT.value: ["公告", "披露", "通知"],
        }
    
    def _generate_event_id(self) -> str:
        """生成事件ID"""
        return f"{EVENT_ID_PREFIX}{uuid.uuid4().hex[:16]}"
    
    def _detect_event_type(self, text: str) -> str:
        """基于关键词检测事件类型"""
        text_lower = text.lower()
        
        for event_type, keywords in self.event_type_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return event_type
        
        return EventTypeEnum.ANNOUNCEMENT.value
    
    def _extract_entities(self, text: str, symbol: str) -> Dict[str, Any]:
        """从文本提取实体（简化版）"""
        import re
        
        entities = {
            "symbol": symbol,
            "amounts": [],
            "dates": [],
            "organizations": []
        }
        
        # 提取金额
        amount_pattern = r'(\d+(?:\.\d+)?)\s*(万元|亿元|元|万|亿)'
        amounts = re.findall(amount_pattern, text)
        if amounts:
            entities["amounts"] = [{"value": a[0], "unit": a[1]} for a in amounts[:5]]
        
        # 提取日期
        date_pattern = r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?'
        dates = re.findall(date_pattern, text)
        if dates:
            entities["dates"] = [f"{d[0]}-{d[1].zfill(2)}-{d[2].zfill(2)}" for d in dates[:3]]
        
        return entities
    
    def calculate_confidence(self, event: dict) -> float:
        """
        计算事件置信度
        
        考虑：
        - 信源等级权重
        - 多源一致性
        - 内容质量
        """
        base_confidence = DEFAULT_CONFIDENCE_SCORE
        
        # 信源等级加权
        source_level = event.get("source_level", "L2")
        level_weight = SOURCE_LEVEL_WEIGHTS.get(source_level, 0.5)
        
        # 证据数量加权
        evidence = event.get("evidence", [])
        evidence_count = len(evidence) if isinstance(evidence, list) else 0
        evidence_bonus = min(0.2, evidence_count * 0.05)  # 最多+0.2
        
        # 内容质量加权（基于摘要长度）
        summary = event.get("summary", "")
        quality_bonus = min(0.1, len(summary) / 500 * 0.1)  # 最多+0.1
        
        confidence = base_confidence * level_weight + evidence_bonus + quality_bonus
        return min(1.0, max(0.0, confidence))
    
    async def extract_event_from_article(self, article_id: int, db: Optional[Session] = None) -> Optional[dict]:
        """
        从单篇文章抽取事件
        
        Returns:
            {
                "event_id": "evt_xxx",
                "symbol": "600519.SH",
                "event_type": "earnings",
                "event_date": "2026-02-01",
                "summary": "...",
                "entities": {...},
                "evidence": [...],
                "confidence": 0.85,
            }
        """
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            # 获取文章
            article = db.execute(
                select(NewsArticle).where(NewsArticle.id == article_id)
            ).scalar_one_or_none()
            
            if not article:
                logger.warning(f"Article {article_id} not found")
                return None
            
            # 提取文本
            text = f"{article.title or ''} {article.content or ''}"
            if len(text.strip()) < 50:
                logger.warning(f"Article {article_id} too short for event extraction")
                return None
            
            # 检测事件类型
            event_type = self._detect_event_type(text)
            
            # 提取实体
            symbols = article.related_stocks or []
            primary_symbol = symbols[0] if symbols else None
            
            if not primary_symbol:
                logger.warning(f"Article {article_id} has no related stocks")
                return None
            
            entities = self._extract_entities(text, primary_symbol)
            
            # 构建事件
            event_data = {
                "event_id": self._generate_event_id(),
                "symbol": primary_symbol,
                "event_type": event_type,
                "event_date": (article.published_at or datetime.utcnow()).date().isoformat(),
                "summary": (article.summary or article.title or "")[:500],
                "description": article.content[:1000] if article.content else None,
                "source_level": "L2",  # 默认财经媒体
                "entities": entities,
                "evidence": [{"article_id": article_id, "url": article.url, "title": article.title}],
            }
            
            # 计算置信度
            event_data["confidence"] = self.calculate_confidence(event_data)
            
            return event_data
            
        finally:
            if close_session:
                db.close()
    
    async def extract_batch(self, article_ids: List[int]) -> List[dict]:
        """批量抽取事件"""
        events = []
        for article_id in article_ids:
            event = await self.extract_event_from_article(article_id)
            if event:
                events.append(event)
        return events
    
    def merge_events(self, events: List[dict]) -> List[dict]:
        """
        合并相同/相似事件
        
        规则：
        - 同股票+同事件类型+时间窗内 -> 合并
        - 多源确认 -> 提升置信度
        """
        if not events:
            return []
        
        merge_rules = EVENT_MERGE_RULES
        time_window = merge_rules.get("same_symbol_and_type", {}).get("time_window_days", 3)
        confidence_boost = merge_rules.get("same_symbol_and_type", {}).get("confidence_boost", 0.1)
        
        merged = []
        used_indices = set()
        
        for i, event in enumerate(events):
            if i in used_indices:
                continue
            
            # 寻找可合并的事件
            group = [event]
            event_date = datetime.fromisoformat(event["event_date"]).date() if isinstance(event["event_date"], str) else event["event_date"]
            
            for j, other in enumerate(events[i+1:], start=i+1):
                if j in used_indices:
                    continue
                
                other_date = datetime.fromisoformat(other["event_date"]).date() if isinstance(other["event_date"], str) else other["event_date"]
                
                # 检查合并条件
                if (event["symbol"] == other["symbol"] and
                    event["event_type"] == other["event_type"] and
                    abs((event_date - other_date).days) <= time_window):
                    group.append(other)
                    used_indices.add(j)
            
            # 合并组内事件
            if len(group) == 1:
                merged.append(event)
            else:
                merged_event = self._merge_event_group(group, confidence_boost)
                merged.append(merged_event)
            
            used_indices.add(i)
        
        return merged
    
    def _merge_event_group(self, group: List[dict], confidence_boost: float) -> dict:
        """合并一组事件"""
        # 取最早日期
        dates = [datetime.fromisoformat(e["event_date"]).date() if isinstance(e["event_date"], str) else e["event_date"] for e in group]
        earliest_date = min(dates)
        
        # 合并证据
        all_evidence = []
        for e in group:
            evidence = e.get("evidence", [])
            if isinstance(evidence, list):
                all_evidence.extend(evidence)
        
        # 合并实体
        all_entities = group[0].get("entities", {}).copy()
        
        # 取最长摘要
        longest_summary = max(group, key=lambda e: len(e.get("summary", "")))["summary"]
        
        # 计算合并后置信度
        max_confidence = max(e.get("confidence", 0.5) for e in group)
        merged_confidence = min(1.0, max_confidence + confidence_boost * (len(group) - 1))
        
        return {
            "event_id": group[0]["event_id"],
            "symbol": group[0]["symbol"],
            "event_type": group[0]["event_type"],
            "event_date": earliest_date.isoformat(),
            "summary": longest_summary,
            "description": group[0].get("description"),
            "source_level": group[0].get("source_level", "L2"),
            "entities": all_entities,
            "evidence": all_evidence,
            "confidence": merged_confidence,
            "merged_count": len(group)
        }
    
    async def create_event(self, event_data: dict, db: Optional[Session] = None) -> str:
        """
        创建新事件，返回event_id
        """
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            event = Event(
                event_id=event_data.get("event_id") or self._generate_event_id(),
                symbol=event_data["symbol"],
                event_type=event_data["event_type"],
                event_date=datetime.fromisoformat(event_data["event_date"]).date() if isinstance(event_data["event_date"], str) else event_data["event_date"],
                source_level=event_data.get("source_level", "L2"),
                confidence=event_data.get("confidence", DEFAULT_CONFIDENCE_SCORE),
                summary=event_data["summary"],
                description=event_data.get("description"),
                entities=event_data.get("entities"),
                evidence=event_data.get("evidence"),
            )
            
            db.add(event)
            db.commit()
            
            logger.info(f"Created event {event.event_id} for {event.symbol}")
            return event.event_id
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create event: {e}")
            raise
        finally:
            if close_session:
                db.close()
    
    def get_event_by_id(self, event_id: str, db: Optional[Session] = None) -> Optional[dict]:
        """获取事件详情"""
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            event = db.execute(
                select(Event).where(Event.event_id == event_id)
            ).scalar_one_or_none()
            
            if not event:
                return None
            
            return {
                "event_id": event.event_id,
                "symbol": event.symbol,
                "event_type": event.event_type,
                "event_date": event.event_date.isoformat(),
                "source_level": event.source_level,
                "confidence": event.confidence,
                "summary": event.summary,
                "description": event.description,
                "entities": event.entities,
                "evidence": event.evidence,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
        finally:
            if close_session:
                db.close()
    
    def list_events_by_symbol(self, symbol: str, start_date: Optional[date] = None,
                            end_date: Optional[date] = None, db: Optional[Session] = None) -> List[dict]:
        """列出某股票的事件"""
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True
        
        try:
            query = select(Event).where(Event.symbol == symbol)
            
            if start_date:
                query = query.where(Event.event_date >= start_date)
            if end_date:
                query = query.where(Event.event_date <= end_date)
            
            query = query.order_by(Event.event_date.desc())
            
            results = db.execute(query).scalars().all()
            
            return [
                {
                    "event_id": e.event_id,
                    "symbol": e.symbol,
                    "event_type": e.event_type,
                    "event_date": e.event_date.isoformat(),
                    "source_level": e.source_level,
                    "confidence": e.confidence,
                    "summary": e.summary,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in results
            ]
        finally:
            if close_session:
                db.close()

