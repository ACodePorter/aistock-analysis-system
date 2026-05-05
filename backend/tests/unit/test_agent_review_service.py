from app.prediction.services.agent_review_service import build_agent_review


def test_build_agent_review_generates_pending_actions_from_failure_analysis():
    failure_analysis = {
        "severity": "high",
        "headline": "近窗存在 4 个高偏差样本，建议优先人工复核。",
        "sample_count": 8,
        "root_causes": [
            {"code": "direction_miss", "label": "方向判断未命中"},
            {"code": "large_price_error", "label": "价格偏差偏大"},
        ],
        "quality_snapshot": {"quality_grade": "risk", "quality_score": 42.0, "confidence_level": "medium"},
    }

    review = build_agent_review("300750.SZ", failure_analysis=failure_analysis)

    assert review["review_id"].startswith("ar_300750_SZ_")
    assert review["status"] == "pending_gate"
    assert review["priority"] == "high"
    assert review["requires_human_review"] is False
    assert review["requires_gate_pass"] is True
    assert any(action["type"] == "feature_review" for action in review["proposed_actions"])
    assert all(action["requires_approval"] is False for action in review["proposed_actions"])
    assert any(action["requires_gate_pass"] for action in review["proposed_actions"])
    assert "不会自动上线或替换模型" in review["blocked_actions"]
    assert review["disclaimer"].endswith("执行交易。")


def test_build_agent_review_waits_for_samples_when_unknown():
    review = build_agent_review("300750.SZ", failure_analysis={"severity": "unknown", "root_causes": []})

    assert review["status"] == "waiting_for_samples"
    assert review["priority"] == "none"
    assert review["proposed_actions"] == []
    assert review["requires_human_review"] is False


def test_build_agent_review_adds_data_coverage_action():
    review = build_agent_review(
        "300750.SZ",
        failure_analysis={
            "severity": "medium",
            "headline": "已复盘 3 个偏差样本。",
            "root_causes": [],
            "coverage_notes": ["预测窗口缺少关联新闻，事件驱动归因可信度较低。"],
        },
    )

    assert any(action["type"] == "data_coverage_review" for action in review["proposed_actions"])
    assert review["priority"] == "medium"