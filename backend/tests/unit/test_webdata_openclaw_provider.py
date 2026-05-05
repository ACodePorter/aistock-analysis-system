
def test_openclaw_search_provider_returns_docs(monkeypatch):
    from app.utils.web_data_providers import OpenClawSearchProvider

    class FakeRetriever:
        def retrieve_sync(self, question, max_results=10, **kwargs):
            return [
                {
                    "title": "Doc",
                    "url": "https://example.com/doc",
                    "summary": "summary",
                    "content": "content",
                }
            ]

    monkeypatch.setattr("app.agent.web_agent.AgenticWebRetriever", FakeRetriever)

    provider = OpenClawSearchProvider()
    result = provider.query("test", limit=5)
    assert result.success is True
    assert result.data["mode"] == "openclaw_web"
    assert result.data["results"][0]["title"] == "Doc"
