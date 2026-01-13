"""Utilities for generating daily macro news reports."""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

from ..reports.macro_pipeline import MacroObservation, MacroPipelineResult
from ..utils.mongo_storage import StockNewsStorage, get_storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MacroDailyReport:
    """Structured representation of a daily macro news report."""

    report_date: date
    generated_at: datetime
    headline: str
    summary: str
    highlights: List[str]
    metrics: Dict[str, Any]
    topics: List[Dict[str, Any]]
    model: Optional[Dict[str, Any]]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["report_date"] = self.report_date.isoformat()
        payload["generated_at"] = self.generated_at.isoformat()
        return payload


def _sentiment_label(value: Optional[float]) -> str:
    if value is None:
        return "无数据"
    if value >= 0.25:
        return "偏暖"
    if value <= -0.25:
        return "偏冷"
    return "中性"


def _weighted_average(observations: Sequence[MacroObservation]) -> Optional[float]:
    numerator = 0.0
    denominator = 0.0
    for obs in observations:
        sentiment = (obs.features or {}).get("avg_sentiment")
        if sentiment is None:
            continue
        weight = max(obs.article_count or 0, 1)
        numerator += sentiment * weight
        denominator += weight
    if denominator == 0.0:
        return None
    return numerator / denominator


def _prepare_topic_payload(observation: MacroObservation) -> Dict[str, Any]:
    features = observation.features or {}
    obs_date = observation.observation_date.isoformat() if isinstance(observation.observation_date, date) else str(observation.observation_date)
    sentiment = features.get("avg_sentiment")
    return {
        "topic": observation.topic,
        "topic_display": observation.topic,
        "observation_date": obs_date,
        "article_count": observation.article_count,
        "sentiment": sentiment,
        "sentiment_label": _sentiment_label(sentiment),
        "positive_ratio": features.get("positive_ratio"),
        "neutral_ratio": features.get("neutral_ratio"),
        "negative_ratio": features.get("negative_ratio"),
        "relevance_mean": features.get("relevance_mean"),
        "top_keywords": (observation.top_keywords or [])[:5],
        "top_entities": observation.top_entities or {},
        "summaries": (observation.summaries or [])[:3],
        "references": (observation.references or [])[:3],
    }


def build_macro_daily_report(
    result: MacroPipelineResult,
    *,
    model_run: Optional[Dict[str, Any]] = None,
) -> MacroDailyReport:
    """Compose a daily macro report from pipeline output and optional model metrics."""

    observations = result.observations or []
    report_date = _determine_report_date(observations, result)

    overall_sentiment = _weighted_average(observations)
    tone_label = _sentiment_label(overall_sentiment)
    total_articles = sum(obs.article_count or 0 for obs in observations)

    sorted_by_sentiment = [obs for obs in observations if (obs.features or {}).get("avg_sentiment") is not None]
    sorted_by_sentiment.sort(key=lambda obs: (obs.features or {}).get("avg_sentiment"), reverse=True)

    top_positive = sorted_by_sentiment[0] if sorted_by_sentiment else None
    bottom_negative = sorted_by_sentiment[-1] if sorted_by_sentiment else None
    if top_positive is bottom_negative:
        bottom_negative = None

    sorted_by_volume = sorted(observations, key=lambda obs: obs.article_count or 0, reverse=True)
    busiest_topic = sorted_by_volume[0] if sorted_by_volume else None

    highlights: List[str] = []
    metrics: Dict[str, Any] = {
        "overall_sentiment": overall_sentiment,
        "tone": tone_label,
        "total_topics": len(observations),
        "total_articles": total_articles,
        "pipeline_errors": len(result.errors or []),
    }

    if overall_sentiment is not None:
        highlights.append(f"整体情绪 {overall_sentiment:.2f}（{tone_label}）")
    else:
        highlights.append("整体情绪缺少数据")

    highlights.append(f"覆盖 {len(observations)} 个主题，整合 {total_articles} 篇文章")

    if top_positive:
        pos_sentiment = (top_positive.features or {}).get("avg_sentiment")
        highlights.append(
            f"最积极主题：{top_positive.topic}（{pos_sentiment:.2f}，{top_positive.article_count} 篇）"
        )
        metrics["top_positive_topic"] = {
            "topic": top_positive.topic,
            "sentiment": pos_sentiment,
            "article_count": top_positive.article_count,
        }

    if bottom_negative and bottom_negative is not top_positive:
        neg_sentiment = (bottom_negative.features or {}).get("avg_sentiment")
        highlights.append(
            f"最承压主题：{bottom_negative.topic}（{neg_sentiment:.2f}，{bottom_negative.article_count} 篇）"
        )
        metrics["top_negative_topic"] = {
            "topic": bottom_negative.topic,
            "sentiment": neg_sentiment,
            "article_count": bottom_negative.article_count,
        }

    if busiest_topic and busiest_topic is not top_positive:
        highlights.append(
            f"信息最密集：{busiest_topic.topic}（{busiest_topic.article_count} 篇）"
        )
        metrics["busiest_topic"] = {
            "topic": busiest_topic.topic,
            "article_count": busiest_topic.article_count,
        }

    if model_run:
        metrics["model"] = model_run
        model_name = model_run.get("model_name", "模型")
        key_metric = _extract_model_metric(model_run.get("metrics") or {})
        highlights.append(f"{model_name} 最新训练：{key_metric}")

    warnings = [
        f"Pipeline error: {err}" for err in (result.errors or [])
    ]

    headline = _compose_headline(report_date, tone_label, total_articles)
    summary = _compose_summary(report_date, tone_label, total_articles, observations)

    topics_payload = [_prepare_topic_payload(obs) for obs in observations]

    return MacroDailyReport(
        report_date=report_date,
        generated_at=datetime.utcnow(),
        headline=headline,
        summary=summary,
        highlights=highlights,
        metrics=metrics,
        topics=topics_payload,
        model=model_run,
        warnings=warnings,
    )


def _determine_report_date(observations: Sequence[MacroObservation], result: MacroPipelineResult) -> date:
    dates: List[date] = []
    for obs in observations:
        obs_date = obs.observation_date
        if isinstance(obs_date, date):
            dates.append(obs_date)
        elif isinstance(obs_date, datetime):
            dates.append(obs_date.date())
        elif isinstance(obs_date, str):
            try:
                dates.append(datetime.fromisoformat(obs_date).date())
            except ValueError:
                continue
    if dates:
        return max(dates)
    return result.finished_at.date()


def _compose_headline(report_date: date, tone_label: str, total_articles: int) -> str:
    if total_articles == 0:
        return f"{report_date.isoformat()} 宏观情绪：暂无数据"
    return f"{report_date.isoformat()} 宏观情绪：{tone_label}"


def _compose_summary(
    report_date: date,
    tone_label: str,
    total_articles: int,
    observations: Sequence[MacroObservation],
) -> str:
    if not observations:
        return (
            f"{report_date.isoformat()} 未收集到宏观新闻观测数据，"
            "请关注数据管道状态或稍后查看。"
        )
    topics = len(observations)
    return (
        f"{report_date.isoformat()} 的宏观新闻整理完成，整体情绪{tone_label}，"
        f"覆盖 {topics} 个主题，合计 {total_articles} 篇核心文章。"
    )


def _extract_model_metric(metrics: Dict[str, Any]) -> str:
    if not metrics:
        return "指标缺失"
    if "rmse" in metrics:
        return f"RMSE {metrics['rmse']}"
    first_key = next(iter(metrics.keys()))
    return f"{first_key} {metrics[first_key]}"


def _sanitize_report_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = doc.copy()
    model_section = sanitized.get("model")
    if isinstance(model_section, dict):
        run_date = model_section.get("run_date")
        if isinstance(run_date, datetime):
            model_section["run_date"] = run_date.isoformat()
    return sanitized


async def generate_and_store_macro_report(
    result: MacroPipelineResult,
    *,
    storage: Optional[StockNewsStorage] = None,
) -> Optional[Dict[str, Any]]:
    """Generate a macro daily report and persist it to MongoDB."""

    storage = storage or await get_storage()
    if storage is None:
        logger.warning("Macro storage unavailable; skipping macro report generation")
        return None

    latest_model_run = await storage.get_macro_model_runs(limit=1)
    model_run = latest_model_run[0] if latest_model_run else None

    report = build_macro_daily_report(result, model_run=model_run)
    document = report.to_dict()
    await storage.save_macro_daily_report(document)
    return _sanitize_report_doc(document)


async def get_latest_macro_report(
    *,
    storage: Optional[StockNewsStorage] = None,
) -> Optional[Dict[str, Any]]:
    storage = storage or await get_storage()
    if storage is None:
        return None
    return await storage.get_latest_macro_daily_report()
