from datetime import date
from types import SimpleNamespace

from app.prediction.services.feature_snapshot_service import build_feature_snapshot


def test_build_feature_snapshot_tracks_lineage_and_coverage():
    prediction = SimpleNamespace(
        predict_date=date(2026, 4, 24),
        target_date=date(2026, 4, 30),
        horizon="5d",
        direction_prob_up=0.63,
        predicted_return=0.028,
        confidence=0.71,
    )
    signal = SimpleNamespace(
        signal_date=date(2026, 4, 24),
        action="buy",
        score=68.0,
        risk_score=42.0,
        rank=3,
    )
    latest_price = SimpleNamespace(
        trade_date=date(2026, 4, 24),
        close=25.3,
        pct_chg=1.2,
        vol=1000000,
        amount=25300000,
    )
    factor_context = {
        "news": {"article_count": 3},
        "macro": {"total": 100, "breadth_label": "市场广度偏强"},
        "quant_factors": [{"key": "momentum_score", "label": "技术动量", "impact": "正向"}],
    }

    snapshot = build_feature_snapshot(
        "300750.SZ",
        prediction=prediction,
        signal=signal,
        latest_price=latest_price,
        factor_context=factor_context,
    )

    assert snapshot["symbol"] == "300750.SZ"
    assert snapshot["snapshot_id"].startswith("fs_300750_SZ_")
    assert snapshot["as_of_date"] == "2026-04-24"
    assert snapshot["prediction"]["target_date"] == "2026-04-30"
    assert snapshot["signal"]["action"] == "buy"
    assert snapshot["factor_counts"]["news_articles"] == 3
    assert snapshot["completeness_score"] == 100.0
    assert all(item["available"] for item in snapshot["coverage"])
    assert snapshot["disclaimer"].endswith("不构成投资建议。")


def test_build_feature_snapshot_warns_for_sparse_context():
    snapshot = build_feature_snapshot(
        "300750.SZ",
        latest_price=SimpleNamespace(trade_date=date(2026, 4, 24), close=25.3),
        factor_context={"news": {"article_count": 0}, "macro": {"total": 0}, "quant_factors": []},
    )

    assert snapshot["prediction"] is None
    assert snapshot["completeness_score"] < 60
    assert any("缺少最新预测记录" in item for item in snapshot["warnings"])
    assert any(item["label"] == "新闻因子" and not item["available"] for item in snapshot["coverage"])