from fastapi.testclient import TestClient


def test_webdata_search_route_openclaw(monkeypatch):
    from app.main import app

    class FakeResult:
        success = True
        source = "openclaw_search"
        latency_ms = 12
        cached = False
        data = {"keyword": "test", "results": [{"title": "Doc", "url": "https://example.com/doc"}]}
        error = None

    monkeypatch.setattr("app.routers.webdata.query_search", lambda *args, **kwargs: FakeResult())
    client = TestClient(app)
    response = client.get("/api/webdata/search", params={"q": "test"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert payload["source"] == "openclaw_search"
    assert payload["data"]["results"][0]["title"] == "Doc"

