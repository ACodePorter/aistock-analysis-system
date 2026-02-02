"""Agent 报告持久化工具函数。

职责:
- 从 agent_reports 目录读取最新或指定 JSON 文件
- 解析并写入/更新 AgentDailyReport 表 (按 report_date upsert)
- 提供 backfill 方法扫描历史文件

注意: 这里使用 SQLAlchemy Core/ORM 简单操作, 不做复杂事务; 单行 upsert 可安全重试。
"""
from __future__ import annotations
import json, os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Optional
from sqlalchemy import select
from ..core.db import SessionLocal
from ..core.models import AgentDailyReport

REPORTS_DIR = Path(__file__).resolve().parent.parent / 'agent_reports'

logger = logging.getLogger(__name__)
# Ensure a dedicated rotating file handler for agent persistence diagnostics
try:
    project_root = Path(__file__).resolve().parents[3]
    logs_dir = project_root / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / 'agent_persistence.log'
    # Add handler only once
    if not any(getattr(h, 'baseFilename', None) == str(log_file) for h in logger.handlers):
        fh = RotatingFileHandler(str(log_file), maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
except Exception:
    # Fail quietly—do not break application startup if logging setup fails
    pass


def _infer_report_date(payload: dict) -> date:
    # 优先 finished_at / started_at, 否则今天
    for k in ('finished_at', 'started_at'):
        v = payload.get(k)
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace('Z','+00:00'))
                return dt.date()
            except Exception:
                continue
    return datetime.utcnow().date()


def persist_agent_report(json_path: Path, markdown_path: Optional[Path] = None, job_id: Optional[str] = None) -> Optional[int]:
    if not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding='utf-8'))
    except Exception:
        return None
    report_date = _infer_report_date(payload)
    stock_reports = payload.get('stock_reports') or payload.get('stock_reports'.replace('stock_reports','stock_reports'))  # defensive
    macro = payload.get('macro')
    analytics = payload.get('analytics')
    diagnostics = payload.get('diagnostics')
    top20_count = payload.get('top20_count') or (stock_reports and len(stock_reports)) or None
    markdown_text = None
    if markdown_path and markdown_path.exists():
        try:
            markdown_text = markdown_path.read_text(encoding='utf-8')
        except Exception:
            pass
    with SessionLocal() as session:
        existing = session.execute(select(AgentDailyReport).where(AgentDailyReport.report_date==report_date)).scalar_one_or_none()
        if existing:
            existing.generated_at = datetime.utcnow()
            existing.job_id = job_id or existing.job_id
            existing.top20_count = top20_count
            existing.stock_reports_json = json.dumps(stock_reports, ensure_ascii=False) if stock_reports else None
            existing.macro_json = json.dumps(macro, ensure_ascii=False) if macro else None
            existing.analytics_json = json.dumps(analytics, ensure_ascii=False) if analytics else None
            existing.diagnostics_json = json.dumps(diagnostics, ensure_ascii=False) if diagnostics else None
            if markdown_text:
                existing.markdown = markdown_text
            session.commit()
            # Optional Mongo upsert (best-effort)
            try:
                _maybe_upsert_mongo(report_date, job_id, payload, markdown_text)
            except Exception:
                pass
            return existing.id
        row = AgentDailyReport(
            report_date=report_date,
            job_id=job_id,
            top20_count=top20_count,
            stock_reports_json=json.dumps(stock_reports, ensure_ascii=False) if stock_reports else None,
            macro_json=json.dumps(macro, ensure_ascii=False) if macro else None,
            analytics_json=json.dumps(analytics, ensure_ascii=False) if analytics else None,
            diagnostics_json=json.dumps(diagnostics, ensure_ascii=False) if diagnostics else None,
            markdown=markdown_text
        )
        session.add(row)
        session.commit()
        # Optional Mongo upsert (best-effort)
        try:
            _maybe_upsert_mongo(report_date, job_id, payload, markdown_text)
        except Exception:
            pass
        return row.id


def backfill_agent_reports(limit: Optional[int] = None) -> int:
    if not REPORTS_DIR.exists():
        return 0
    files = sorted(REPORTS_DIR.glob('agent_report_*.json'), key=lambda p: p.stat().st_mtime)
    if limit:
        files = files[-limit:]
    count = 0
    for jf in files:
        md_candidate = jf.with_suffix('.md')
        if persist_agent_report(jf, md_candidate):
            count += 1
    return count


# --- Optional MongoDB persistence ---
def _maybe_upsert_mongo(report_date: date, job_id: Optional[str], payload: dict, markdown_text: Optional[str]):
    """Best-effort upsert into MongoDB for agent daily reports.

    Controlled by env AGENT_MONGO_ENABLE (default: '1'). Safe no-op on import/connection errors.
    """
    enabled = os.getenv("AGENT_MONGO_ENABLE", "1").lower() in ("1", "true", "yes")
    if not enabled:
        logger.info("AGENT_MONGO_ENABLE disabled; skipping Mongo upsert")
        return

    try:
        from pymongo import MongoClient
    except Exception as e:
        logger.warning("pymongo not available; cannot upsert to MongoDB: %s", e)
        return

    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", os.getenv("MONGO_DB", "aistock_news"))
    coll_name = os.getenv("AGENT_MONGO_COLLECTION", "agent_daily_reports")
    # Build document
    doc = {
        "report_date": report_date.isoformat(),
        "job_id": job_id,
        "generated_at": datetime.utcnow().isoformat(),
        "version": payload.get("version"),
        "top20_count": payload.get("top20_count"),
        "stock_reports": payload.get("stock_reports"),
        "macro": payload.get("macro"),
        "analytics": payload.get("analytics"),
        "diagnostics": payload.get("diagnostics"),
        "markdown": markdown_text,
        "source": "agent",
    }
    try:
        logger.info("Attempting Mongo upsert: uri=%s db=%s coll=%s report_date=%s", mongo_uri, db_name, coll_name, doc["report_date"])
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=2000)
        db = client[db_name]
        coll = db[coll_name]
        result = coll.update_one({"report_date": doc["report_date"]}, {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}}, upsert=True)
        if result.acknowledged:
            logger.info("Mongo upsert acknowledged. matched=%s modified=%s upserted_id=%s", getattr(result, 'matched_count', None), getattr(result, 'modified_count', None), getattr(result, 'upserted_id', None))
        else:
            logger.warning("Mongo upsert not acknowledged for report_date=%s", doc["report_date"])
    except Exception:
        logger.exception("Exception during Mongo upsert for report_date=%s", doc["report_date"]) 
    finally:
        try:
            client.close()
        except Exception:
            pass
