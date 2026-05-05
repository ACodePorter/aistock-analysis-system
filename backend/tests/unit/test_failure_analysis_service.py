from app.prediction.services.failure_analysis_service import build_failure_analysis


def test_build_failure_analysis_identifies_direction_and_bias_causes():
    analysis = build_failure_analysis(
        "300750.SZ",
        [
            {
                "target_date": "2026-04-24",
                "error_pct": 9.2,
                "signed_error_pct": 9.2,
                "direction_correct": False,
                "interval_hit": False,
                "deviation_level": "high",
            },
            {
                "target_date": "2026-04-23",
                "error_pct": 2.0,
                "signed_error_pct": 2.0,
                "direction_correct": True,
                "interval_hit": True,
                "deviation_level": "low",
            },
        ],
        quality={"quality_grade": "risk", "quality_score": 42.0, "confidence_level": "medium"},
    )

    assert analysis["severity"] == "high"
    assert analysis["high_deviation_count"] == 1
    assert analysis["direction_miss_count"] == 1
    assert any(cause["code"] == "direction_miss" for cause in analysis["root_causes"])
    assert any(cause["code"] == "large_price_error" for cause in analysis["root_causes"])
    assert analysis["quality_snapshot"]["quality_grade"] == "risk"
    assert analysis["disclaimer"].endswith("不会自动调整生产模型。")


def test_build_failure_analysis_reports_missing_feature_coverage():
    analysis = build_failure_analysis(
        "300750.SZ",
        [{"error_pct": 1.0, "signed_error_pct": -1.0, "direction_correct": True, "interval_hit": True, "deviation_level": "low"}],
        feature_snapshot={
            "completeness_score": 66.7,
            "factor_counts": {"news_articles": 0, "market_breadth_total": 0, "quant_factors": 3},
        },
    )

    assert analysis["severity"] == "low"
    assert analysis["coverage_notes"]
    assert any("关联新闻" in note for note in analysis["coverage_notes"])
    assert any("补齐缺失因子" in action for action in analysis["next_actions"])


def test_build_failure_analysis_handles_empty_cases():
    analysis = build_failure_analysis("300750.SZ", [])

    assert analysis["severity"] == "unknown"
    assert analysis["sample_count"] == 0
    assert analysis["root_causes"] == []
    assert analysis["next_actions"] == ["等待目标日实际收盘回填后再生成失败归因。"]