import sys, pathlib, json
from types import SimpleNamespace

import pytest

# Ensure backend path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # add backend/

from app.routers import movers  # type: ignore

class DummySession:
    """Very small dummy DB session to satisfy dependency; returns empty data sets.
    We only validate response structure, not data correctness here."""
    def execute(self, *args, **kwargs):
        class R:
            def scalar(self_inner):
                return None
            def mappings(self_inner):
                return []
        return R()

    def close(self):
        pass

@pytest.fixture
def db():
    return DummySession()

def test_analyze_response_shape(db):
    resp = movers.analyze(limit=3, news_days=1, per_symbol_news=1, db=db)
    # Required top-level keys
    for key in ["daily","weekly","summaries","recommendations","sector_stats","methodology"]:
        assert key in resp, f"Missing key: {key}"
    # recommendations structure
    assert isinstance(resp["recommendations"], list)
    if resp["recommendations"]:
        r0 = resp["recommendations"][0]
        for k in ["symbol", "score", "components"]:
            assert k in r0
        assert "week_momentum" in r0["components"], "components.week_momentum missing"
    # methodology minimal
    assert resp["methodology"].get("steps")
