from fastapi.testclient import TestClient


def test_api_news_search_route_openclaw(monkeypatch):
    from app.main import app
    from app.news.news_service import NewsSearchService

    async def fake_search_news(self, query, **kwargs):
        return [{"title": "Doc", "url": "https://example.com/doc", "source": "openclaw_web"}]

    monkeypatch.setattr(NewsSearchService, "search_news", fake_search_news, raising=True)
    client = TestClient(app)
    response = client.post("/api/news/search", json={"query": "test", "max_results": 5})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["articles"][0]["source"] == "openclaw_web"
