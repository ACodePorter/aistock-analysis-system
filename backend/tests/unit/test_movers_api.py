import sys, pathlib
from fastapi.testclient import TestClient
import types

# ensure path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from app.main import app  # type: ignore
from app.routers import movers  # type: ignore

# Build a dummy DB session with minimal interface
class DummySession:
    def __init__(self):
        pass
    def execute(self, *a, **k):
        class R:
            def scalar(self_inner): return None
            def mappings(self_inner): return []
        return R()
    def close(self):
        pass

def override_get_db():
    db = DummySession()
    try:
        yield db
    finally:
        db.close()

# Override dependency
app.dependency_overrides[movers.get_db] = override_get_db

client = TestClient(app)

def test_movers_analyze_api_shape():
    r = client.get("/api/movers/analyze")
    assert r.status_code == 200
    data = r.json()
    for key in ["daily","weekly","summaries","recommendations","sector_stats","methodology"]:
        assert key in data
    if data["recommendations"]:
        first = data["recommendations"][0]
        assert all(k in first for k in ("symbol","score","components"))
        assert "week_momentum" in first["components"]
