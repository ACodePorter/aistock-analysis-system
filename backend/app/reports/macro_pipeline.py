"""Macro news observation and daily learning pipeline.

This module orchestrates a daily workflow that:
- collects macro-level news topics from multiple keyword buckets
- performs content crawling and LLM-driven analysis
- aggregates sentiment/keywords/features into a long-term observation store
- prepares feature vectors for regression/forecast models

The implementation intentionally keeps each stage modular so that pieces can be
replaced by more advanced components (e.g. dedicated feature store, AutoML
service, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, date, UTC
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..news.llm_processor import LLMNewsProcessor, NewsAnalysisResult
from ..utils.mongo_storage import get_storage, StockNewsStorage
from ..news.news_crawler import NewsContentCrawler
from ..news.news_service import NewsSearchService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MacroTopic:
    name: str
    queries: List[str]
    weight: float = 1.0
    description: str | None = None
    related_indices: List[str] | None = None

    def normalized_name(self) -> str:
        return self.name.strip().lower()


@dataclass(slots=True)
class MacroObservation:
    topic: str
    observation_date: date
    article_count: int
    features: Dict[str, Any]
    top_keywords: List[str]
    top_entities: Dict[str, List[str]]
    summaries: List[str]
    references: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["observation_date"] = self.observation_date.isoformat()
        topic_slug = self.topic.lower().replace(" ", "_")
        payload["topic_display"] = self.topic
        payload["topic"] = topic_slug
        payload.setdefault("created_at", datetime.now(UTC))
        payload.setdefault("updated_at", datetime.now(UTC))
        return payload


@dataclass(slots=True)
class MacroPipelineResult:
    observations: List[MacroObservation]
    started_at: datetime
    finished_at: datetime
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "errors": self.errors,
            "observations": [obs.to_dict() for obs in self.observations],
        }


DEFAULT_TOPICS: Sequence[MacroTopic] = (
    MacroTopic(
        name="Global Macro",
        description="Worldwide macroeconomic overview: PMI, inflation, growth guidance",
        weight=1.2,
        queries=[
            "全球 宏观 经济 数据", "全球 PMI 数据", "全球 通胀 数据", "全球 经济 前景 分析",
            "美联储 利率 决议", "欧央行 货币政策", "全球 GDP 增长", "国际 金融 市场 动态",
        ],
        related_indices=["SP500", "HSI", "SSE"],
    ),
    MacroTopic(
        name="China Policy",
        description="Domestic policy, fiscal and monetary measures",
        weight=1.1,
        queries=[
            "中国 宏观 政策", "财政政策 发布", "货币政策 调整", "国务院 常务会议 内容",
            "央行 公开市场 操作", "中国经济 数据 发布", "中国 制造业 PMI", "国内 经济 形势 分析",
        ],
        related_indices=["CSI300", "CN10Y"],
    ),
    MacroTopic(
        name="Property and Urban",
        description="Real estate regulations and urban development initiatives",
        weight=1.0,
        queries=[
            "房地产 市场 政策", "住房信贷 新政", "保障房 进展", "城市 更新 规划",
            "楼市 成交 数据", "土地 出让 信息", "房贷 利率 调整", "房地产 调控 措施",
        ],
        related_indices=["CSIRealty"],
    ),
    MacroTopic(
        name="Technology and Innovation",
        description="Cutting-edge technology, AI, semiconductor and innovation policies",
        weight=1.0,
        queries=[
            "人工智能 产业 政策", "半导体 行业 新闻", "科技 创新 发布", "数字经济 规划",
            "芯片 国产化 进展", "新能源汽车 产业 动态", "科技 投融资 动态", "AI 人工智能 最新进展",
        ],
        related_indices=["Nasdaq100", "STAR50"],
    ),
    MacroTopic(
        name="Energy and Commodities",
        description="Energy supply-demand, commodity price movements, carbon transition",
        weight=0.9,
        queries=[
            "能源 市场 动态", "大宗商品 价格", "原油 供给", "新能源 政策", "碳 中和 举措",
            "黄金 价格 走势", "天然气 供需", "有色金属 市场 行情",
        ],
        related_indices=["Brent", "LMEIndex"],
    ),
)


class MacroNewsPipeline:
    """High-level orchestration for macro news observation and learning."""

    def __init__(
        self,
        topics: Optional[Sequence[MacroTopic]] = None,
        storage: Optional[StockNewsStorage] = None,
        *,
        time_range: str | None = None,
        max_articles_per_topic: Optional[int] = None,
        crawl_concurrency: Optional[int] = None,
    ) -> None:
        self.topics: Sequence[MacroTopic] = topics or DEFAULT_TOPICS
        self._storage = storage
        self.search_service = NewsSearchService()
        self.time_range = time_range or os.getenv("MACRO_NEWS_TIME_RANGE", "week")
        self.max_articles_per_topic = max_articles_per_topic or int(os.getenv("MACRO_MAX_ARTICLES", "20"))
        self.crawl_concurrency = crawl_concurrency or int(os.getenv("MACRO_CRAWL_CONCURRENCY", "4"))
        self.min_relevance_threshold = float(os.getenv("MACRO_MIN_RELEVANCE", "0.2"))
        self.max_keywords = int(os.getenv("MACRO_MAX_KEYWORDS", "10"))
        self.max_references = int(os.getenv("MACRO_MAX_REFERENCES", "8"))
        self.sentiment_floor = float(os.getenv("MACRO_SENTIMENT_FLOOR", "-1"))
        self.sentiment_cap = float(os.getenv("MACRO_SENTIMENT_CAP", "1"))

    async def run_daily_pipeline(self, *, for_date: Optional[date] = None) -> MacroPipelineResult:
        started = datetime.now(UTC)
        errors: List[str] = []
        observations: List[MacroObservation] = []
        target_date = for_date or datetime.now(UTC).date()

        logger.info("Starting macro news pipeline for %s", target_date.isoformat())

        storage = self._storage or await get_storage()
        if storage is None:
            logger.warning("MongoDB storage unavailable; observations won't be persisted")

        try:
            async with NewsContentCrawler() as crawler, LLMNewsProcessor() as llm:
                for topic in self.topics:
                    try:
                        observation = await self._process_topic(
                            topic=topic,
                            crawler=crawler,
                            llm=llm,
                            storage=storage,
                            target_date=target_date,
                        )
                        if observation:
                            observations.append(observation)
                    except Exception as topic_error:  # noqa: BLE001
                        message = f"Topic {topic.name} failed: {topic_error}"
                        logger.exception(message)
                        errors.append(message)
        finally:
            finished = datetime.now(UTC)

        logger.info(
            "Macro news pipeline finished with %d observations and %d errors",
            len(observations),
            len(errors),
        )

        return MacroPipelineResult(
            observations=observations,
            started_at=started,
            finished_at=finished,
            errors=errors,
        )

    async def _process_topic(
        self,
        *,
        topic: MacroTopic,
        crawler: NewsContentCrawler,
        llm: LLMNewsProcessor,
        storage: Optional[StockNewsStorage],
        target_date: date,
    ) -> Optional[MacroObservation]:
        search_results = await self._collect_search_results(topic)

        # 回退机制：如果搜索结果太少，用更宽的时间范围重试
        if len(search_results) < 3 and self.time_range not in ("month", "year"):
            fallback_range = "month" if self.time_range == "week" else "week"
            logger.info(
                "Too few results (%d) for topic %s with time_range=%s; retrying with '%s'",
                len(search_results), topic.name, self.time_range, fallback_range,
            )
            wider_results = await self._collect_search_results(topic, time_range_override=fallback_range)
            search_results = self._deduplicate_results(search_results + wider_results)

        if not search_results:
            logger.info("No search results for topic %s", topic.name)
            return None

        deduped = self._deduplicate_results(search_results)
        limited = deduped[: self.max_articles_per_topic]

        crawl_results = await self._crawl_articles(crawler, limited)
        if not crawl_results:
            logger.info("No crawlable articles for topic %s", topic.name)
            return None

        analyses = await self._analyze_articles(llm, crawl_results)
        observation = self._build_observation(topic, target_date, crawl_results, analyses)

        if observation and storage:
            await storage.save_macro_observation(observation.to_dict())

        return observation

    async def _collect_search_results(
        self, topic: MacroTopic, *, time_range_override: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search news for all queries within a topic and merge results."""
        effective_time_range = time_range_override or self.time_range
        aggregated: List[Dict[str, Any]] = []

        for query in topic.queries:
            try:
                results = await self.search_service.search_news(
                    query=query,
                    category="general",
                    time_range=effective_time_range,
                    max_results=self.max_articles_per_topic * 2,
                )
                aggregated.extend(results)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Search failed for query '%s': %s", query, exc)

        return aggregated

    async def _crawl_articles(
        self,
        crawler: NewsContentCrawler,
        search_results: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Fetch article content for search results and merge metadata."""
        url_map = {item.get("url"): item for item in search_results if item.get("url")}
        urls = list(url_map.keys())
        if not urls:
            return []

        raw_results = await crawler.batch_crawl_articles(urls, max_concurrent=self.crawl_concurrency)

        merged: List[Dict[str, Any]] = []
        for raw in raw_results:
            if raw.get("status") != "success":
                continue
            url = raw.get("url")
            base = url_map.get(url, {})
            merged.append({**base, **raw})

        return merged

    async def _analyze_articles(
        self,
        llm: LLMNewsProcessor,
        articles: Sequence[Dict[str, Any]],
    ) -> List[Optional[NewsAnalysisResult]]:
        batches: List[List[Dict[str, Any]]] = []
        batch_size = int(os.getenv("MACRO_ANALYSIS_BATCH", "5"))
        current: List[Dict[str, Any]] = []

        for article in articles:
            payload = {
                "title": article.get("title") or article.get("content", "")[:80],
                "content": article.get("content", ""),
                "url": article.get("url", ""),
            }
            current.append(payload)
            if len(current) >= batch_size:
                batches.append(current)
                current = []

        if current:
            batches.append(current)

        results: List[Optional[NewsAnalysisResult]] = []
        for batch in batches:
            batch_results = await llm.batch_analyze_news(batch)
            results.extend(batch_results)

        # Pad to align length with articles sequence
        if len(results) < len(articles):
            results.extend([None] * (len(articles) - len(results)))

        return results[: len(articles)]

    def _build_observation(
        self,
        topic: MacroTopic,
        target_date: date,
        articles: Sequence[Dict[str, Any]],
        analyses: Sequence[Optional[NewsAnalysisResult]],
    ) -> Optional[MacroObservation]:
        if not articles:
            return None

        sentiment_scores: List[float] = []
        relevance_scores: List[float] = []
        quality_scores: List[float] = []
        sentiment_distribution: Counter[str] = Counter()
        keyword_counter: Counter[str] = Counter()
        company_counter: Counter[str] = Counter()
        location_counter: Counter[str] = Counter()
        people_counter: Counter[str] = Counter()
        summaries: List[str] = []
        references: List[Dict[str, Any]] = []

        for article, analysis in zip(articles, analyses):
            if analysis is None:
                continue
            score = max(self.sentiment_floor, min(self.sentiment_cap, analysis.sentiment_score or 0.0))
            sentiment_scores.append(score)
            relevance_scores.append(analysis.relevance_score or 0.0)
            quality_scores.append(analysis.content_quality or 0.0)
            sentiment_distribution.update([analysis.sentiment_type or "unknown"])

            keyword_counter.update(_normalize_sequence(analysis.keywords))
            company_counter.update(_normalize_sequence(analysis.companies))
            location_counter.update(_normalize_sequence(analysis.locations))
            people_counter.update(_normalize_sequence(analysis.people))

            if analysis.summary:
                summaries.append(analysis.summary)

            references.append(
                {
                    "title": article.get("title"),
                    "url": article.get("url"),
                    "published_at": _ensure_iso(article.get("published_date")),
                    "sentiment_score": score,
                    "sentiment_type": analysis.sentiment_type,
                    "relevance": analysis.relevance_score,
                    "summary": analysis.summary,
                }
            )

        if not sentiment_scores:
            logger.info("No valid analysis for topic %s; skipping observation", topic.name)
            return None

        avg_sentiment = mean(sentiment_scores)
        positive_count = sentiment_distribution.get("positive", 0)
        negative_count = sentiment_distribution.get("negative", 0)
        neutral_count = sentiment_distribution.get("neutral", 0)
        total = positive_count + negative_count + neutral_count
        features = {
            "avg_sentiment": avg_sentiment,
            "positive_ratio": positive_count / total if total else 0.0,
            "negative_ratio": negative_count / total if total else 0.0,
            "neutral_ratio": neutral_count / total if total else 0.0,
            "relevance_mean": mean(relevance_scores) if relevance_scores else 0.0,
            "quality_mean": mean(quality_scores) if quality_scores else 0.0,
            "article_count": len(articles),
            "topic_weight": topic.weight,
        }

        top_keywords = [kw for kw, _ in keyword_counter.most_common(self.max_keywords)]
        top_entities = {
            "companies": [c for c, _ in company_counter.most_common(self.max_keywords)],
            "locations": [c for c, _ in location_counter.most_common(self.max_keywords)],
            "people": [c for c, _ in people_counter.most_common(self.max_keywords)],
        }

        observation = MacroObservation(
            topic=topic.name,
            observation_date=target_date,
            article_count=len(articles),
            features=features,
            top_keywords=top_keywords,
            top_entities=top_entities,
            summaries=summaries[: self.max_references],
            references=references[: self.max_references],
        )

        return observation

    def _deduplicate_results(self, results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        unique: List[Dict[str, Any]] = []
        for item in results:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            unique.append(item)
        return unique


def _normalize_sequence(values: Optional[Sequence[str]]) -> List[str]:
    if not values:
        return []
    normalized = []
    for value in values:
        if not value:
            continue
        trimmed = value.strip()
        if trimmed:
            normalized.append(trimmed)
    return normalized


def _ensure_iso(published_at: Any) -> Optional[str]:
    if published_at is None:
        return None
    if isinstance(published_at, datetime):
        return published_at.isoformat()
    if isinstance(published_at, date):
        return datetime.combine(published_at, datetime.min.time()).isoformat()
    return str(published_at)


async def run_pipeline(for_date: Optional[date] = None) -> MacroPipelineResult:
    pipeline = MacroNewsPipeline()
    return await pipeline.run_daily_pipeline(for_date=for_date)


def run() -> None:
    """Synchronous entry point for CLI usage."""
    result = asyncio.run(run_pipeline())
    logger.info("Macro pipeline completed: %s", result.to_dict())


if __name__ == "__main__":
    run()
