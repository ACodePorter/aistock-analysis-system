from fastapi.testclient import TestClient


def test_retrieval_health_uses_openclaw(monkeypatch):
    from app.main import app

    class FakeRetriever:
        async def health_check(self, query="A股 公司 新闻"):
            return {
                "ok": True,
                "search_results": 3,
                "readable_results": 1,
            }

    monkeypatch.setattr("app.agent.web_agent.AgenticWebRetriever", FakeRetriever)
    monkeypatch.setattr("app.routers.news.AgenticWebRetriever", FakeRetriever, raising=False)

    client = TestClient(app)
    response = client.get("/api/news/retrieval/health")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["retrieval_mode"] == "openclaw_web"
    assert payload["results_count"] == 3
