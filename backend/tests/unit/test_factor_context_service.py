from datetime import datetime, date
from types import SimpleNamespace

from app.prediction.services.factor_context_service import (
    build_factor_context,
    build_macro_context,
    build_news_context,
    build_quant_factor_context,
)


def article(title, sentiment_type, score, category="company", keywords=None):
    return SimpleNamespace(
        title=title,
        published_at=datetime(2026, 4, 25, 10, 0),
        sentiment_type=sentiment_type,
        sentiment_score=score,
        category=category,
        keywords=keywords or [],
    )


def test_build_news_context_summarizes_sentiment_and_keywords():
    news = build_news_context(
        "300750.SZ",
        [
            article("利好扩产", "positive", 0.7, keywords=["扩产", "订单"]),
            article("成本压力", "negative", -0.2, keywords=["成本"]),
        ],
        window_days=7,
    )

    assert news["article_count"] == 2
    assert news["sentiment_label"] == "偏正面"
    assert news["positive_count"] == 1
    assert news["top_keywords"][0]["keyword"] in {"扩产", "订单", "成本"}
    assert news["headlines"][0]["title"] == "利好扩产"


def test_build_factor_context_includes_macro_and_quant_summary():
    news = build_news_context("300750.SZ", [article("订单改善", "positive", 0.5)], window_days=7)
    macro = build_macro_context(
        {"total": 100, "up_count": 66, "down_count": 30, "flat_count": 4, "breadth_ratio": 0.66, "avg_pct_chg": 0.9},
        date(2026, 4, 24),
    )
    quant_factors = build_quant_factor_context({"momentum_score": 72, "risk_penalty_score": 25})

    context = build_factor_context("300750.SZ", news=news, macro=macro, quant_factors=quant_factors)

    assert context["symbol"] == "300750.SZ"
    assert context["macro"]["breadth_label"] == "市场广度偏强"
    assert any("新闻" in item for item in context["summary"])
    assert any(f["label"] == "技术动量" for f in context["quant_factors"])
    assert context["disclaimer"].endswith("不构成投资建议。")


def test_build_factor_context_warns_when_data_missing():
    context = build_factor_context(
        "300750.SZ",
        news=build_news_context("300750.SZ", [], window_days=7),
        macro=build_macro_context(None, None),
        quant_factors=[],
    )

    assert context["warnings"]
    assert context["news"]["article_count"] == 0
    assert context["macro"]["total"] == 0
