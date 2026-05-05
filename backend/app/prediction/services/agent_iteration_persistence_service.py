"""Persistence helpers for agent iteration snapshots and review replay."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from ...core.models import (
    AgentReviewRun,
    AgentVerificationCheck,
    FailureAnalysisRecord,
    FeatureSnapshot,
)

logger = logging.getLogger(__name__)

REQUIRED_TABLES = {
    "feature_snapshots",
    "failure_analyses",
    "agent_review_runs",
    "agent_verification_checks",
}


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stable_id(prefix: str, symbol: str, payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{symbol.replace('.', '_')}_{digest}"


def _tables_ready(session: Session) -> tuple[bool, list[str]]:
    inspector = inspect(session.get_bind())
    existing = set(inspector.get_table_names())
    missing = sorted(REQUIRED_TABLES - existing)
    return not missing, missing


def _analysis_id(symbol: str, failure_analysis: dict, lookback_days: int) -> str:
    root_causes = failure_analysis.get("root_causes") or []
    return _stable_id("fa", symbol, {
        "lookback_days": lookback_days,
        "severity": failure_analysis.get("severity"),
        "sample_count": failure_analysis.get("sample_count"),
        "high_deviation_count": failure_analysis.get("high_deviation_count"),
        "root_causes": [cause.get("code") for cause in root_causes],
        "quality_snapshot": failure_analysis.get("quality_snapshot"),
    })


def persist_agent_iteration_bundle(
    session: Session,
    *,
    symbol: str,
    lookback_days: int,
    feature_snapshot: Optional[dict],
    failure_analysis: Optional[dict],
    agent_review: Optional[dict],
) -> dict:
    """Persist the latest snapshot, failure analysis, review run, and checks.

    The function is intentionally best-effort. Missing migration tables return a skipped
    status so read APIs can continue serving generated JSON contracts.
    """
    ready, missing = _tables_ready(session)
    if not ready:
        return {"status": "skipped", "reason": "migration_not_applied", "missing_tables": missing}
    if not agent_review:
        return {"status": "skipped", "reason": "missing_agent_review"}

    sym = symbol.upper()
    persisted: dict[str, Any] = {"status": "persisted"}
    try:
        snapshot_id = None
        if feature_snapshot:
            snapshot_id = feature_snapshot.get("snapshot_id")
            prediction = feature_snapshot.get("prediction") or {}
            snapshot = session.execute(
                select(FeatureSnapshot).where(FeatureSnapshot.snapshot_id == snapshot_id)
            ).scalar_one_or_none()
            values = {
                "symbol": sym,
                "as_of_date": _parse_date(feature_snapshot.get("as_of_date")),
                "prediction_date": _parse_date(prediction.get("predict_date")),
                "target_date": _parse_date(prediction.get("target_date")),
                "source": feature_snapshot.get("source") or "latest_prediction_signal_context",
                "schema_version": 1,
                "completeness_score": feature_snapshot.get("completeness_score"),
                "verification_status": agent_review.get("verification_status"),
                "gate_result": agent_review.get("gate_result"),
                "payload_json": feature_snapshot,
                "updated_at": _now(),
            }
            if snapshot is None:
                session.add(FeatureSnapshot(snapshot_id=snapshot_id, created_at=_now(), **values))
            else:
                for key, value in values.items():
                    setattr(snapshot, key, value)
            persisted["feature_snapshot_id"] = snapshot_id

        analysis_id = None
        if failure_analysis:
            analysis_id = failure_analysis.get("analysis_id") or _analysis_id(sym, failure_analysis, lookback_days)
            analysis = session.execute(
                select(FailureAnalysisRecord).where(FailureAnalysisRecord.analysis_id == analysis_id)
            ).scalar_one_or_none()
            values = {
                "symbol": sym,
                "lookback_days": lookback_days,
                "severity": failure_analysis.get("severity") or "unknown",
                "sample_count": int(failure_analysis.get("sample_count") or 0),
                "high_deviation_count": int(failure_analysis.get("high_deviation_count") or 0),
                "evidence_snapshot_ids": {"snapshot_ids": [snapshot_id]} if snapshot_id else None,
                "root_causes_json": failure_analysis.get("root_causes") or [],
                "payload_json": {**failure_analysis, "analysis_id": analysis_id},
            }
            if analysis is None:
                session.add(FailureAnalysisRecord(analysis_id=analysis_id, created_at=_now(), **values))
            else:
                for key, value in values.items():
                    setattr(analysis, key, value)
            persisted["failure_analysis_id"] = analysis_id

        review_id = agent_review.get("review_id")
        review = session.execute(
            select(AgentReviewRun).where(AgentReviewRun.review_id == review_id)
        ).scalar_one_or_none()
        values = {
            "symbol": sym,
            "status": agent_review.get("status") or "waiting_for_samples",
            "priority": agent_review.get("priority") or "none",
            "source": agent_review.get("source") or "failure_analysis_rule_agent",
            "proposed_actions_json": agent_review.get("proposed_actions") or [],
            "blocked_actions_json": agent_review.get("blocked_actions") or [],
            "verification_status": agent_review.get("verification_status") or "pending",
            "gate_result": agent_review.get("gate_result"),
            "payload_json": agent_review,
            "updated_at": _now(),
        }
        if review is None:
            session.add(AgentReviewRun(review_id=review_id, created_at=_now(), **values))
        else:
            for key, value in values.items():
                setattr(review, key, value)

        for check in agent_review.get("verification_checks") or []:
            check_id = check.get("check_id")
            if not check_id:
                continue
            record = session.execute(
                select(AgentVerificationCheck).where(AgentVerificationCheck.check_id == check_id)
            ).scalar_one_or_none()
            values = {
                "review_id": review_id,
                "check_type": check.get("check_type") or "unknown",
                "status": check.get("status") or "pending",
                "evidence_json": check.get("evidence") or {},
                "message": check.get("message"),
            }
            if record is None:
                session.add(AgentVerificationCheck(check_id=check_id, created_at=_now(), **values))
            else:
                for key, value in values.items():
                    setattr(record, key, value)

        session.commit()
        persisted["agent_review_id"] = review_id
        persisted["verification_checks"] = len(agent_review.get("verification_checks") or [])
        return persisted
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.debug("agent iteration persistence skipped for %s: %s", sym, exc)
        return {"status": "failed", "reason": str(exc)[:240]}


def serialize_feature_snapshot(record: FeatureSnapshot) -> dict:
    payload = dict(record.payload_json or {})
    payload.setdefault("snapshot_id", record.snapshot_id)
    payload["persisted_at"] = record.created_at.isoformat() if record.created_at else None
    payload["persistence"] = {
        "id": record.id,
        "verification_status": record.verification_status,
        "gate_result": record.gate_result,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    return payload


def serialize_failure_analysis(record: FailureAnalysisRecord) -> dict:
    payload = dict(record.payload_json or {})
    payload.setdefault("analysis_id", record.analysis_id)
    payload["persisted_at"] = record.created_at.isoformat() if record.created_at else None
    payload["persistence"] = {
        "id": record.id,
        "lookback_days": record.lookback_days,
        "evidence_snapshot_ids": record.evidence_snapshot_ids,
    }
    return payload


def serialize_agent_review(record: AgentReviewRun, checks: Optional[list[AgentVerificationCheck]] = None) -> dict:
    payload = dict(record.payload_json or {})
    payload.setdefault("review_id", record.review_id)
    payload["verification_status"] = record.verification_status
    payload["gate_result"] = record.gate_result
    if checks is not None:
        payload["verification_checks"] = [
            {
                "check_id": item.check_id,
                "review_id": item.review_id,
                "check_type": item.check_type,
                "status": item.status,
                "message": item.message,
                "evidence": item.evidence_json or {},
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in checks
        ]
    payload["persisted_at"] = record.created_at.isoformat() if record.created_at else None
    payload["persistence"] = {
        "id": record.id,
        "status": record.status,
        "priority": record.priority,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    return payload