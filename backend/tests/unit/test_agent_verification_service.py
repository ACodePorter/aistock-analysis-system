from app.prediction.services.agent_verification_service import build_agent_verification


def base_review():
    return {
        "review_id": "ar_300750_SZ_test",
        "status": "pending_gate",
        "blocked_actions": ["不会自动上线或替换模型"],
    }


def test_build_agent_verification_allows_candidate_when_evidence_complete():
    feature_snapshot = {
        "snapshot_id": "fs_300750_SZ_test",
        "as_of_date": "2026-04-24",
        "completeness_score": 100.0,
        "lineage": {
            "as_of_date": "2026-04-24",
            "target_date": "2026-04-30",
            "signal_date": "2026-04-24",
            "price_trade_date": "2026-04-24",
        },
        "factor_counts": {"news_articles": 2, "market_breadth_total": 100, "quant_factors": 5},
    }
    failure_analysis = {"sample_count": 5, "high_deviation_count": 1}

    result = build_agent_verification(base_review(), failure_analysis=failure_analysis, feature_snapshot=feature_snapshot)

    assert result["verification_status"] == "passed"
    assert result["gate_result"]["status"] == "candidate_allowed"
    assert result["gate_result"]["next_state"] == "candidate"
    assert all(check["status"] == "passed" for check in result["checks"])


def test_build_agent_verification_blocks_without_snapshot():
    result = build_agent_verification(base_review(), failure_analysis={"sample_count": 3})

    assert result["verification_status"] == "failed"
    assert result["gate_result"]["status"] == "blocked"
    assert "snapshot_presence" in result["gate_result"]["failed_checks"]


def test_build_agent_verification_only_observes_when_news_missing():
    feature_snapshot = {
        "snapshot_id": "fs_300750_SZ_test",
        "as_of_date": "2026-04-24",
        "completeness_score": 83.3,
        "lineage": {
            "as_of_date": "2026-04-24",
            "target_date": "2026-04-30",
            "signal_date": "2026-04-24",
            "price_trade_date": "2026-04-24",
        },
        "factor_counts": {"news_articles": 0, "market_breadth_total": 100, "quant_factors": 5},
    }

    result = build_agent_verification(base_review(), failure_analysis={"sample_count": 2}, feature_snapshot=feature_snapshot)

    assert result["verification_status"] == "warning"
    assert result["gate_result"]["status"] == "observation_only"
    assert "factor_evidence_alignment" in result["gate_result"]["warning_checks"]
