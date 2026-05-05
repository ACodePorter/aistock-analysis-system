"""Generate daily macro news reports based on stored observations and model runs."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import sqrt
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


def _clamp(value: Optional[float], lower: float, upper: float) -> Optional[float]:
    if value is None:
        return None
    return max(lower, min(upper, value))


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # 常见乱码/占位字符过滤
    if "\ufffd" in text:
        text = text.replace("\ufffd", "")
    return " ".join(text.split())


def _is_high_quality_summary(text: str) -> bool:
    if not text:
        return False
    # 极短文本、URL 片段、疑似乱码都视为低质量
    if len(text) < 14:
        return False
    if text.startswith("http://") or text.startswith("https://"):
        return False
    return True


def _safe_ratio(value: Any) -> Optional[float]:
    ratio = _safe_float(value)
    return _clamp(ratio, 0.0, 1.0)


def _stddev(values: Sequence[float]) -> Optional[float]:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    if len(filtered) == 1:
        return 0.0
    avg = sum(filtered) / len(filtered)
    variance = sum((v - avg) ** 2 for v in filtered) / len(filtered)
    return sqrt(variance)


def _sentiment_bucket(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    if value >= 0.25:
        return "positive"
    if value <= -0.25:
        return "negative"
    return "neutral"


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


def _topic_confidence(article_count: int, reference_count: int, high_quality_summary_count: int) -> float:
    # 置信度由样本量、来源覆盖、摘要有效性组成
    sample_score = min(article_count / 12.0, 1.0)
    source_score = min(reference_count / 6.0, 1.0)
    summary_score = min(high_quality_summary_count / 3.0, 1.0)
    return round(sample_score * 0.45 + source_score * 0.35 + summary_score * 0.20, 4)


def _trend_label(delta_sentiment: Optional[float]) -> str:
    if delta_sentiment is None:
        return "未知"
    if delta_sentiment >= 0.08:
        return "明显回暖"
    if delta_sentiment >= 0.02:
        return "小幅回暖"
    if delta_sentiment <= -0.08:
        return "明显转弱"
    if delta_sentiment <= -0.02:
        return "小幅转弱"
    return "基本持平"


def _plain_market_state(market_regime: str, avg_sentiment: Optional[float]) -> str:
    if avg_sentiment is None:
        return "今天收集到的数据不够多，暂时无法判断市场整体氛围。"
    if avg_sentiment >= 0.3:
        return "今天市场整体氛围比较乐观，好消息明显多于坏消息，投资者情绪偏积极。"
    if avg_sentiment >= 0.1:
        return "今天市场氛围偏暖，正面消息略多，但还没到特别乐观的程度。"
    if avg_sentiment <= -0.3:
        return "今天市场整体氛围偏悲观，负面消息较多，投资者情绪比较谨慎。"
    if avg_sentiment <= -0.1:
        return "今天市场氛围偏冷，有一些不太好的消息在影响情绪。"
    return "今天市场整体比较平静，没有特别明显的乐观或悲观倾向。"


def _plain_focus_topic(concentration: Optional[float], most_covered: List[Dict[str, Any]]) -> str:
    if concentration is None or not most_covered:
        return "今天各方面的新闻都比较分散，没有特别集中的焦点话题。"
    topic_name = most_covered[0].get("topic_display") or most_covered[0].get("topic", "未知")
    if concentration >= 0.6:
        return f"今天大家最关注的话题是「{topic_name}」，大部分报道都集中在这个方向。"
    if concentration >= 0.4:
        return f"今天比较受关注的话题是「{topic_name}」，相关报道较多。"
    return f"今天的新闻比较分散，其中「{topic_name}」相对报道多一些。"


def _plain_trend_change(delta_avg_sentiment: Optional[float]) -> str:
    if delta_avg_sentiment is None:
        return "暂时没有前一天的数据可以对比。"
    if delta_avg_sentiment >= 0.15:
        return "和昨天相比，今天的市场情绪明显好转了，乐观程度提升不少。"
    if delta_avg_sentiment >= 0.05:
        return "和昨天相比，今天的市场情绪稍有好转。"
    if delta_avg_sentiment <= -0.15:
        return "和昨天相比，今天的市场情绪明显变差了，要注意防范风险。"
    if delta_avg_sentiment <= -0.05:
        return "和昨天相比，今天的市场情绪略有下滑。"
    return "和昨天相比，今天的市场情绪基本没什么变化，比较稳定。"


def _build_plain_summary(
    *,
    market_regime: str,
    avg_sentiment: Optional[float],
    delta_avg_sentiment: Optional[float],
    total_articles: int,
    validated_topics: List[Dict[str, Any]],
    opportunity_signals: List[Dict[str, Any]],
    risk_signals: List[Dict[str, Any]],
    most_covered: List[Dict[str, Any]],
) -> str:
    """生成一段通俗易懂的总结段落，面向普通投资者。"""
    parts: List[str] = []

    # 整体判断
    if avg_sentiment is not None:
        if avg_sentiment >= 0.2:
            parts.append(f"今天我们分析了 {total_articles} 篇宏观新闻，整体来看市场偏乐观")
        elif avg_sentiment <= -0.2:
            parts.append(f"今天我们分析了 {total_articles} 篇宏观新闻，整体来看市场偏谨慎")
        else:
            parts.append(f"今天我们分析了 {total_articles} 篇宏观新闻，整体来看市场比较平稳")
    else:
        parts.append("今天的宏观新闻数据还不够充分")

    # 趋势对比
    if delta_avg_sentiment is not None:
        if delta_avg_sentiment >= 0.05:
            parts.append("，比昨天的氛围有所改善")
        elif delta_avg_sentiment <= -0.05:
            parts.append("，比昨天的氛围有所下降")
        else:
            parts.append("，和昨天相比变化不大")
    parts.append("。")

    # 机会和风险
    opp_names = [s["topic"] for s in opportunity_signals[:2]]
    risk_names = [s["topic"] for s in risk_signals[:2]]

    if opp_names:
        opp_text = "、".join(opp_names)
        parts.append(f"其中，{opp_text}方面传来了比较积极的信号，可以多留意相关动态。")
    if risk_names:
        risk_text = "、".join(risk_names)
        parts.append(f"需要注意的是，{risk_text}方面的报道偏负面，建议谨慎对待。")

    if not opp_names and not risk_names:
        parts.append("今天各方面的消息都比较中性，没有特别突出的利好或利空。")

    return "".join(parts)


def _is_recent_report(report_date: date, max_lag_days: int = 1) -> bool:
    today = datetime.now(UTC).date()
    lag = (today - report_date).days
    return 0 <= lag <= max_lag_days


# ---- 话题名称中文化 ----
TOPIC_CN_NAMES: Dict[str, str] = {
    "global_macro": "全球宏观经济",
    "global macro": "全球宏观经济",
    "china_policy": "中国政策",
    "china policy": "中国政策",
    "property_and_urban": "房地产与城市发展",
    "property and urban": "房地产与城市发展",
    "technology_and_innovation": "科技创新",
    "technology and innovation": "科技创新",
    "energy_and_commodities": "能源与大宗商品",
    "energy and commodities": "能源与大宗商品",
}


def _cn_topic_name(topic: str, display: str = "") -> str:
    """将话题名转成中文。"""
    key = (topic or "").strip().lower()
    return TOPIC_CN_NAMES.get(key, display or topic or "未知话题")


def _build_topic_detail(entry: Dict[str, Any]) -> Dict[str, Any]:
    """从 validated topic 构建面向用户的话题详情。"""
    topic_key = entry.get("topic", "")
    display = entry.get("topic_display", "")
    cn_name = _cn_topic_name(topic_key, display)

    summaries = entry.get("summaries") or []
    references = entry.get("references") or []
    keywords = entry.get("top_keywords") or []
    entities = entry.get("top_entities") or {}
    sentiment = _safe_float(entry.get("avg_sentiment"))
    article_count = int(entry.get("article_count") or 0)

    # 从参考来源提取关键新闻条目
    key_news: List[Dict[str, Any]] = []
    for ref in references[:5]:
        title = _normalize_text(ref.get("title"))
        url = ref.get("url")
        summary = _normalize_text(ref.get("summary"))
        if not title and not summary:
            continue
        key_news.append({
            "title": title or "(无标题)",
            "url": url,
            "summary": summary or None,
            "sentiment_score": _safe_float(ref.get("sentiment_score")),
            "sentiment_type": ref.get("sentiment_type"),
        })

    # 提取提到的公司、人物
    companies = entities.get("companies") or []
    people = entities.get("people") or []

    # 生成话题摘要文字
    topic_summary_text = ""
    if summaries:
        # 取最具代表性的 2 条摘要组合
        top_summaries = [s for s in summaries[:3] if _is_high_quality_summary(s)]
        if top_summaries:
            topic_summary_text = " ".join(top_summaries[:2])

    # 生成用户可读的情绪描述
    if sentiment is not None:
        if sentiment >= 0.3:
            mood = "积极乐观"
        elif sentiment >= 0.1:
            mood = "偏向正面"
        elif sentiment <= -0.3:
            mood = "明显悲观"
        elif sentiment <= -0.1:
            mood = "偏向负面"
        else:
            mood = "中性平稳"
    else:
        mood = "数据不足"

    return {
        "topic": topic_key,
        "cn_name": cn_name,
        "mood": mood,
        "article_count": article_count,
        "sentiment": sentiment,
        "summary_text": topic_summary_text,
        "keywords": keywords[:8],
        "key_news": key_news,
        "companies": companies[:6],
        "people": people[:4],
    }


def _build_trend_analysis(
    observations_by_date: Dict[date, List[Dict[str, Any]]],
    report_date: date,
    max_days: int = 7,
) -> Dict[str, Any]:
    """构建最近 N 天各话题情绪趋势。"""
    cutoff = report_date - timedelta(days=max_days)
    dates_in_range = sorted(d for d in observations_by_date if cutoff <= d <= report_date)

    # 按话题聚合每日情绪
    topic_trends: Dict[str, List[Dict[str, Any]]] = {}
    daily_overall: List[Dict[str, Any]] = []

    for d in dates_in_range:
        day_obs = observations_by_date[d]
        day_sentiments: List[float] = []
        for obs in day_obs:
            topic_key = (obs.get("topic") or "").lower()
            features = obs.get("features") or {}
            s = _safe_float(features.get("avg_sentiment"))
            ac = int(features.get("article_count") or obs.get("article_count") or 0)
            cn = _cn_topic_name(topic_key, obs.get("topic_display", ""))
            if s is not None:
                day_sentiments.append(s)
                if cn not in topic_trends:
                    topic_trends[cn] = []
                topic_trends[cn].append({
                    "date": d.isoformat(),
                    "sentiment": round(s, 3),
                    "article_count": ac,
                })
        if day_sentiments:
            daily_overall.append({
                "date": d.isoformat(),
                "avg_sentiment": round(sum(day_sentiments) / len(day_sentiments), 3),
                "topic_count": len(day_sentiments),
            })

    # 识别趋势方向
    trend_direction = "stable"
    if len(daily_overall) >= 3:
        recent = [x["avg_sentiment"] for x in daily_overall[-3:]]
        earlier = [x["avg_sentiment"] for x in daily_overall[:max(1, len(daily_overall) - 3)]]
        avg_recent = sum(recent) / len(recent)
        avg_earlier = sum(earlier) / len(earlier)
        diff = avg_recent - avg_earlier
        if diff >= 0.1:
            trend_direction = "improving"
        elif diff <= -0.1:
            trend_direction = "deteriorating"

    # 找出变化最大的话题
    biggest_movers: List[Dict[str, Any]] = []
    for cn_name, points in topic_trends.items():
        if len(points) < 2:
            continue
        first_s = points[0]["sentiment"]
        last_s = points[-1]["sentiment"]
        delta = last_s - first_s
        if abs(delta) >= 0.05:
            if delta > 0:
                direction = "好转"
            else:
                direction = "转差"
            biggest_movers.append({
                "topic": cn_name,
                "delta": round(delta, 3),
                "direction": direction,
                "from_sentiment": first_s,
                "to_sentiment": last_s,
            })
    biggest_movers.sort(key=lambda x: abs(x["delta"]), reverse=True)

    return {
        "days_covered": len(dates_in_range),
        "daily_overall": daily_overall,
        "topic_trends": topic_trends,
        "trend_direction": trend_direction,
        "biggest_movers": biggest_movers[:5],
    }


def _aggregate_hot_keywords(selected: List[Dict[str, Any]], limit: int = 15) -> List[Dict[str, Any]]:
    """跨话题聚合关键词热度排行。"""
    counter: Counter[str] = Counter()
    keyword_topics: Dict[str, set] = {}
    for obs in selected:
        topic_cn = _cn_topic_name(
            (obs.get("topic") or "").lower(),
            obs.get("topic_display", ""),
        )
        for kw in (obs.get("top_keywords") or []):
            clean = _normalize_text(kw)
            if not clean or len(clean) < 2:
                continue
            counter[clean] += 1
            keyword_topics.setdefault(clean, set()).add(topic_cn)
    result = []
    for word, count in counter.most_common(limit):
        result.append({
            "keyword": word,
            "count": count,
            "topics": sorted(keyword_topics.get(word, set())),
        })
    return result


def _build_rich_summary(
    *,
    topic_details: List[Dict[str, Any]],
    trend_analysis: Dict[str, Any],
    hot_keywords: List[Dict[str, Any]],
    total_articles: int,
    avg_sentiment: Optional[float],
    delta_avg_sentiment: Optional[float],
    opportunity_signals: List[Dict[str, Any]],
    risk_signals: List[Dict[str, Any]],
) -> str:
    """生成一段包含具体内容的总结段落。"""
    parts: List[str] = []

    # 整体判断
    if avg_sentiment is not None:
        if avg_sentiment >= 0.2:
            parts.append(f"今天我们分析了 {total_articles} 篇宏观新闻，整体来看市场偏乐观")
        elif avg_sentiment <= -0.2:
            parts.append(f"今天我们分析了 {total_articles} 篇宏观新闻，整体来看市场偏谨慎")
        else:
            parts.append(f"今天我们分析了 {total_articles} 篇宏观新闻，整体来看市场比较平稳")
    else:
        parts.append("今天的宏观新闻数据还不够充分")

    # 趋势对比
    if delta_avg_sentiment is not None:
        if delta_avg_sentiment >= 0.05:
            parts.append("，比昨天的氛围有所改善")
        elif delta_avg_sentiment <= -0.05:
            parts.append("，比昨天的氛围有所下降")
        else:
            parts.append("，和昨天相比变化不大")
    parts.append("。")

    # 具体话题内容
    for td in topic_details[:3]:
        if td.get("summary_text"):
            parts.append(f"\n\n【{td['cn_name']}】{td['summary_text']}")

    # 机会和风险
    opp_names = [s["topic"] for s in opportunity_signals[:2]]
    risk_names = [s["topic"] for s in risk_signals[:2]]
    if opp_names:
        opp_text = "、".join(opp_names)
        parts.append(f"\n\n利好方面，{opp_text}传来了比较积极的信号，可以多留意。")
    if risk_names:
        risk_text = "、".join(risk_names)
        parts.append(f"需要注意的是，{risk_text}方面的报道偏负面，建议谨慎。")

    # 关键词高亮
    if hot_keywords:
        top_words = [k["keyword"] for k in hot_keywords[:6]]
        kw_text = "、".join(top_words)
        parts.append(f"\n\n今日热门话题关键词：{kw_text}。")

    # 趋势概述
    movers = trend_analysis.get("biggest_movers") or []
    if movers:
        mover = movers[0]
        parts.append(f"近期变化最大的方向是「{mover['topic']}」（{mover['direction']}）。")

    return "".join(parts)


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
        total_references = 0
        high_quality_summary_topics = 0

        for item in selected:
            features = item.get("features", {}) or {}
            sentiment = _clamp(_safe_float(features.get("avg_sentiment")), -1.0, 1.0)
            article_count = int(features.get("article_count") or item.get("article_count") or 0)
            total_articles += article_count
            if sentiment is not None:
                sentiments.append(sentiment)

            raw_keywords = list(item.get("top_keywords") or [])
            cleaned_keywords: List[str] = []
            seen_keywords: set[str] = set()
            for kw in raw_keywords:
                clean_kw = _normalize_text(kw)
                if not clean_kw:
                    continue
                lowered = clean_kw.lower()
                if lowered in seen_keywords:
                    continue
                seen_keywords.add(lowered)
                cleaned_keywords.append(clean_kw)
                if len(cleaned_keywords) >= 10:
                    break

            raw_summaries = list(item.get("summaries") or [])
            cleaned_summaries: List[str] = []
            for summary in raw_summaries:
                clean_summary = _normalize_text(summary)
                if not _is_high_quality_summary(clean_summary):
                    continue
                cleaned_summaries.append(clean_summary)
                if len(cleaned_summaries) >= 5:
                    break

            if cleaned_summaries:
                high_quality_summary_topics += 1

            references: List[Dict[str, Any]] = []
            seen_reference_keys: set[str] = set()
            for ref in list(item.get("references") or []):
                title = _normalize_text((ref or {}).get("title"))
                url = _normalize_text((ref or {}).get("url"))
                summary = _normalize_text((ref or {}).get("summary"))
                if not title and not url:
                    continue
                key = f"{title.lower()}|{url.lower()}"
                if key in seen_reference_keys:
                    continue
                seen_reference_keys.add(key)
                references.append(
                    {
                        "title": title or None,
                        "url": url or None,
                        "published_at": (ref or {}).get("published_at"),
                        "sentiment_score": _clamp(_safe_float((ref or {}).get("sentiment_score")), -1.0, 1.0),
                        "sentiment_type": (ref or {}).get("sentiment_type"),
                        "relevance": _safe_ratio((ref or {}).get("relevance")),
                        "summary": summary or None,
                    }
                )
                if len(references) >= 8:
                    break

            reference_count = len(references)
            total_references += reference_count

            confidence = _topic_confidence(
                article_count=article_count,
                reference_count=reference_count,
                high_quality_summary_count=len(cleaned_summaries),
            )

            signal_type = "neutral"
            if sentiment is not None and confidence >= 0.45:
                if sentiment >= 0.2 and article_count >= 3:
                    signal_type = "opportunity"
                elif sentiment <= -0.2 and article_count >= 3:
                    signal_type = "risk"

            topic_entry = {
                "topic": item.get("topic") or "unknown",
                "topic_display": item.get("topic_display") or item.get("topic") or "unknown",
                "observation_date": item.get("observation_date") or report_date.isoformat(),
                "article_count": article_count,
                "avg_sentiment": sentiment,
                "positive_ratio": _safe_ratio(features.get("positive_ratio")),
                "negative_ratio": _safe_ratio(features.get("negative_ratio")),
                "neutral_ratio": _safe_ratio(features.get("neutral_ratio")),
                "relevance_mean": _safe_ratio(features.get("relevance_mean")),
                "top_keywords": cleaned_keywords,
                "top_entities": item.get("top_entities") or {},
                "summaries": cleaned_summaries,
                "references": references,
                "sentiment_label": _sentiment_label(sentiment),
                "confidence": confidence,
                "signal_type": signal_type,
            }
            topic_entries.append(topic_entry)

        # 过滤低价值主题：样本过少、摘要与来源证据不足的主题不纳入核心结论。
        validated_topics = [
            t
            for t in topic_entries
            if int(t.get("article_count") or 0) >= 1
            and (_safe_float(t.get("confidence")) or 0.0) >= 0.3
            and (len(t.get("summaries") or []) > 0 or len(t.get("references") or []) >= 1)
        ]

        # 如果所有主题都被过滤掉了，回退使用全部主题（至少有文章的）
        if not validated_topics and topic_entries:
            validated_topics = [t for t in topic_entries if int(t.get("article_count") or 0) >= 1]

        validated_topics.sort(key=lambda t: (t["avg_sentiment"] or 0.0), reverse=True)
        top_positive = [t for t in validated_topics if (t["avg_sentiment"] or 0) > 0]
        top_negative = [t for t in sorted(validated_topics, key=lambda t: (t["avg_sentiment"] or 0.0)) if (t["avg_sentiment"] or 0) < 0]
        most_covered = sorted(validated_topics, key=lambda t: t["article_count"], reverse=True)

        avg_sentiment = _mean(sentiments)
        sentiment_dispersion = _stddev(sentiments)
        positive_share = None
        if sentiments:
            positive_share = sum(1 for s in sentiments if s is not None and s > 0) / len(sentiments)
        negative_share = None
        neutral_share = None
        if sentiments:
            negative_share = sum(1 for s in sentiments if s is not None and s < 0) / len(sentiments)
            neutral_share = 1.0 - (positive_share or 0.0) - (negative_share or 0.0)

        concentration = None
        if total_articles > 0 and most_covered:
            concentration = _clamp(most_covered[0]["article_count"] / total_articles, 0.0, 1.0)

        avg_confidence = _mean([_safe_float(t.get("confidence")) or 0.0 for t in topic_entries])
        references_per_topic = total_references / len(topic_entries) if topic_entries else 0.0
        summary_quality_ratio = high_quality_summary_topics / len(topic_entries) if topic_entries else 0.0

        previous_day = None
        previous_report = None
        prev_candidates = sorted(d for d in observations_by_date.keys() if d < report_date)
        if prev_candidates:
            previous_day = prev_candidates[-1]
            previous_report = await storage.get_macro_report_by_date(previous_day)

        prev_metrics = (previous_report or {}).get("metrics", {}) if isinstance(previous_report, dict) else {}
        prev_avg_sentiment = _safe_float(prev_metrics.get("average_sentiment"))
        prev_article_count = _safe_float(prev_metrics.get("article_count"))
        prev_topic_count = _safe_float(prev_metrics.get("topic_count"))

        delta_avg_sentiment = None
        if avg_sentiment is not None and prev_avg_sentiment is not None:
            delta_avg_sentiment = avg_sentiment - prev_avg_sentiment

        delta_article_count = None
        if prev_article_count is not None:
            delta_article_count = total_articles - int(prev_article_count)

        delta_topic_count = None
        if prev_topic_count is not None:
            delta_topic_count = len(topic_entries) - int(prev_topic_count)

        market_regime = "中性震荡"
        if avg_sentiment is not None:
            if avg_sentiment >= 0.2:
                market_regime = "情绪偏多"
            elif avg_sentiment <= -0.2:
                market_regime = "情绪偏空"

        if sentiment_dispersion is not None and sentiment_dispersion >= 0.35:
            market_regime += "（分歧较大）"

        metrics = {
            "average_sentiment": avg_sentiment,
            "topic_count": len(topic_entries),
            "article_count": total_articles,
            "positive_topic_ratio": positive_share,
            "negative_topic_ratio": negative_share,
            "neutral_topic_ratio": _clamp(neutral_share, 0.0, 1.0) if neutral_share is not None else None,
            "sentiment_dispersion": sentiment_dispersion,
            "attention_concentration": concentration,
            "avg_topic_confidence": avg_confidence,
            "references_per_topic": round(references_per_topic, 2),
            "summary_quality_ratio": round(summary_quality_ratio, 4),
            "delta_avg_sentiment": delta_avg_sentiment,
            "delta_article_count": delta_article_count,
            "delta_topic_count": delta_topic_count,
            "market_regime": market_regime,
            "trend_label": _trend_label(delta_avg_sentiment),
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

        # 旧版亮点卡信息密度低，直接停用。
        highlights: List[Dict[str, str]] = []

        risk_signals: List[Dict[str, Any]] = []
        opportunity_signals: List[Dict[str, Any]] = []
        for topic in validated_topics:
            sentiment = _safe_float(topic.get("avg_sentiment"))
            confidence = _safe_float(topic.get("confidence")) or 0.0
            article_count = int(topic.get("article_count") or 0)
            raw_name = topic.get("topic_display") or topic.get("topic") or "未知主题"
            topic_name = _cn_topic_name((topic.get("topic") or "").lower(), raw_name)
            topic_kws = (topic.get("top_keywords") or [])[:4]
            kw_hint = "、".join(topic_kws) if topic_kws else ""
            summaries = topic.get("summaries") or []
            brief = summaries[0][:80] if summaries else ""
            if sentiment is None:
                continue
            if sentiment <= -0.2 and article_count >= 3:
                detail_parts = [f"关于「{topic_name}」"]
                if brief:
                    detail_parts.append(f"（{brief}…）")
                detail_parts.append(f"的 {article_count} 篇报道中，负面情绪较为突出")
                if kw_hint:
                    detail_parts.append(f"，涉及{kw_hint}等方面")
                reason = "".join(detail_parts)
                risk_signals.append(
                    {
                        "topic": topic_name,
                        "severity": "high" if sentiment <= -0.35 else "medium",
                        "confidence": round(confidence, 3),
                        "reason": reason,
                        "keywords": topic_kws,
                    }
                )
            if sentiment >= 0.2 and article_count >= 3:
                detail_parts = [f"关于「{topic_name}」"]
                if brief:
                    detail_parts.append(f"（{brief}…）")
                detail_parts.append(f"的 {article_count} 篇报道中，积极信号明显")
                if kw_hint:
                    detail_parts.append(f"，涉及{kw_hint}等方面")
                reason = "".join(detail_parts)
                opportunity_signals.append(
                    {
                        "topic": topic_name,
                        "severity": "high" if sentiment >= 0.35 else "medium",
                        "confidence": round(confidence, 3),
                        "reason": reason,
                        "keywords": topic_kws,
                    }
                )

        risk_signals.sort(key=lambda x: (x.get("severity") == "high", x.get("confidence", 0)), reverse=True)
        opportunity_signals.sort(key=lambda x: (x.get("severity") == "high", x.get("confidence", 0)), reverse=True)

        # 生成内容更丰富的执行摘要
        executive_summary: List[str] = [
            _plain_market_state(market_regime, avg_sentiment),
            _plain_focus_topic(concentration, most_covered),
            _plain_trend_change(delta_avg_sentiment),
        ]
        # 追加各话题的关键信息
        for t in validated_topics[:3]:
            t_cn = _cn_topic_name((t.get("topic") or "").lower(), t.get("topic_display", ""))
            t_summaries = t.get("summaries") or []
            if t_summaries:
                executive_summary.append(f"「{t_cn}」方面：{t_summaries[0]}")

        focus_actions: List[str] = []
        avoid_actions: List[str] = []
        verify_actions: List[str] = []

        for signal in opportunity_signals[:3]:
            focus_actions.append(f"可以多关注「{signal['topic']}」——{signal['reason']}")
        for signal in risk_signals[:3]:
            avoid_actions.append(f"注意「{signal['topic']}」——{signal['reason']}")

        if concentration is not None and concentration >= 0.55:
            verify_actions.append("今天大家的注意力都集中在少数几个话题上，需要注意是否被单一新闻事件带动了情绪。")
        if avg_confidence is not None and avg_confidence < 0.45:
            verify_actions.append("今天收集到的新闻样本较少，结论仅供参考，建议明天再看看趋势是否一致。")
        if delta_avg_sentiment is not None and abs(delta_avg_sentiment) >= 0.08:
            verify_actions.append("今天市场情绪变化比较大，建议观察明天的走势来确认方向。")

        if not focus_actions:
            focus_actions.append("今天没有特别突出的利好方向，建议保持观望，不急于操作。")
        if not avoid_actions:
            avoid_actions.append("今天没有发现明显的风险信号，但仍需保持关注。")
        if not verify_actions:
            verify_actions.append("今天的数据整体平稳，可以按正常节奏关注市场变化。")

        data_diagnostics: List[Dict[str, Any]] = [
            {
                "name": "数据可靠度",
                "value": round(avg_confidence, 3) if avg_confidence is not None else None,
                "status": "good" if (avg_confidence or 0) >= 0.65 else "warn" if (avg_confidence or 0) >= 0.45 else "risk",
                "detail": "衡量今天分析结论的可信程度，越高越可靠",
            },
            {
                "name": "信息完整度",
                "value": round(summary_quality_ratio, 3),
                "status": "good" if summary_quality_ratio >= 0.7 else "warn" if summary_quality_ratio >= 0.45 else "risk",
                "detail": "衡量今天收集到的新闻内容是否足够充分",
            },
            {
                "name": "来源丰富度",
                "value": round(references_per_topic, 2),
                "status": "good" if references_per_topic >= 3 else "warn" if references_per_topic >= 1.5 else "risk",
                "detail": "每个话题平均参考了多少篇文章，越多越全面",
            },
        ]

        report_outline = [
            "今日市场是偏乐观还是偏悲观？和昨天比有什么变化？",
            "哪些行业板块有利好消息？哪些需要注意风险？",
            "这些结论是基于哪些新闻和数据得出的？",
            "今天应该重点关注什么？需要回避什么？",
        ]

        is_recent = _is_recent_report(report_date, max_lag_days=3)
        has_minimum_topic_coverage = len(validated_topics) >= 1
        has_minimum_evidence = references_per_topic >= 0.5 or summary_quality_ratio >= 0.2
        is_valid = bool(is_recent and has_minimum_topic_coverage)
        is_high_quality = bool(is_valid and has_minimum_evidence and len(validated_topics) >= 2)

        invalid_reasons: List[str] = []
        quality_notes: List[str] = []
        if not is_recent:
            invalid_reasons.append("报告日期距今超过3天，信息可能已过时")
        if not has_minimum_topic_coverage:
            invalid_reasons.append("收集到的有效话题太少，无法形成有意义的分析")
        if not has_minimum_evidence:
            quality_notes.append("今天收集到的资料还不够充分，结论仅供参考")
        if len(validated_topics) < 2:
            quality_notes.append("覆盖的话题较少，可能无法全面反映市场情况")

        validation = {
            "is_valid": is_valid,
            "is_high_quality": is_high_quality,
            "feature_enabled": is_valid,
            "checked_at": datetime.now(UTC).isoformat(),
            "rules": {
                "freshness_within_days": 3,
                "min_valid_topics": 1,
                "min_references_per_topic": 0.5,
                "min_summary_quality_ratio": 0.2,
            },
            "stats": {
                "valid_topics": len(validated_topics),
                "raw_topics": len(topic_entries),
                "references_per_topic": round(references_per_topic, 2),
                "summary_quality_ratio": round(summary_quality_ratio, 3),
                "report_is_recent": is_recent,
            },
            "invalid_reasons": invalid_reasons,
            "quality_notes": quality_notes,
            "message": "数据充分，报告可供参考" if is_high_quality else ("数据基本可用，部分结论仅供参考" if is_valid else "今天收集到的数据不够充分，结论仅供参考"),
        }

        # ---- 新增：话题详情、趋势分析、热门关键词 ----
        topic_details = [_build_topic_detail(t) for t in validated_topics]

        trend_analysis = _build_trend_analysis(
            observations_by_date, report_date, max_days=7,
        )

        hot_keywords = _aggregate_hot_keywords(selected, limit=15)

        # 使用 cn_name 替换信号中的英文话题名
        for sig in risk_signals:
            sig["topic"] = _cn_topic_name(sig.get("topic", ""), sig.get("topic", ""))
        for sig in opportunity_signals:
            sig["topic"] = _cn_topic_name(sig.get("topic", ""), sig.get("topic", ""))

        plain_summary = _build_rich_summary(
            topic_details=topic_details,
            trend_analysis=trend_analysis,
            hot_keywords=hot_keywords,
            total_articles=total_articles,
            avg_sentiment=avg_sentiment,
            delta_avg_sentiment=delta_avg_sentiment,
            opportunity_signals=opportunity_signals,
            risk_signals=risk_signals,
        )

        report_payload: Dict[str, Any] = {
            "report_date": report_date.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "plain_summary": plain_summary,
            "outline": report_outline,
            "validation": validation,
            "metrics": metrics,
            "executive_summary": executive_summary,
            "risk_signals": risk_signals[:5],
            "opportunity_signals": opportunity_signals[:5],
            "action_items": {
                "focus": focus_actions,
                "avoid": avoid_actions,
                "verify": verify_actions,
            },
            "data_diagnostics": data_diagnostics,
            "topics": validated_topics,
            "topic_details": topic_details,
            "trend_analysis": trend_analysis,
            "hot_keywords": hot_keywords,
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