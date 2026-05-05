from fastapi.testclient import TestClient
from app.main import app
from app.core.db import engine


def setup_module(module):
    # Ensure symbol has no prices to trigger fallback; wipe table rows for a test symbol
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM prices_daily WHERE symbol='ZZTEST.SZ'")


def test_report_endpoint_fallback_no_data(monkeypatch):
    # Monkeypatch fetch_daily to return empty DataFrame to force diagnostics skeleton
    import pandas as pd
    from app.data import data_source
    def _empty_fetch(sym, start_date=None):
        return pd.DataFrame(columns=['symbol','trade_date','open','high','low','close','pct_chg','vol','amount'])
    monkeypatch.setattr(data_source, 'fetch_daily', _empty_fetch)
    client = TestClient(app)
    r = client.get('/api/report/ZZTEST.SZ/full?timeRange=5d&showDiagnostics=1')
    assert r.status_code == 200, r.text
    js = r.json()
    assert js['symbol'] == 'ZZTEST.SZ'
    assert js['diagnostics']['reason'] == 'no_price_data'
    assert js['price_data'] == []


def teardown_module(module):
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM prices_daily WHERE symbol='ZZTEST.SZ'")
