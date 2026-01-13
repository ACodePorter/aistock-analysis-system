from fastapi.testclient import TestClient
import json, datetime, sys, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
SCRIPTS = BACKEND / 'scripts'


def _ensure_seed():
    # Create a minimal fake agent report to drive pool update if none existing
    reports_dir = ROOT / 'agent_reports'
    reports_dir.mkdir(exist_ok=True)
    rpt = reports_dir / 'agent_report_api_pool.json'
    data = {
        'finished_at': datetime.datetime.utcnow().isoformat(),
        'stock_reports': [
            {'symbol': 'POOL1.SH', 'report': {'score': 0.5, 'factors': []}},
            {'symbol': 'POOL2.SZ', 'report': {'score': 0.7, 'factors': []}},
        ]
    }
    rpt.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    subprocess.call([sys.executable, str(SCRIPTS / 'update_stock_pool.py')])


def test_stock_pool_list(monkeypatch):
    from app.main import app
    _ensure_seed()
    client = TestClient(app)
    r = client.get('/api/stock-pool?limit=10')
    assert r.status_code == 200
    payload = r.json()
    assert 'rows' in payload and isinstance(payload['rows'], list)
    assert payload['total'] >= len(payload['rows'])


def test_stock_profile_fetch():
    from app.main import app
    client = TestClient(app)
    # ensure profile exists via refresh
    resp = client.post('/api/stock-profile/POOL1.SH/refresh')
    assert resp.status_code == 200
    prof = client.get('/api/stock-profile/POOL1.SH')
    assert prof.status_code == 200
    data = prof.json()
    assert data['symbol'] == 'POOL1.SH'
    assert 'last_refreshed' in data
