"""
事件驱动新闻集成模块

负责：
1. 监听新闻更新事件
2. 当出现重大新闻时触发模型重训练
3. 新闻情绪突变检测
4. 与现有 news_service 集成

触发条件：
- 单日新闻情绪偏离均值超过 2 倍标准差
- 出现标记为"重大事件"的新闻
- 单日新闻数量异常（超过正常水平 3 倍）
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from ...core.models import NewsArticle
from ..model_engine.trainer import TrainingOrchestrator

logger = logging.getLogger(__name__)

# 事件驱动阈值
SENTIMENT_Z_THRESHOLD = 2.0     # 情绪 z-score 阈值
NEWS_VOLUME_MULTIPLIER = 3.0    # 新闻数量异常倍数
LOOKBACK_DAYS = 30              # 均值/标准差回溯天数


class NewsEventTrigger:
    """新闻事件触发器

    用法：
        trigger = NewsEventTrigger(session)
        triggered = trigger.check_and_trigger("600519.SH")
        triggered_all = trigger.check_all()
    """

    def __init__(self, session: Session):
        self.session = session
        self.orchestrator = TrainingOrchestrator(session)

    def check_and_trigger(self, symbol: str) -> Optional[dict]:
        """检查单只股票的新闻事件，必要时触发重训练

        Returns:
            触发信息字典，未触发则返回 None
        """
        today = date.today()
        reasons = []

        # 检查情绪突变
        sentiment_spike = self._check_sentiment_spike(symbol, today)
        if sentiment_spike:
            reasons.append(f"sentiment_spike: z={sentiment_spike:.2f}")

        # 检查新闻数量异常
        volume_spike = self._check_volume_spike(symbol, today)
        if volume_spike:
            reasons.append(f"volume_spike: ratio={volume_spike:.1f}")

        # 检查重大事件
        has_major = self._check_major_event(symbol, today)
        if has_major:
            reasons.append("major_event_detected")

        if not reasons:
            return None

        # 触发重训练
        reason_str = "; ".join(reasons)
        logger.info("事件触发重训练: symbol=%s, reasons=%s", symbol, reason_str)

        result = self.orchestrator.trigger_retrain(
            symbol=symbol,
            reason=reason_str,
        )

        return {
            "symbol": symbol,
            "triggered": True,
            "reasons": reasons,
            "retrain_result": result,
        }

    def check_all(self) -> list[dict]:
        """检查所有观察列表股票的事件"""
        from ..data_layer.market_data import get_watchlist_symbols

        symbols = get_watchlist_symbols(self.session)
        triggered = []

        for symbol in symbols:
            result = self.check_and_trigger(symbol)
            if result:
                triggered.append(result)

        if triggered:
            logger.info("事件驱动触发: %d 只股票需要重训练", len(triggered))

        return triggered

    def _check_sentiment_spike(self, symbol: str, check_date: date) -> Optional[float]:
        """检查情绪突变（z-score 超过阈值）"""
        from ..data_layer.news_data import load_news_sentiment

        start = check_date - timedelta(days=LOOKBACK_DAYS)
        df = load_news_sentiment(self.session, symbol, start, check_date)
        if df.empty or len(df) < 5:
            return None

        sentiments = df["avg_sentiment"]
        mean_val = sentiments.iloc[:-1].mean()
        std_val = sentiments.iloc[:-1].std()

        if std_val == 0:
            return None

        latest = sentiments.iloc[-1]
        z_score = abs((latest - mean_val) / std_val)

        if z_score >= SENTIMENT_Z_THRESHOLD:
            return float(z_score)
        return None

    def _check_volume_spike(self, symbol: str, check_date: date) -> Optional[float]:
        """检查新闻数量异常"""
        from ..data_layer.news_data import load_news_sentiment

        start = check_date - timedelta(days=LOOKBACK_DAYS)
        df = load_news_sentiment(self.session, symbol, start, check_date)
        if df.empty or len(df) < 5:
            return None

        volumes = df["news_count"]
        avg_vol = volumes.iloc[:-1].mean()

        if avg_vol == 0:
            return None

        latest_vol = volumes.iloc[-1]
        ratio = latest_vol / avg_vol

        if ratio >= NEWS_VOLUME_MULTIPLIER:
            return float(ratio)
        return None

    def _check_major_event(self, symbol: str, check_date: date) -> bool:
        """检查是否有标记为重大的事件

        从 StockEvent 表或 NewsArticle 的 importance 字段判断
        """
        from ...core.models import StockEvent

        # 检查 StockEvent 表
        event_count = self.session.execute(
            select(func.count(StockEvent.id))
            .where(
                and_(
                    StockEvent.symbol == symbol,
                    StockEvent.event_date == check_date,
                )
            )
        ).scalar() or 0

        return event_count > 0
