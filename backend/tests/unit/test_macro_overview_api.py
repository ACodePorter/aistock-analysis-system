import pytest
from fastapi.testclient import TestClient


class DummyStorage:
    def __init__(self):
        self.observations_called_with = []
        self.model_runs_called_with = []

    async def get_macro_observations(self, limit: int = 8):
        self.observations_called_with.append(limit)
        return [
            {
                "topic": "growth",
                "topic_display": "Global Growth",
                "observation_date": "2024-03-01",
                "article_count": 5,
                "features": {
                    "avg_sentiment": 0.12,
                    "positive_ratio": 0.4,
                    "negative_ratio": 0.2,
                    "neutral_ratio": 0.4,
                    "relevance_mean": 0.73,
                },
                "top_keywords": [f"kw{i}" for i in range(12)],
                "top_entities": {"US": 3, "China": 2},
                "summaries": ["Summary A", "Summary B", "Summary C"],
                "references": ["http://example.com/a", "http://example.com/b"],
            },
            {
                "topic": "growth",
                "topic_display": "Global Growth",
                "observation_date": "2024-03-02",
                "article_count": 6,
                "features": {
                    "avg_sentiment": 0.2,
                    "positive_ratio": 0.5,
                    "negative_ratio": 0.1,
                    "neutral_ratio": 0.4,
                    "relevance_mean": 0.81,
                },
                "top_keywords": [f"kw{i}" for i in range(12)],
                "top_entities": {"US": 5, "China": 4},
                "summaries": ["Summary C", "Summary D", "Summary E", "Summary F"],
                "references": ["http://example.com/c", "http://example.com/d", "http://example.com/e"],
            },
            {
                "topic": "inflation",
                "topic_display": "Inflation Watch",
                "observation_date": "2024-02-28",
                "article_count": 3,
                "features": {
                    "avg_sentiment": -0.1,
                    "positive_ratio": 0.2,
                    "negative_ratio": 0.6,
                    "neutral_ratio": 0.2,
                    "relevance_mean": 0.65,
                },
                "top_keywords": ["cpi", "prices"],
                "top_entities": {"US": 2},
                "summaries": ["Inflation remains elevated"],
                "references": ["http://example.com/inf"],
            },
        ]

    async def get_macro_model_runs(self, limit: int = 5):
        self.model_runs_called_with.append(limit)
        return [
            {
                "model_name": "macro-lstm",
                "run_date": "2024-03-01T10:00:00",
                "metrics": {"rmse": 0.12},
                "coefficients": {"gdp": 0.6},
                "calibration": {"alpha": 0.1},
                "notes": ["Improved feature set"],
            },
            {
                "model_name": "macro-transformer",
                "run_date": "2024-02-28T11:30:00",
                "metrics": {"rmse": 0.09},
                "coefficients": {"inflation": 0.4},
                "calibration": {"beta": 0.2},
                "notes": ["Baseline"],
            },
        ]


@pytest.fixture
def client(monkeypatch):
    from app.main import app

    storage = DummyStorage()

    async def fake_get_storage():
        return storage

    monkeypatch.setattr("app.main.get_storage", fake_get_storage)
    return TestClient(app)


def test_macro_overview_returns_latest_observations(client):
    response = client.get("/api/macro/overview?limit=5&model_limit=2")
    assert response.status_code == 200

    payload = response.json()
    assert payload["storage_available"] is True
    assert payload["latest_observation_date"] == "2024-03-02"

    topics = payload["topics"]
    assert len(topics) == 2

    growth_topic = next(item for item in topics if item["topic"] == "growth")
    assert growth_topic["article_count"] == 6
    assert growth_topic["avg_sentiment"] == 0.2
    assert growth_topic["top_keywords"] == [f"kw{i}" for i in range(10)]
    assert len(growth_topic["summaries"]) == 4
    assert len(payload["model_runs"]) == 2
    assert payload["model_runs"][0]["model_name"] == "macro-lstm"
    