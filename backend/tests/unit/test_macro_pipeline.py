from datetime import date, datetime

from app.reports.macro_pipeline import MacroObservation, _ensure_iso, _normalize_sequence


def test_normalize_sequence_filters_empty():
    values = ["  Alpha  ", "", None, "Beta", "  "]
    assert _normalize_sequence(values) == ["Alpha", "Beta"]


def test_ensure_iso_handles_various_inputs():
    today = date(2024, 6, 1)
    dt = datetime(2024, 6, 1, 12, 0)
    assert _ensure_iso(today) == "2024-06-01T00:00:00"
    assert _ensure_iso(dt) == "2024-06-01T12:00:00"
    assert _ensure_iso("custom") == "custom"


def test_macro_observation_to_dict_generates_slug():
    obs = MacroObservation(
        topic="Global Macro",
        observation_date=date(2024, 6, 1),
        article_count=3,
        features={"avg_sentiment": 0.2},
        top_keywords=["growth"],
        top_entities={"companies": [], "locations": [], "people": []},
        summaries=["summary"],
        references=[],
    )
    payload = obs.to_dict()
    assert payload["topic"] == "global_macro"
    assert payload["topic_display"] == "Global Macro"
    assert payload["observation_date"] == "2024-06-01"
