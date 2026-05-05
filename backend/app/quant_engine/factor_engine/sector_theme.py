"""
Sector & Theme Factor Engine

Computes sector strength rankings and theme heat scores using mixed aggregation:
  news sentiment (40%) + technical score (30%) + fund-flow score (30%).

Pure in-memory computation. No DB writes, no external API calls.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import math


@dataclass
class SectorHeatScore:
    """Sector strength score with ranking."""
    name: str
    ranking: int
    score: float                        # composite score [0, 100]
    confidence: float                   # data confidence [0, 1]
    news_sentiment_score: float         # news sentiment component [0, 100]
    tech_score: float                   # technical component [0, 100]
    fund_score: float                   # fund-flow component [0, 100]
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ThemeHeatScore:
    """Theme heat score with ranking."""
    name: str
    ranking: int
    score: float                        # composite score [0, 100]
    frequency: int                      # number of related news articles
    avg_sentiment: float                # average sentiment [-1, 1]
    associated_symbols: List[str]       # related stock codes
    metadata: Optional[Dict[str, Any]] = None


def _tanh_normalize(value: float, center: float = 0.0, scale: float = 1.0) -> float:
    """Map an arbitrary value to [0, 100] via tanh.

    score = 50 + 50 * tanh((value - center) / scale)
    """
    z = (value - center) / scale if scale != 0 else 0.0
    return 50.0 + 50.0 * math.tanh(z)


def calculate_sector_strength(
    sector_data: Dict[str, Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> List[SectorHeatScore]:
    """Calculate sector strength rankings using mixed aggregation.

    Args:
        sector_data: Pre-aggregated sector data, keyed by sector name.
            Each entry contains:
                "news_sentiment"  float  avg news sentiment [-1.0, 1.0]
                "tech_score"      float  technical score    [0, 100]
                "fund_score"      float  fund-flow score    [0, 100]
                "confidence"      float  data confidence    [0, 1]   (optional)
                "metadata"        dict   raw stats                   (optional)

        weights: Weight config dict with keys "news", "tech", "fund".
                 Values must sum to 1.0.
                 Defaults to {"news": 0.4, "tech": 0.3, "fund": 0.3}.

    Returns:
        List[SectorHeatScore] sorted by score descending (rank 1 = strongest).

    Raises:
        ValueError: If weights do not sum to 1.0.
    """
    if not sector_data:
        return []

    if weights is None:
        weights = {"news": 0.4, "tech": 0.3, "fund": 0.3}

    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) > 0.01:
        raise ValueError(f"Weights must sum to 1.0, got {weight_sum:.3f}")

    results: List[SectorHeatScore] = []

    for sector_name, data in sector_data.items():
        news_raw   = float(data.get("news_sentiment", 0.0))  # [-1, 1]
        tech       = float(data.get("tech_score", 50.0))     # [0, 100]
        fund       = float(data.get("fund_score", 50.0))     # [0, 100]
        confidence = float(data.get("confidence", 0.5))

        # Map news_sentiment [-1, 1] -> [0, 100].
        # scale=0.5: sentiment +-0.5 maps to ~76/24, +-1.0 maps to ~93/7.
        news_score = _tanh_normalize(news_raw, center=0.0, scale=0.5)

        news_score = max(0.0, min(100.0, news_score))
        tech       = max(0.0, min(100.0, tech))
        fund       = max(0.0, min(100.0, fund))

        composite = (
            news_score * weights["news"]
            + tech     * weights["tech"]
            + fund     * weights["fund"]
        )

        results.append(SectorHeatScore(
            name=sector_name,
            ranking=0,
            score=round(composite, 2),
            confidence=min(1.0, max(0.0, confidence)),
            news_sentiment_score=round(news_score, 2),
            tech_score=round(tech, 2),
            fund_score=round(fund, 2),
            metadata={"weights": weights, "raw": data.get("metadata", {})},
        ))

    results.sort(key=lambda x: x.score, reverse=True)
    for rank, item in enumerate(results, 1):
        item.ranking = rank

    return results


def calculate_theme_heat(
    theme_data: Dict[str, Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
    top_n: Optional[int] = None,
    frequency_baseline: int = 5,
) -> List[ThemeHeatScore]:
    """Calculate theme heat scores using a composite index.

    Args:
        theme_data: Pre-aggregated theme data, keyed by theme name.
            Each entry contains:
                "frequency"           int    article count
                "avg_sentiment"       float  avg sentiment score  [-1.0, 1.0]
                "sentiment_std"       float  sentiment stddev               (optional)
                "stock_performance"   float  avg daily return of related stocks (%)
                "associated_symbols"  list   related stock codes
                "metadata"            dict   raw stats                     (optional)

        weights: Weight config dict with keys "frequency", "sentiment", "performance".
                 Values must sum to 1.0.
                 Defaults to {"frequency": 0.4, "sentiment": 0.3, "performance": 0.3}.

        top_n:              Return only the top-N themes. None returns all.
        frequency_baseline: Article count that saturates the frequency score to 100.
                            Defaults to 5.

    Returns:
        List[ThemeHeatScore] sorted by score descending, length <= top_n if given.

    Raises:
        ValueError: If weights do not sum to 1.0.
    """
    if not theme_data:
        return []

    if weights is None:
        weights = {"frequency": 0.4, "sentiment": 0.3, "performance": 0.3}

    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) > 0.01:
        raise ValueError(f"Weights must sum to 1.0, got {weight_sum:.3f}")

    if frequency_baseline <= 0:
        frequency_baseline = 5

    results: List[ThemeHeatScore] = []

    for theme_name, data in theme_data.items():
        frequency         = max(0, int(data.get("frequency", 0)))
        avg_sentiment     = float(data.get("avg_sentiment", 0.0))
        sentiment_std     = float(data.get("sentiment_std", 0.0))
        stock_performance = float(data.get("stock_performance", 0.0))  # %
        symbols           = data.get("associated_symbols", [])

        avg_sentiment = max(-1.0, min(1.0, avg_sentiment))
        sentiment_std = max(0.0, sentiment_std)

        # Frequency score [0, 100]: linear, saturates at baseline count.
        freq_score = min(100.0, (frequency / frequency_baseline) * 100.0)

        # Sentiment intensity [0, 100].
        # extremity = |avg| * (1 + std) in [0, ~2], then scaled to [0, 100].
        intensity  = abs(avg_sentiment) * (1.0 + sentiment_std)
        sent_score = min(100.0, (min(2.0, intensity) / 2.0) * 100.0)

        # Performance score [0, 100]: tanh, scale=10 so +-10% -> ~76/24.
        perf_score = max(0.0, min(100.0,
            _tanh_normalize(stock_performance, center=0.0, scale=10.0)))

        composite = (
            freq_score * weights["frequency"]
            + sent_score * weights["sentiment"]
            + perf_score * weights["performance"]
        )

        results.append(ThemeHeatScore(
            name=theme_name,
            ranking=0,
            score=round(composite, 2),
            frequency=frequency,
            avg_sentiment=round(avg_sentiment, 3),
            associated_symbols=symbols if isinstance(symbols, list) else [],
            metadata={
                "weights": weights,
                "frequency_score": round(freq_score, 2),
                "sentiment_score": round(sent_score, 2),
                "performance_score": round(perf_score, 2),
                "raw": data.get("metadata", {}),
            },
        ))

    results.sort(key=lambda x: x.score, reverse=True)

    if top_n is not None:
        results = results[:top_n]

    for rank, item in enumerate(results, 1):
        item.ranking = rank

    return results
