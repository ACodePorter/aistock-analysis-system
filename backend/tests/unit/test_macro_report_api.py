import datetime as dt
from typing import Any, List, Optional

import pytest
from fastapi.testclient import TestClient


class MacroReportStorageSpy:
    def __init__(
        self,
        *,
        latest: Optional[dict[str, Any]] = None,
        by_date: Optional[dict[str, Any]] = None,
        history: Optional[List[dict[str, Any]]] = None,
    ) -> None:
        self.latest_result = latest
        self.by_date_result = by_date
        self.history_result = history or []
        self.latest_calls: int = 0
        self.by_date_calls: List[Any] = []
        self.history_limits: List[int] = []

    async def get_latest_macro_report(self) -> Optional[dict[str, Any]]:
        self.latest_calls += 1
        return self.latest_result

    async def get_macro_report_by_date(self, report_date: Any) -> Optional[dict[str, Any]]:
        self.by_date_calls.append(report_date)
        return self.by_date_result

    async def get_macro_reports(self, limit: int = 10, **_: Any) -> List[dict[str, Any]]:
        self.history_limits.append(limit)
        return self.history_result


@pytest.fixture
def make_client(monkeypatch):
    from app.main import app

    def _factory(storage: MacroReportStorageSpy, generator_result: Optional[dict[str, Any]] = None):
        async def fake_get_storage():
            return storage

        monkeypatch.setattr("app.main.get_storage", fake_get_storage)

        async def fake_generate_and_store(target_date: Optional[dt.date] = None):
            fake_generate_and_store.called_with.append(target_date)
            return generator_result

        fake_generate_and_store.called_with = []  # type: ignore[attr-defined]
        monkeypatch.setattr("app.main.generate_and_store_macro_report", fake_generate_and_store)

        client = TestClient(app)
        return client, storage, fake_generate_and_store

    return _factory


def _sample_report(report_date: str, identifier: Optional[str] = None) -> dict[str, Any]:
    return {
        "_id": identifier or report_date,
        "report_date": report_date,
        "generated_at": f"{report_date}T09:00:00+00:00",
        "metrics": {
            "article_count": 12,
            "average_sentiment": 0.18,
            "positive_topic_ratio": 0.42,
        },
        "topics": [
            {
                "topic": "growth",
                "topic_display": "Economic Growth",
                "observation_date": report_date,
                "article_count": 6,
                "avg_sentiment": 0.21,
                "positive_ratio": 0.5,
                "negative_ratio": 0.2,
                "neutral_ratio": 0.3,
                "top_keywords": ["economy", "policy", "exports"],
                "top_entities": {"companies": ["Apple"]},
                "summaries": ["Growth momentum improving"],
                "references": [],
                "sentiment_label": "积极",
            }
        ],
        "top_positive_topics": [],
        "top_negative_topics": [],
        "most_covered_topics": [],
        "model_insights": {"latest_run": None, "best_validation_run": None},
        "highlights": [
            {
                "type": "positive-topic",
                "title": "Growth sentiment strengthening",
                "detail": "Average sentiment 0.21 with half of coverage positive.",
            }
        ],
    }


def test_macro_report_returns_latest_snapshot(make_client):
    latest = _sample_report("2024-03-02")
    history = [{"report_date": "2024-03-02"}, {"report_date": "2024-03-01"}]
    storage = MacroReportStorageSpy(latest=latest, history=history)
    client, storage_ref, generator = make_client(storage)

    response = client.get("/api/macro/report")

    assert response.status_code == 200
    payload = response.json()

    assert payload["report"]["report_date"] == "2024-03-02"
    assert "_id" not in payload["report"]
    assert payload["available_dates"] == ["2024-03-02", "2024-03-01"]
    assert storage_ref.latest_calls == 1
    assert storage_ref.by_date_calls == []
    assert generator.called_with == []  # type: ignore[attr-defined]


def test_macro_report_supports_explicit_date(make_client):
    by_date = _sample_report("2024-03-01")
    storage = MacroReportStorageSpy(by_date=by_date)
    client, storage_ref, generator = make_client(storage)

    response = client.get("/api/macro/report?report_date=2024-03-01")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["report_date"] == "2024-03-01"
    assert storage_ref.by_date_calls
    assert storage_ref.by_date_calls[0].isoformat() == "2024-03-01"
    assert storage_ref.latest_calls == 0
    assert generator.called_with == []  # type: ignore[attr-defined]


def test_macro_report_invalid_date_returns_400(make_client):
    storage = MacroReportStorageSpy()
    client, _, _ = make_client(storage)

    response = client.get("/api/macro/report?report_date=bad-date")

    assert response.status_code == 400
    assert response.json()["detail"] == "report_date must be ISO format YYYY-MM-DD"


def test_macro_report_refresh_generates_new_snapshot(make_client):
    generated = _sample_report("2024-03-03")
    history = [{"report_date": "2024-03-03"}]
    storage = MacroReportStorageSpy(history=history)
    client, storage_ref, generator = make_client(storage, generator_result=generated)

    response = client.get("/api/macro/report?refresh=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["report_date"] == "2024-03-03"
    assert generator.called_with == [None]  # type: ignore[attr-defined]
    # Since generation returned data immediately, storage fallback is optional but available dates still listed
    assert payload["available_dates"] == ["2024-03-03"]