
def test_openclaw_crawler_maps_results(monkeypatch):
    from app.crawlers.crawlers import OpenClawCrawler

    class FakeRetriever:
        def retrieve_sync(self, question, max_results=10, **kwargs):
            return [
                {
                    "title": "News",
                    "url": "https://example.com/news",
                    "summary": "brief",
                    "published": "2024-06-01T10:00:00",
                }
            ]

    monkeypatch.setattr("app.agent.web_agent.AgenticWebRetriever", FakeRetriever)

    crawler = OpenClawCrawler()
    rows = crawler.crawl_stock_news("600000.SH", "浦发银行", 5)
    assert rows[0]["source"] == "openclaw_web"
    assert rows[0]["stock_code"] == "600000.SH"
    assert rows[0]["content"] == "brief"
