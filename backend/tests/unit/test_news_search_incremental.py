import datetime as dt
from fastapi.testclient import TestClient


def test_news_search_incremental_filters_domain_and_since(monkeypatch):
    # Import app and service
    from app.main import app
    from app.news.news_service import NewsSearchService

    # Prepare fake articles across domains and dates
    base = dt.datetime(2024, 6, 1, 12, 0, 0)
    articles = [
        {
            "title": "A1",
            "url": "https://www.reuters.com/markets/a1",
            "parsed_url": {"host": "www.reuters.com"},
            "published": (base - dt.timedelta(days=3)).isoformat(),  # 2024-05-29T...
        },
        {
            "title": "A2",
            "url": "https://www.bloomberg.com/news/a2",
            "parsed_url": {"host": "www.bloomberg.com"},
            "published": (base - dt.timedelta(days=1)).isoformat(),  # 2024-05-31T...
        },
        {
            "title": "A3",
            "url": "https://example.com/x",
            "parsed_url": {"host": "example.com"},
            "published": (base + dt.timedelta(hours=1)).isoformat(),  # 2024-06-01T13:00
        },
    ]

    async def fake_search_news(self, query, language=None, engines=None, max_results=20,
                               include_domains=None, exclude_domains=None, since=None):  # noqa: D401
        # ignore inputs, return all articles to let router filtering apply
        return list(articles)

    monkeypatch.setattr(NewsSearchService, "search_news", fake_search_news, raising=True)

    client = TestClient(app)

    # include only bloomberg, since 2024-05-30 => should keep only A2 (bloomberg on 05-31)
    payload = {
        "query": "test",
        "include_domains": ["www.bloomberg.com"],
        "since": "2024-05-30",
        "max_results": 10,
    }
    r = client.post("/api/news/search_incremental", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    titles = [a.get("title") for a in data.get("articles", [])]
    assert titles == ["A2"], f"unexpected titles: {titles}"
    # latest_published should be the A2 timestamp
    assert data.get("latest_published", "").startswith("2024-05-31"), data.get("latest_published")

    # exclude example.com, since 2024-05-28 => keeps A1 (reuters) + A2 (bloomberg), filters A3 by exclude
    payload2 = {
        "query": "test",
        "exclude_domains": ["example.com"],
        "since": "2024-05-28",
    }
    r2 = client.post("/api/news/search_incremental", json=payload2)
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    titles2 = [a.get("title") for a in data2.get("articles", [])]
    assert set(titles2) == {"A1", "A2"}
    # latest should be A2 (05-31) in this set
    assert data2.get("latest_published", "").startswith("2024-05-31")
