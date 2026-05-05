"""
事件驱动因子模块（Event-driven Alpha）

从新闻/公告/事件中提取结构化信号，构建事件驱动特征，增强模型对突发信息的反应能力。

核心功能：
1. 事件检测   — 从 NewsArticle / Event 表识别四大事件类型
2. 关键词提取 — 基于规则的关键词匹配 + 情绪分级
3. 事件特征   — 构建 per-symbol-per-date 的事件因子
4. 融合接口   — 可直接嵌入 FactorEngine 或独立使用
"""

from __future__ import annotations

import datetime
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ===================================================================
# 事件类型定义与关键词词典
# ===================================================================

class EventCategory:
    EARNINGS = "earnings"
    POLICY = "policy"
    INDUSTRY = "industry"
    BREAKING = "breaking"


CATEGORY_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    EventCategory.EARNINGS: {
        "positive": [
            "业绩预增", "净利润增长", "营收大增", "超预期", "盈利增长",
            "利润翻倍", "业绩暴增", "高增长", "扭亏为盈", "业绩超预期",
            "revenue beat", "earnings beat", "profit surge",
        ],
        "negative": [
            "业绩预减", "净利润下降", "业绩不及预期", "亏损", "利润下滑",
            "营收下降", "业绩暴雷", "商誉减值", "计提", "业绩变脸",
            "earnings miss", "profit warning", "revenue decline",
        ],
        "neutral": [
            "财报", "年报", "季报", "半年报", "中报", "业绩快报",
            "业绩预告", "earnings report", "financial results",
        ],
    },
    EventCategory.POLICY: {
        "positive": [
            "政策利好", "减税", "降准", "降息", "补贴", "扶持政策",
            "税收优惠", "政策红利", "政策支持", "松绑", "放开",
            "stimulus", "tax cut", "rate cut",
        ],
        "negative": [
            "政策收紧", "加息", "监管", "反垄断", "罚款", "整治",
            "限制", "叫停", "约谈", "制裁",
            "regulation", "crackdown", "sanction",
        ],
        "neutral": [
            "政策", "法规", "规定", "条例", "指导意见", "通知",
            "policy", "regulation", "guideline",
        ],
    },
    EventCategory.INDUSTRY: {
        "positive": [
            "行业景气", "需求旺盛", "订单激增", "产能扩张", "技术突破",
            "国产替代", "产业升级", "渗透率提升",
            "industry boom", "demand surge",
        ],
        "negative": [
            "行业低迷", "产能过剩", "价格战", "需求疲软", "库存积压",
            "行业寒冬", "竞争加剧",
            "industry downturn", "oversupply",
        ],
        "neutral": [
            "行业", "板块", "产业链", "上下游", "供应链",
            "sector", "industry",
        ],
    },
    EventCategory.BREAKING: {
        "positive": [
            "重大合同", "战略合作", "并购", "回购", "增持",
            "重大订单", "中标", "突破", "获批", "上市",
            "acquisition", "buyback", "partnership",
        ],
        "negative": [
            "黑天鹅", "暴跌", "违规", "立案", "爆雷", "造假",
            "退市", "停牌", "被查", "大股东减持", "质押爆仓",
            "fraud", "delisting", "crash",
        ],
        "neutral": [
            "公告", "变更", "任命", "辞任", "调整",
            "announcement", "change",
        ],
    },
}

IMPACT_WEIGHTS = {
    EventCategory.EARNINGS: 1.0,
    EventCategory.POLICY: 0.8,
    EventCategory.INDUSTRY: 0.6,
    EventCategory.BREAKING: 1.2,
}

SENTIMENT_POLARITY = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


# ===================================================================
# 数据结构
# ===================================================================

@dataclass
class DetectedEvent:
    """单条检测到的事件"""
    symbol: str
    event_date: datetime.date
    category: str
    sentiment: str  # positive / negative / neutral
    sentiment_score: float  # -1 ~ +1
    confidence: float  # 0 ~ 1
    impact_score: float  # 综合影响分
    keywords_matched: List[str] = field(default_factory=list)
    source_title: str = ""
    source_id: Optional[int] = None


@dataclass
class EventFeatureRow:
    """per-symbol-per-date 的事件特征聚合"""
    symbol: str
    trade_date: datetime.date
    # 事件数量
    event_count: int = 0
    earnings_count: int = 0
    policy_count: int = 0
    industry_count: int = 0
    breaking_count: int = 0
    # 情绪
    event_sentiment_avg: float = 0.0
    event_sentiment_max: float = 0.0
    event_sentiment_min: float = 0.0
    event_sentiment_std: float = 0.0
    # 影响分
    event_impact_sum: float = 0.0
    event_impact_max: float = 0.0
    # 极性比例
    positive_ratio: float = 0.0
    negative_ratio: float = 0.0
    # 置信度
    avg_confidence: float = 0.0
    # 突发标记
    has_major_positive: int = 0
    has_major_negative: int = 0
    has_breaking: int = 0


# ===================================================================
# 事件检测器
# ===================================================================

class EventDetector:
    """从新闻文本中检测事件类型和情绪"""

    def __init__(
        self,
        keyword_dict: Optional[Dict] = None,
        min_confidence: float = 0.3,
    ):
        self.keywords = keyword_dict or CATEGORY_KEYWORDS
        self._compile_patterns()
        self.min_confidence = min_confidence

    def _compile_patterns(self):
        """预编译正则模式以提高效率"""
        self._patterns: Dict[str, Dict[str, re.Pattern]] = {}
        for cat, sentiments in self.keywords.items():
            self._patterns[cat] = {}
            for sentiment, words in sentiments.items():
                escaped = [re.escape(w) for w in words]
                pattern = re.compile("|".join(escaped), re.IGNORECASE)
                self._patterns[cat][sentiment] = pattern

    def detect(
        self,
        text: str,
        symbol: str = "",
        event_date: Optional[datetime.date] = None,
        base_sentiment_score: float = 0.0,
        source_title: str = "",
        source_id: Optional[int] = None,
    ) -> List[DetectedEvent]:
        """对单条文本进行事件检测

        Args:
            text:                  新闻标题+内容
            symbol:                关联股票
            event_date:            事件日期
            base_sentiment_score:  原有情绪分（来自 NLP/LLM），用于辅助
            source_title:          新闻标题
            source_id:             新闻ID
        """
        if not text:
            return []

        events = []
        text_lower = text.lower()

        for cat, sentiment_patterns in self._patterns.items():
            best_sentiment = None
            best_score = 0.0
            all_matched = []

            for sentiment, pattern in sentiment_patterns.items():
                matches = pattern.findall(text)
                if matches:
                    polarity = SENTIMENT_POLARITY[sentiment]
                    match_score = len(matches) * abs(polarity)
                    all_matched.extend(matches)
                    if match_score > best_score or (match_score == best_score and sentiment != "neutral"):
                        best_score = match_score
                        best_sentiment = sentiment

            if not all_matched:
                continue

            if best_sentiment is None:
                best_sentiment = "neutral"

            # 综合情绪分
            polarity = SENTIMENT_POLARITY[best_sentiment]
            n_matches = len(all_matched)
            confidence = min(1.0, 0.3 + 0.1 * n_matches)

            if base_sentiment_score != 0:
                final_sentiment = 0.6 * polarity + 0.4 * base_sentiment_score
            else:
                final_sentiment = polarity

            # 影响分 = 情绪强度 × 类别权重 × 匹配数量加成
            impact = abs(final_sentiment) * IMPACT_WEIGHTS.get(cat, 0.5) * min(2.0, 1.0 + 0.2 * n_matches)

            if confidence < self.min_confidence:
                continue

            events.append(DetectedEvent(
                symbol=symbol,
                event_date=event_date or datetime.date.today(),
                category=cat,
                sentiment=best_sentiment,
                sentiment_score=round(final_sentiment, 4),
                confidence=round(confidence, 4),
                impact_score=round(impact, 4),
                keywords_matched=list(set(all_matched))[:10],
                source_title=source_title,
                source_id=source_id,
            ))

        return events


# ===================================================================
# 事件特征构建器
# ===================================================================

class EventFeatureBuilder:
    """将检测到的事件聚合为 per-symbol-per-date 的特征"""

    def aggregate(
        self,
        events: List[DetectedEvent],
    ) -> Dict[Tuple[str, datetime.date], EventFeatureRow]:
        """将事件列表聚合为 {(symbol, date): features}"""
        grouped: Dict[Tuple[str, datetime.date], List[DetectedEvent]] = defaultdict(list)
        for e in events:
            grouped[(e.symbol, e.event_date)].append(e)

        result = {}
        for key, group in grouped.items():
            result[key] = self._aggregate_group(key[0], key[1], group)
        return result

    def _aggregate_group(
        self,
        symbol: str,
        trade_date: datetime.date,
        events: List[DetectedEvent],
    ) -> EventFeatureRow:
        n = len(events)
        sentiments = [e.sentiment_score for e in events]
        impacts = [e.impact_score for e in events]
        confidences = [e.confidence for e in events]

        n_pos = sum(1 for e in events if e.sentiment == "positive")
        n_neg = sum(1 for e in events if e.sentiment == "negative")

        major_pos_threshold = 0.7
        major_neg_threshold = -0.7

        return EventFeatureRow(
            symbol=symbol,
            trade_date=trade_date,
            event_count=n,
            earnings_count=sum(1 for e in events if e.category == EventCategory.EARNINGS),
            policy_count=sum(1 for e in events if e.category == EventCategory.POLICY),
            industry_count=sum(1 for e in events if e.category == EventCategory.INDUSTRY),
            breaking_count=sum(1 for e in events if e.category == EventCategory.BREAKING),
            event_sentiment_avg=float(np.mean(sentiments)) if sentiments else 0.0,
            event_sentiment_max=float(np.max(sentiments)) if sentiments else 0.0,
            event_sentiment_min=float(np.min(sentiments)) if sentiments else 0.0,
            event_sentiment_std=float(np.std(sentiments)) if len(sentiments) > 1 else 0.0,
            event_impact_sum=float(np.sum(impacts)),
            event_impact_max=float(np.max(impacts)) if impacts else 0.0,
            positive_ratio=n_pos / n if n > 0 else 0.0,
            negative_ratio=n_neg / n if n > 0 else 0.0,
            avg_confidence=float(np.mean(confidences)) if confidences else 0.0,
            has_major_positive=1 if any(s > major_pos_threshold for s in sentiments) else 0,
            has_major_negative=1 if any(s < major_neg_threshold for s in sentiments) else 0,
            has_breaking=1 if any(e.category == EventCategory.BREAKING for e in events) else 0,
        )

    def to_dataframe(
        self,
        feature_rows: Dict[Tuple[str, datetime.date], EventFeatureRow],
    ) -> pd.DataFrame:
        """转换为 DataFrame（适合与行情数据 merge）"""
        if not feature_rows:
            return pd.DataFrame()

        records = []
        for (sym, dt), row in feature_rows.items():
            rec = {
                "symbol": row.symbol,
                "trade_date": row.trade_date,
                "event_count": row.event_count,
                "earnings_count": row.earnings_count,
                "policy_count": row.policy_count,
                "industry_count": row.industry_count,
                "breaking_count": row.breaking_count,
                "event_sentiment_avg": row.event_sentiment_avg,
                "event_sentiment_max": row.event_sentiment_max,
                "event_sentiment_min": row.event_sentiment_min,
                "event_sentiment_std": row.event_sentiment_std,
                "event_impact_sum": row.event_impact_sum,
                "event_impact_max": row.event_impact_max,
                "positive_ratio": row.positive_ratio,
                "negative_ratio": row.negative_ratio,
                "avg_confidence": row.avg_confidence,
                "has_major_positive": row.has_major_positive,
                "has_major_negative": row.has_major_negative,
                "has_breaking": row.has_breaking,
            }
            records.append(rec)

        return pd.DataFrame(records)


# ===================================================================
# 事件因子计算（用于 FactorEngine 集成）
# ===================================================================

EVENT_FACTOR_COLUMNS = [
    "event_count", "earnings_count", "policy_count",
    "industry_count", "breaking_count",
    "event_sentiment_avg", "event_sentiment_max",
    "event_sentiment_min", "event_sentiment_std",
    "event_impact_sum", "event_impact_max",
    "positive_ratio", "negative_ratio",
    "avg_confidence",
    "has_major_positive", "has_major_negative", "has_breaking",
]


def compute_event_factors(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """计算事件驱动因子（需要 event_* 列已 merge 到 df 中）

    在此基础上生成衍生时序特征：滚动窗口、累积效应、衰减因子。
    """
    factors: List[str] = []

    # 检查是否已有事件列
    base_cols = [c for c in EVENT_FACTOR_COLUMNS if c in df.columns]
    if not base_cols:
        return df, factors

    factors.extend(base_cols)

    # --- 事件密度（滚动窗口） ---
    if "event_count" in df.columns:
        ec = df["event_count"].astype(float).fillna(0)
        for w in (3, 5, 7, 14):
            col = f"event_density_{w}d"
            df[col] = ec.rolling(w, min_periods=1).sum()
            factors.append(col)

        ec_ma20 = ec.rolling(20, min_periods=5).mean()
        df["event_count_spike"] = ec / (ec_ma20 + 1e-9)
        factors.append("event_count_spike")

    # --- 事件情绪累积与衰减 ---
    if "event_sentiment_avg" in df.columns:
        sent = df["event_sentiment_avg"].astype(float).fillna(0)

        for w in (3, 5, 7):
            col = f"event_sent_{w}d"
            df[col] = sent.rolling(w, min_periods=1).mean()
            factors.append(col)

        # 指数衰减加权（近期事件权重更大）
        df["event_sent_ewm5"] = sent.ewm(span=5, adjust=False).mean()
        df["event_sent_ewm10"] = sent.ewm(span=10, adjust=False).mean()
        factors.extend(["event_sent_ewm5", "event_sent_ewm10"])

        # 情绪动量
        df["event_sent_momentum"] = (
            df.get("event_sent_3d", sent) - df.get("event_sent_7d", sent)
        )
        factors.append("event_sent_momentum")

        # 情绪波动
        df["event_sent_vol_7d"] = sent.rolling(7, min_periods=3).std().fillna(0)
        factors.append("event_sent_vol_7d")

    # --- 影响力衰减 ---
    if "event_impact_sum" in df.columns:
        imp = df["event_impact_sum"].astype(float).fillna(0)
        df["event_impact_ewm5"] = imp.ewm(span=5, adjust=False).mean()
        df["event_impact_3d"] = imp.rolling(3, min_periods=1).sum()
        df["event_impact_7d"] = imp.rolling(7, min_periods=1).sum()
        factors.extend(["event_impact_ewm5", "event_impact_3d", "event_impact_7d"])

    # --- 重大事件累积标记 ---
    if "has_major_positive" in df.columns:
        df["major_pos_3d"] = df["has_major_positive"].rolling(3, min_periods=1).sum()
        df["major_neg_3d"] = df["has_major_negative"].rolling(3, min_periods=1).sum() if "has_major_negative" in df.columns else 0
        df["breaking_3d"] = df["has_breaking"].rolling(3, min_periods=1).sum() if "has_breaking" in df.columns else 0
        factors.extend(["major_pos_3d", "major_neg_3d", "breaking_3d"])

    # --- 事件类型比例 ---
    if "event_count" in df.columns:
        ec_safe = df["event_count"].astype(float).replace(0, np.nan)
        for cat_col in ("earnings_count", "policy_count", "industry_count", "breaking_count"):
            if cat_col in df.columns:
                ratio_col = f"{cat_col}_ratio"
                df[ratio_col] = (df[cat_col].astype(float) / ec_safe).fillna(0)
                factors.append(ratio_col)

    return df, factors


# ===================================================================
# 数据库批量提取事件
# ===================================================================

def extract_events_from_db(
    session,
    symbols: List[str],
    start_date: datetime.date,
    end_date: datetime.date,
    detector: Optional[EventDetector] = None,
) -> Tuple[List[DetectedEvent], pd.DataFrame]:
    """从 NewsArticle + Event 表批量提取事件并构建特征 DataFrame

    Returns:
        events:     所有检测到的事件列表
        event_df:   per-symbol-per-date 的事件特征 DataFrame
    """
    if detector is None:
        detector = EventDetector()
    builder = EventFeatureBuilder()

    all_events: List[DetectedEvent] = []

    try:
        from ...core.models import NewsArticle, Event

        # 1. 从 NewsArticle 提取事件
        articles = (
            session.query(
                NewsArticle.id,
                NewsArticle.title,
                NewsArticle.content,
                NewsArticle.summary,
                NewsArticle.published_at,
                NewsArticle.sentiment_score,
                NewsArticle.related_stocks,
                NewsArticle.keywords,
                NewsArticle.category,
            )
            .filter(
                NewsArticle.published_at >= start_date,
                NewsArticle.published_at <= end_date + datetime.timedelta(days=1),
                NewsArticle.is_duplicate.is_(False),
            )
            .order_by(NewsArticle.published_at.desc())
            .limit(5000)
            .all()
        )

        for art in articles:
            text = f"{art.title or ''} {art.summary or ''} {art.content or ''}"
            pub_date = art.published_at.date() if art.published_at else end_date
            base_sent = float(art.sentiment_score) if art.sentiment_score else 0.0

            related = art.related_stocks or []
            if isinstance(related, str):
                try:
                    import json
                    related = json.loads(related)
                except Exception:
                    related = []

            target_symbols = [s for s in related if s in symbols] if related else symbols[:3]

            for sym in target_symbols:
                detected = detector.detect(
                    text=text,
                    symbol=sym,
                    event_date=pub_date,
                    base_sentiment_score=base_sent,
                    source_title=art.title or "",
                    source_id=art.id,
                )
                all_events.extend(detected)

        # 2. 从 Event 表补充结构化事件
        db_events = (
            session.query(Event)
            .filter(
                Event.symbol.in_(symbols),
                Event.event_date >= start_date,
                Event.event_date <= end_date,
            )
            .all()
        )

        event_type_to_category = {
            "earnings": EventCategory.EARNINGS,
            "earnings_adjustment": EventCategory.EARNINGS,
            "buyback": EventCategory.BREAKING,
            "penalty": EventCategory.BREAKING,
            "merger": EventCategory.BREAKING,
            "contract": EventCategory.BREAKING,
            "risk_alert": EventCategory.BREAKING,
            "announcement": EventCategory.INDUSTRY,
            "litigation": EventCategory.BREAKING,
            "policy_impact": EventCategory.POLICY,
        }

        for ev in db_events:
            cat = event_type_to_category.get(ev.event_type, EventCategory.INDUSTRY)
            text = f"{ev.summary or ''} {ev.description or ''}"
            detected = detector.detect(
                text=text,
                symbol=ev.symbol,
                event_date=ev.event_date,
                base_sentiment_score=0.0,
                source_title=ev.summary or "",
            )
            if detected:
                all_events.extend(detected)
            else:
                all_events.append(DetectedEvent(
                    symbol=ev.symbol,
                    event_date=ev.event_date,
                    category=cat,
                    sentiment="neutral",
                    sentiment_score=0.0,
                    confidence=float(ev.confidence) if ev.confidence else 0.5,
                    impact_score=IMPACT_WEIGHTS.get(cat, 0.5) * 0.5,
                    keywords_matched=[ev.event_type],
                    source_title=ev.summary or "",
                ))

        logger.info(
            "Extracted %d events from %d articles + %d DB events for %d symbols",
            len(all_events), len(articles), len(db_events), len(symbols),
        )

    except Exception as e:
        logger.warning("Event extraction from DB failed: %s", e)

    # 构建特征
    feature_rows = builder.aggregate(all_events)
    event_df = builder.to_dataframe(feature_rows)

    return all_events, event_df


def build_event_features_for_symbol(
    session,
    symbol: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> pd.DataFrame:
    """为单只股票构建事件特征（可直接 merge 到行情 DataFrame）"""
    _, event_df = extract_events_from_db(
        session=session,
        symbols=[symbol],
        start_date=start_date,
        end_date=end_date,
    )
    if event_df.empty:
        return pd.DataFrame()

    event_df = event_df[event_df["symbol"] == symbol].drop(columns=["symbol"], errors="ignore")
    return event_df
