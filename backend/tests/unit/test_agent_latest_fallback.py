from datetime import datetime
from app.core.db import init_database, engine, SessionLocal
from app.core.models import AgentJob, AgentJobStatus


def setup_module(module):
    init_database()
    # Clean jobs
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM agent_jobs")
    # Insert a job without any report files existing
    with SessionLocal() as session:
        job = AgentJob(job_id='testjob1', status=AgentJobStatus.FINISHED.value, created_at=datetime.utcnow())
        session.add(job)
        session.commit()


def test_agent_latest_no_reports():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get('/api/agent/latest')
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert 'report' in data
    assert data['report'].get('fallback') in ('agent_job_row_no_report_files','empty')


def teardown_module(module):
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM agent_jobs")
