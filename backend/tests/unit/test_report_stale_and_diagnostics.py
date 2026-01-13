from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import engine

TEST_SYMBOL = 'STALE1.SZ'


def setup_module(module):
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM prices_daily WHERE symbol='%s'" % TEST_SYMBOL)
        # Insert a stale row 40 days ago so 5d window misses it
        stale_day = date.today() - timedelta(days=40)
        conn.exec_driver_sql(
            """
            INSERT INTO prices_daily(symbol, trade_date, open, high, low, close, pct_chg, vol, amount)
            VALUES (%(symbol)s, %(trade_date)s, 10, 11, 9, 10.5, 1.23, 1000, 500000)
            """,
            {"symbol": TEST_SYMBOL, "trade_date": stale_day}
        )


def test_report_stale_fallback():
    client = TestClient(app)
    r = client.get(f"/api/report/{TEST_SYMBOL}/full?timeRange=5d&showDiagnostics=1")
    assert r.status_code == 200, r.text
    js = r.json()
    # Should use stale fallback
    assert js.get('stale') is True
    assert js['diagnostics']['stale_used'] is True
    assert len(js['price_data']) >= 1


def test_report_diagnostics_no_data(monkeypatch):
    # Force fetch_daily to return empty and ensure no DB rows for another symbol
    from app import data_source
    import pandas as pd
    symbol2 = 'NODATA1.SZ'
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM prices_daily WHERE symbol='%s'" % symbol2)
    def _empty_fetch(sym):
        return pd.DataFrame(columns=['symbol','trade_date','open','high','low','close','pct_chg','vol','amount'])
    monkeypatch.setattr(data_source, 'fetch_daily', _empty_fetch)
    client = TestClient(app)
    r = client.get(f"/api/report/{symbol2}/full?timeRange=5d&showDiagnostics=1")
    assert r.status_code == 200
    js = r.json()
    assert js['diagnostics']['reason'] == 'no_price_data'
    assert js['diagnostics']['external_fetch_rows'] == 0


def teardown_module(module):
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM prices_daily WHERE symbol='%s'" % TEST_SYMBOL)
        conn.exec_driver_sql("DELETE FROM prices_daily WHERE symbol='NODATA1.SZ'")
