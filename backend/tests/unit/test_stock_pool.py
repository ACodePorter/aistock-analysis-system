import os, json, datetime, subprocess, sys
from pathlib import Path

# Basic smoke tests for stock pool + profile logic

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
SCRIPTS = BACKEND / 'scripts'

# We assume DB is already initialized by other tests / startup routines.


def test_update_stock_pool_script_exists():
    assert (SCRIPTS / 'update_stock_pool.py').exists(), 'update_stock_pool.py missing'


def test_enrich_stock_profile_script_exists():
    assert (SCRIPTS / 'enrich_stock_profile.py').exists(), 'enrich_stock_profile.py missing'


def test_stock_pool_update_and_profile_creation(monkeypatch, tmp_path):
    # Create a fake agent report with 2 symbols
    reports_dir = ROOT / 'agent_reports'
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / 'agent_report_test_stock_pool.json'
    fake_report = {
        'finished_at': datetime.datetime.utcnow().isoformat(),
        'stock_reports': [
            {'symbol': 'TEST1.SH', 'name': '测试一', 'report': {'score': 0.8, 'factors': []}},
            {'symbol': 'TEST2.SZ', 'name': '测试二', 'report': {'score': 0.6, 'factors': []}},
        ]
    }
    report_path.write_text(json.dumps(fake_report, ensure_ascii=False), encoding='utf-8')

    # Run update_stock_pool (should create members + trigger enrichment for new symbols)
    rc = subprocess.call([sys.executable, str(SCRIPTS / 'update_stock_pool.py')])
    assert rc == 0, 'update_stock_pool script failed'

    # Import DB session + models to assert rows
    sys.path.append(str(BACKEND))
    from app.core.db import SessionLocal  # type: ignore
    from app.core.models import StockPoolMember, StockProfile  # type: ignore

    with SessionLocal() as session:
        members = session.query(StockPoolMember).filter(StockPoolMember.symbol.in_(['TEST1.SH','TEST2.SZ'])).all()
        assert len(members) >= 2, 'Pool members not created'
        profiles = session.query(StockProfile).filter(StockProfile.symbol.in_(['TEST1.SH','TEST2.SZ'])).all()
        assert len(profiles) >= 2, 'Profiles not created by enrichment trigger'
