from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.models import AgentRuntimeSkillAuditLog, AgentRuntimeSkillDefinition, AgentRuntimeSkillVersion
from .registry import get_skill, list_default_skills
from .schemas import AgentSkillDefinition


EDITABLE_SKILL_FIELDS = {
    "description",
    "enabled",
    "riskLevel",
    "timeoutMs",
    "retryPolicy",
    "requiredDataSources",
    "dependencies",
    "permission",
    "requiresConfirmation",
    "plainExplanation",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bump_patch(version: str | None) -> str:
    raw = version or "1.0.0"
    parts = raw.split(".")
    if len(parts) != 3:
        return "1.0.1"
    try:
        parts[2] = str(int(parts[2]) + 1)
    except ValueError:
        return "1.0.1"
    return ".".join(parts)


def _merge_row(default_data: dict[str, Any] | None, row: AgentRuntimeSkillDefinition) -> AgentSkillDefinition:
    data = dict(default_data or {})
    data.update(row.definition_json or {})
    data["skillKey"] = row.skill_key
    data["enabled"] = row.enabled
    data["riskLevel"] = row.risk_level
    data["version"] = row.version
    data["updatedBy"] = row.updated_by
    if row.created_at:
        data["createdAt"] = row.created_at.isoformat()
    if row.updated_at:
        data["updatedAt"] = row.updated_at.isoformat()
    return AgentSkillDefinition.model_validate(data)


def list_effective_skills(session: Session | None = None) -> list[AgentSkillDefinition]:
    defaults = {item.skillKey: item for item in list_default_skills()}
    if session is None:
        return list(defaults.values())
    try:
        rows = session.execute(select(AgentRuntimeSkillDefinition)).scalars().all()
    except SQLAlchemyError:
        return list(defaults.values())

    merged = dict(defaults)
    for row in rows:
        default = defaults.get(row.skill_key)
        merged[row.skill_key] = _merge_row(default.model_dump(mode="json") if default else None, row)
    return list(merged.values())


def get_effective_skill(skill_key: str, session: Session | None = None) -> AgentSkillDefinition | None:
    normalized = skill_key.strip()
    if session is None:
        return get_skill(normalized)
    try:
        row = session.execute(select(AgentRuntimeSkillDefinition).where(AgentRuntimeSkillDefinition.skill_key == normalized)).scalar_one_or_none()
    except SQLAlchemyError:
        return get_skill(normalized)
    default = get_skill(normalized)
    if not row:
        return default
    return _merge_row(default.model_dump(mode="json") if default else None, row)


def update_skill_definition(
    session: Session,
    skill_key: str,
    changes: dict[str, Any],
    *,
    actor: str = "user",
    reason: str | None = None,
    action: str = "update",
) -> AgentSkillDefinition:
    normalized = skill_key.strip()
    current = get_effective_skill(normalized, session)
    if not current:
        raise KeyError(normalized)
    if not current.editable:
        raise PermissionError(f"Skill {normalized} is not editable")

    invalid_fields = sorted(set(changes) - EDITABLE_SKILL_FIELDS)
    if invalid_fields:
        raise ValueError(f"unsupported fields: {', '.join(invalid_fields)}")

    before = current.model_dump(mode="json")
    after = dict(before)
    after.update({key: value for key, value in changes.items() if value is not None})
    after["updatedAt"] = _utc_now_iso()
    after["updatedBy"] = actor
    after["version"] = _bump_patch(before.get("version"))
    validated = AgentSkillDefinition.model_validate(after)
    after = validated.model_dump(mode="json")

    row = session.execute(select(AgentRuntimeSkillDefinition).where(AgentRuntimeSkillDefinition.skill_key == normalized)).scalar_one_or_none()
    now = _utc_now()
    if row:
        row.definition_json = after
        row.enabled = validated.enabled
        row.risk_level = validated.riskLevel
        row.version = validated.version
        row.updated_at = now
        row.updated_by = actor
    else:
        row = AgentRuntimeSkillDefinition(
            skill_key=normalized,
            definition_json=after,
            enabled=validated.enabled,
            risk_level=validated.riskLevel,
            version=validated.version,
            created_at=now,
            updated_at=now,
            updated_by=actor,
        )
        session.add(row)

    audit_id = f"audit-{uuid.uuid4().hex[:16]}"
    session.add(
        AgentRuntimeSkillAuditLog(
            audit_log_id=audit_id,
            timestamp=now,
            actor=actor,
            action=action,
            skill_key=normalized,
            before_json=before,
            after_json=after,
            reason=reason,
            result="success",
            risk_level=validated.riskLevel,
        )
    )
    session.add(
        AgentRuntimeSkillVersion(
            version_id=f"skill-version-{uuid.uuid4().hex[:16]}",
            skill_key=normalized,
            version=validated.version,
            created_at=now,
            created_by=actor,
            change_summary=reason or f"Skill {action}",
            before_json=before,
            after_json=after,
            audit_log_id=audit_id,
        )
    )
    session.commit()
    return validated


def rollback_skill_definition(
    session: Session,
    skill_key: str,
    version_id: str,
    *,
    actor: str = "user",
    reason: str | None = None,
) -> AgentSkillDefinition:
    normalized = skill_key.strip()
    current = get_effective_skill(normalized, session)
    if not current:
        raise KeyError(normalized)
    if not current.editable:
        raise PermissionError(f"Skill {normalized} is not editable")

    target = session.execute(
        select(AgentRuntimeSkillVersion).where(
            AgentRuntimeSkillVersion.skill_key == normalized,
            AgentRuntimeSkillVersion.version_id == version_id,
        )
    ).scalar_one_or_none()
    if not target:
        raise KeyError(version_id)

    before = current.model_dump(mode="json")
    after = dict(target.after_json or {})
    after["updatedAt"] = _utc_now_iso()
    after["updatedBy"] = actor
    after["version"] = _bump_patch(before.get("version"))
    validated = AgentSkillDefinition.model_validate(after)
    after = validated.model_dump(mode="json")

    row = session.execute(select(AgentRuntimeSkillDefinition).where(AgentRuntimeSkillDefinition.skill_key == normalized)).scalar_one_or_none()
    now = _utc_now()
    if row:
        row.definition_json = after
        row.enabled = validated.enabled
        row.risk_level = validated.riskLevel
        row.version = validated.version
        row.updated_at = now
        row.updated_by = actor
    else:
        row = AgentRuntimeSkillDefinition(
            skill_key=normalized,
            definition_json=after,
            enabled=validated.enabled,
            risk_level=validated.riskLevel,
            version=validated.version,
            created_at=now,
            updated_at=now,
            updated_by=actor,
        )
        session.add(row)

    audit_id = f"audit-{uuid.uuid4().hex[:16]}"
    session.add(
        AgentRuntimeSkillAuditLog(
            audit_log_id=audit_id,
            timestamp=now,
            actor=actor,
            action="rollback",
            skill_key=normalized,
            before_json=before,
            after_json=after,
            reason=reason or f"Rollback to {target.version}",
            result="success",
            risk_level=validated.riskLevel,
        )
    )
    session.add(
        AgentRuntimeSkillVersion(
            version_id=f"skill-version-{uuid.uuid4().hex[:16]}",
            skill_key=normalized,
            version=validated.version,
            created_at=now,
            created_by=actor,
            change_summary=reason or f"Rollback to {target.version}",
            before_json=before,
            after_json=after,
            audit_log_id=audit_id,
        )
    )
    session.commit()
    return validated


def skill_versions(session: Session, skill_key: str, limit: int = 50) -> list[AgentRuntimeSkillVersion]:
    return session.execute(
        select(AgentRuntimeSkillVersion)
        .where(AgentRuntimeSkillVersion.skill_key == skill_key)
        .order_by(AgentRuntimeSkillVersion.created_at.desc())
        .limit(limit)
    ).scalars().all()


def skill_audit_logs(session: Session, skill_key: str | None = None, limit: int = 50) -> list[AgentRuntimeSkillAuditLog]:
    stmt = select(AgentRuntimeSkillAuditLog)
    if skill_key:
        stmt = stmt.where(AgentRuntimeSkillAuditLog.skill_key == skill_key)
    return session.execute(stmt.order_by(AgentRuntimeSkillAuditLog.timestamp.desc()).limit(limit)).scalars().all()