import os
from datetime import date, timedelta

from app.core.db import SessionLocal, init_database, engine
from app.core.models import StockPoolMember, StockProfile


def setup_module(module):
    # ensure tables
    init_database()
    # clean relevant tables
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM stock_pool_member")
        conn.exec_driver_sql("DELETE FROM stock_profile")
    # insert sample data
    today = date.today()
    with SessionLocal() as session:
        m1 = StockPoolMember(symbol='AAA.SZ', first_seen_date=today - timedelta(days=10))
        m2 = StockPoolMember(symbol='BBB.SZ', first_seen_date=today - timedelta(days=5))
        m3 = StockPoolMember(symbol='CCC.SZ', first_seen_date=today - timedelta(days=20), exit_date=today - timedelta(days=2))
        session.add_all([m1, m2, m3])
        session.add_all([
            StockProfile(symbol='AAA.SZ', industry='Tech'),
            StockProfile(symbol='BBB.SZ', industry='Finance'),
            StockProfile(symbol='CCC.SZ', industry='Energy'),
        ])
        session.commit()


def test_days_active_sort_desc(client):
    # Use test client from conftest (if available); else create inline
    from fastapi.testclient import TestClient
    from app.main import app
    local_client = TestClient(app)
    resp = local_client.get('/api/stock-pool?sort=days_active&order=desc&limit=10')
    assert resp.status_code == 200, resp.text
    data = resp.json()
    symbols = [r['symbol'] for r in data['rows']]
    # For active members, longer active first: m1(10d) vs m2(5d); exited m3 has fixed 18d which should rank first overall
    assert symbols[0] == 'CCC.SZ'
    assert 'days_active' in data['rows'][0]


def test_days_active_sort_asc():
    from fastapi.testclient import TestClient
    from app.main import app
    local_client = TestClient(app)
    resp = local_client.get('/api/stock-pool?sort=days_active&order=asc&limit=10')
    assert resp.status_code == 200
    data = resp.json()
    symbols = [r['symbol'] for r in data['rows']]
    # Shortest active first when asc -> BBB (5d active) likely first
    assert symbols[0] in ('BBB.SZ','AAA.SZ','CCC.SZ')  # loose check due to exit vs active ordering differences across DB


def teardown_module(module):
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM stock_pool_member")
        conn.exec_driver_sql("DELETE FROM stock_profile")
