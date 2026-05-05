import asyncio


def test_openclaw_mode_uses_agentic_pipeline(monkeypatch):
    from app.news.news_service import NewsSearchService

    class FakeRetriever:
        async def retrieve(self, question, max_results=20, **kwargs):
            return [
                {
                    "title": "A",
                    "url": "https://www.bloomberg.com/news/a",
                    "snippet": "A",
                    "published": "2024-06-01T10:00:00",
                    "source": "fake",
                },
                {
                    "title": "B",
                    "url": "https://example.com/b",
                    "snippet": "B",
                    "published": "2024-05-01T10:00:00",
                    "source": "fake",
                },
            ][:max_results]

    monkeypatch.setenv("WEB_RETRIEVAL_MODE", "openclaw")
    monkeypatch.setattr("app.news.news_service.AgenticWebRetriever", FakeRetriever)

    svc = NewsSearchService()
    out = asyncio.run(
        svc.search_news(
            query="test",
            include_domains=["bloomberg.com"],
            since="2024-05-30",
            max_results=10,
        )
    )
    assert len(out) == 1
    assert out[0]["title"] == "A"
    assert out[0].get("source") == "fake"

    monkeypatch.delenv("WEB_RETRIEVAL_MODE", raising=False)
