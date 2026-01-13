"""Generate daily macro news reports based on stored observations and model runs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Dict, List, Optional, Sequence

from ..utils.mongo_storage import StockNewsStorage, get_storage

logger = logging.getLogger(__name__)


def _parse_observation_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def _as_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _sentiment_label(value: Optional[float]) -> str:
    if value is None:
        return "未知"
    if value >= 0.25:
        return "积极"
    if value <= -0.25:
        return "偏空"
    return "中性"


def _mean(values: Sequence[float]) -> Optional[float]:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


@dataclass(slots=True)
class MacroReportGenerator:
    storage: Optional[StockNewsStorage] = None

    async def _ensure_storage(self) -> Optional[StockNewsStorage]:
        if self.storage is not None:
            return self.storage
        return await get_storage()

    async def generate_daily_report(
        self,
        *,
        target_date: Optional[date] = None,
        persist: bool = True,
    ) -> Optional[Dict[str, Any]]:
        storage = await self._ensure_storage()
        if storage is None:
            logger.warning("Mongo storage unavailable; macro report generation skipped")
            return None

        observations = await storage.get_macro_observations(limit=500)
        if not observations:
            logger.info("No macro observations available; report skipped")
            return None

        observations_by_date: Dict[date, List[Dict[str, Any]]] = {}
        for obs in observations:
            obs_date = _parse_observation_date(obs.get("observation_date"))
            if obs_date is None:
                continue
            observations_by_date.setdefault(obs_date, []).append(obs)

        if not observations_by_date:
            logger.info("Observations lack parseable dates; report skipped")
            return None

        report_date = target_date or max(observations_by_date)
        selected = observations_by_date.get(report_date)
        if not selected:
            logger.info("No observations found for report date %s", report_date)
            return None

        topic_entries: List[Dict[str, Any]] = []
        sentiments: List[float] = []
        total_articles = 0

        for item in selected:
            features = item.get("features", {}) or {}
            sentiment = _safe_float(features.get("avg_sentiment"))
            article_count = int(features.get("article_count") or item.get("article_count") or 0)
            total_articles += article_count
            if sentiment is not None:
                sentiments.append(sentiment)

            topic_entry = {
                "topic": item.get("topic") or "unknown",
                "topic_display": item.get("topic_display") or item.get("topic") or "unknown",
                "observation_date": item.get("observation_date") or report_date.isoformat(),
                "article_count": article_count,
                "avg_sentiment": sentiment,
                "positive_ratio": _safe_float(features.get("positive_ratio")),
                "negative_ratio": _safe_float(features.get("negative_ratio")),
                "neutral_ratio": _safe_float(features.get("neutral_ratio")),
                "relevance_mean": _safe_float(features.get("relevance_mean")),
                "top_keywords": list((item.get("top_keywords") or [])[:10]),
                "top_entities": item.get("top_entities") or {},
                "summaries": list((item.get("summaries") or [])[:5]),
                "references": list((item.get("references") or [])[:5]),
                "sentiment_label": _sentiment_label(sentiment),
            }
            topic_entries.append(topic_entry)

        topic_entries.sort(key=lambda t: (t["avg_sentiment"] or 0.0), reverse=True)
        top_positive = [t for t in topic_entries if (t["avg_sentiment"] or 0) > 0]
        top_negative = [t for t in sorted(topic_entries, key=lambda t: (t["avg_sentiment"] or 0.0)) if (t["avg_sentiment"] or 0) < 0]
        most_covered = sorted(topic_entries, key=lambda t: t["article_count"], reverse=True)

        avg_sentiment = _mean(sentiments)
        positive_share = None
        if sentiments:
            positive_share = sum(1 for s in sentiments if s is not None and s > 0) / len(sentiments)

        metrics = {
            "average_sentiment": avg_sentiment,
            "topic_count": len(topic_entries),
            "article_count": total_articles,
            "positive_topic_ratio": positive_share,
        }

        model_runs = await storage.get_macro_model_runs(limit=10)
        latest_run = model_runs[0] if model_runs else None

        best_validation_run = None
        best_rmse = float("inf")
        for run in model_runs:
            metrics_map = run.get("metrics", {}) or {}
            val_rmse = _safe_float(metrics_map.get("val_rmse"))
            if val_rmse is not None and val_rmse < best_rmse:
                best_rmse = val_rmse
                best_validation_run = run

        model_insights = {
            "latest_run": self._format_model_run(latest_run),
            "best_validation_run": self._format_model_run(best_validation_run),
        }

        highlights: List[Dict[str, str]] = []
        if top_positive:
            lead = top_positive[0]
            if lead["avg_sentiment"] and lead["avg_sentiment"] > 0.1:
                pos_ratio = lead.get("positive_ratio")
                pos_ratio_str = f"{pos_ratio:.0%}" if isinstance(pos_ratio, (int, float)) else "—"
                highlights.append({
                    "type": "positive-topic",
                    "title": f"{lead['topic_display']} 情绪回暖",
                    "detail": f"平均情绪 {lead['avg_sentiment']:.2f}，积极占比 {pos_ratio_str}。",
                })

        if top_negative:
            laggard = top_negative[0]
            if laggard["avg_sentiment"] and laggard["avg_sentiment"] < -0.1:
                neg_ratio = laggard.get("negative_ratio")
                neg_ratio_str = f"{neg_ratio:.0%}" if isinstance(neg_ratio, (int, float)) else "—"
                highlights.append({
                    "type": "negative-topic",
                    "title": f"{laggard['topic_display']} 需关注",
                    "detail": f"情绪 {laggard['avg_sentiment']:.2f}，消极占比 {neg_ratio_str}。",
                })

        if most_covered:
            heavy = most_covered[0]
            if heavy["article_count"] >= 5:
                keyword_preview = ", ".join(heavy["top_keywords"][:3]) if heavy["top_keywords"] else "多主题"
                highlights.append({
                    "type": "high-volume",
                    "title": f"{heavy['topic_display']} 热度最高",
                    "detail": f"收录 {heavy['article_count']} 篇相关文章，关键词聚焦 {keyword_preview}。",
                })

        if latest_run:
            metrics_map = latest_run.get("metrics", {}) or {}
            val_rmse = metrics_map.get("val_rmse")
            rmse_str = (
                f"{float(val_rmse):.3f}" if isinstance(val_rmse, (int, float)) else str(val_rmse)
            ) if val_rmse is not None else "N/A"
            highlights.append({
                "type": "model-update",
                "title": "模型训练更新",
                "detail": f"{latest_run.get('model_name', '宏观模型')} 于 {latest_run.get('run_date', '近期')} 运行，验证 RMSE {rmse_str}。",
            })

        report_payload: Dict[str, Any] = {
            "report_date": report_date.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "metrics": metrics,
            "topics": topic_entries,
            "top_positive_topics": top_positive[:3],
            "top_negative_topics": top_negative[:3],
            "most_covered_topics": most_covered[:3],
            "model_insights": model_insights,
            "highlights": highlights,
        }

        if persist:
            await storage.save_macro_report(report_payload)

        return report_payload

    @staticmethod
    def _format_model_run(run: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not run:
            return None
        return {
            "model_name": run.get("model_name"),
            "run_date": run.get("run_date"),
            "metrics": run.get("metrics", {}),
            "coefficients": run.get("coefficients", {}),
            "calibration": run.get("calibration", {}),
            "notes": run.get("notes", []),
        }


async def generate_and_store_macro_report(target_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
    generator = MacroReportGenerator()
    return await generator.generate_daily_report(target_date=target_date, persist=True)