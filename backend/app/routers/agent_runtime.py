from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from ..agent_runtime.executor import AgentRuntimeExecutor
from ..agent_runtime.pipeline_orchestrator import AgentPipelineOrchestrator
from ..agent_runtime.registry import list_default_capabilities, list_default_skills
from ..agent_runtime.schemas import AgentStatusSnapshot, UserAgentContext, UserAgentRequest
from ..agent_runtime.skill_store import get_effective_skill, list_effective_skills, rollback_skill_definition, skill_audit_logs, skill_versions, update_skill_definition
from ..core.db import SessionLocal
from ..core.models import AgentRuntimePipelineRun, AgentRuntimeRun, AgentRuntimeSkillAuditLog, AgentRuntimeSkillUsage, AgentRuntimeSkillVersion, AgentRuntimeTask, PipelineRun


router = APIRouter(prefix="/api/agent", tags=["agent-runtime"])
_executor = AgentRuntimeExecutor()
_pipeline_orchestrator = AgentPipelineOrchestrator(_executor)
SKILL_NOT_FOUND = "skill not found"
AGENT_TASK_NOT_FOUND = "agent task not found"
SKILL_MIGRATION_REQUIRED = "agent runtime migration is required before Skill mutation"
SKILL_MUTATION_RESPONSES = {
    400: {"description": "Invalid Skill mutation request"},
    403: {"description": "Skill is not editable or action is forbidden"},
    404: {"description": "Skill not found"},
    503: {"description": "Agent runtime migration is required before Skill mutation"},
}


class AgentSkillUpdateRequest(BaseModel):
    description: str | None = None
    enabled: bool | None = None
    riskLevel: str | None = None
    timeoutMs: int | None = Field(default=None, ge=1000, le=300000)
    retryPolicy: dict[str, int] | None = None
    requiredDataSources: list[str] | None = None
    dependencies: list[str] | None = None
    permission: str | None = None
    requiresConfirmation: bool | None = None
    plainExplanation: str | None = None
    reason: str | None = None
    actor: str = "user"


class AgentSkillToggleRequest(BaseModel):
    reason: str | None = None
    actor: str = "user"


class AgentSkillTestRequest(BaseModel):
    message: str | None = None
    actor: str = "user"


class AgentSkillRollbackRequest(BaseModel):
    versionId: str = Field(..., min_length=1, max_length=80)
    reason: str | None = None
    actor: str = "user"


class AgentPipelineRunRequest(BaseModel):
    message: str | None = Field(default=None, max_length=4000)
    triggeredBy: str = Field(default="user", max_length=40)
    context: UserAgentContext | None = None


class AgentTaskConfirmRequest(BaseModel):
    confirmed: bool = True
    confirmationText: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="user", max_length=80)
    pipelineRunId: str | None = Field(default=None, max_length=80)


class AgentTaskRerunRequest(BaseModel):
    confirmed: bool = False
    confirmationText: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="user", max_length=80)
    pipelineRunId: str | None = Field(default=None, max_length=80)


class AgentFailedRerunRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)
    confirmed: bool = False
    confirmationText: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="user", max_length=80)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/task-chat")
def task_chat(request: UserAgentRequest):
    return _executor.run_task_chat(request)


@router.get("/capabilities")
def get_agent_capabilities():
    return {"items": [item.model_dump(mode="json") for item in list_default_capabilities()]}


@router.get("/skills")
def list_agent_skills(
    owner_agent: Annotated[str | None, Query(alias="ownerAgent")] = None,
    category: Annotated[str | None, Query()] = None,
    risk_level: Annotated[str | None, Query(alias="riskLevel")] = None,
    enabled: Annotated[bool | None, Query()] = None,
):
    with SessionLocal() as session:
        items = list_effective_skills(session)
    if owner_agent:
        items = [item for item in items if item.ownerAgent == owner_agent]
    if category:
        items = [item for item in items if item.category == category]
    if risk_level:
        items = [item for item in items if item.riskLevel == risk_level]
    if enabled is not None:
        items = [item for item in items if item.enabled == enabled]
    return {"items": [item.model_dump(mode="json") for item in items], "count": len(items)}


@router.get("/skills/{skill_key}", responses={404: {"description": "Skill not found"}})
def get_agent_skill(skill_key: str):
    with SessionLocal() as session:
        skill = get_effective_skill(skill_key, session)
    if not skill:
        raise HTTPException(status_code=404, detail=SKILL_NOT_FOUND)
    return skill.model_dump(mode="json")


@router.patch("/skills/{skill_key}", responses=SKILL_MUTATION_RESPONSES)
def patch_agent_skill(skill_key: str, request: AgentSkillUpdateRequest):
    payload = request.model_dump(exclude_unset=True, exclude={"reason", "actor"})
    try:
        with SessionLocal() as session:
            updated = update_skill_definition(session, skill_key, payload, actor=request.actor, reason=request.reason, action="update")
    except KeyError:
        raise HTTPException(status_code=404, detail=SKILL_NOT_FOUND) from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=SKILL_MIGRATION_REQUIRED) from exc
    return updated.model_dump(mode="json")


@router.post("/skills/{skill_key}/enable", responses=SKILL_MUTATION_RESPONSES)
def enable_agent_skill(skill_key: str, request: AgentSkillToggleRequest | None = None):
    request = request or AgentSkillToggleRequest()
    return _toggle_skill(skill_key, True, request)


@router.post("/skills/{skill_key}/disable", responses=SKILL_MUTATION_RESPONSES)
def disable_agent_skill(skill_key: str, request: AgentSkillToggleRequest | None = None):
    request = request or AgentSkillToggleRequest()
    return _toggle_skill(skill_key, False, request)


@router.post("/skills/{skill_key}/test-run", responses={400: {"description": "Skill is disabled"}, 404: {"description": "Skill not found"}})
def test_agent_skill(skill_key: str, request: AgentSkillTestRequest | None = None):
    request = request or AgentSkillTestRequest()
    with SessionLocal() as session:
        skill = get_effective_skill(skill_key, session)
    if not skill:
        raise HTTPException(status_code=404, detail=SKILL_NOT_FOUND)
    if not skill.enabled:
        raise HTTPException(status_code=400, detail="skill is disabled")
    response = _executor.run_task_chat(UserAgentRequest(message=request.message or f"测试 {skill.skillName} Skill"))
    return {
        "skillKey": skill.skillKey,
        "skillName": skill.skillName,
        "status": "pending_confirmation" if response.requiresConfirmation else "success",
        "reply": response.reply,
        "requiresConfirmation": response.requiresConfirmation,
        "taskPlan": response.taskPlan.model_dump(mode="json") if response.taskPlan else None,
        "warnings": response.warnings,
    }


@router.get("/skills/{skill_key}/versions")
def list_agent_skill_versions(skill_key: str, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    with SessionLocal() as session:
        rows = skill_versions(session, skill_key, limit)
    return {"items": [_skill_version_row(row) for row in rows], "count": len(rows)}


@router.get("/skills/{skill_key}/audit-logs")
def list_agent_skill_audit_logs(skill_key: str, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    with SessionLocal() as session:
        rows = skill_audit_logs(session, skill_key, limit)
    return {"items": [_skill_audit_row(row) for row in rows], "count": len(rows)}


@router.get("/skills/{skill_key}/export", responses={404: {"description": "Skill not found"}})
def export_agent_skill(skill_key: str):
    with SessionLocal() as session:
        skill = get_effective_skill(skill_key, session)
        if not skill:
            raise HTTPException(status_code=404, detail=SKILL_NOT_FOUND)
        versions = skill_versions(session, skill_key, 100)
        audits = skill_audit_logs(session, skill_key, 100)
    return {
        "skill": skill.model_dump(mode="json"),
        "versions": [_skill_version_row(row) for row in versions],
        "auditLogs": [_skill_audit_row(row) for row in audits],
    }


@router.post("/skills/{skill_key}/rollback", responses=SKILL_MUTATION_RESPONSES)
def rollback_agent_skill(skill_key: str, request: AgentSkillRollbackRequest):
    try:
        with SessionLocal() as session:
            updated = rollback_skill_definition(
                session,
                skill_key,
                request.versionId,
                actor=request.actor,
                reason=request.reason,
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="skill or version not found") from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=SKILL_MIGRATION_REQUIRED) from exc
    return updated.model_dump(mode="json")


@router.get("/status")
def get_agent_status_overview():
    capabilities = list_default_capabilities()
    skills = list_default_skills()
    since_24h = _utc_now() - timedelta(hours=24)
    rows_by_agent: dict[str, list[AgentRuntimeRun]] = {}
    with SessionLocal() as session:
        rows = session.execute(select(AgentRuntimeRun).where(AgentRuntimeRun.started_at >= since_24h)).scalars().all()
    for row in rows:
        rows_by_agent.setdefault(row.agent_name, []).append(row)
    snapshots = [_agent_status_snapshot(capability, skills, rows_by_agent.get(capability.agentName, [])) for capability in capabilities]
    return {"items": [item.model_dump(mode="json") for item in snapshots], "count": len(snapshots)}


@router.get("/pipelines")
def list_supported_agent_pipelines():
    items = _pipeline_orchestrator.supported_pipelines()
    return {"items": items, "count": len(items)}


@router.post("/pipelines/{pipeline_type}/run", responses={400: {"description": "Invalid pipeline request"}, 404: {"description": "Pipeline type not found"}})
def run_agent_pipeline(pipeline_type: str, request: AgentPipelineRunRequest | None = None):
    request = request or AgentPipelineRunRequest()
    try:
        return _pipeline_orchestrator.run_pipeline(
            pipeline_type,
            message=request.message,
            triggered_by=request.triggeredBy,
            context=request.context,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="pipeline type not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pipelines/runs")
def list_agent_pipeline_runs(
    pipeline_type: Annotated[str | None, Query(alias="pipelineType")] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    stmt = select(AgentRuntimePipelineRun)
    if pipeline_type:
        stmt = stmt.where(AgentRuntimePipelineRun.pipeline_type == pipeline_type)
    if status:
        stmt = stmt.where(AgentRuntimePipelineRun.status == status)
    with SessionLocal() as session:
        rows = session.execute(stmt.order_by(AgentRuntimePipelineRun.started_at.desc()).limit(limit)).scalars().all()
    return {"items": [_pipeline_run_row(row) for row in rows], "count": len(rows)}


@router.get("/pipelines/runs/{pipeline_run_id}", responses={404: {"description": "Pipeline run not found"}})
def get_agent_pipeline_run(pipeline_run_id: str):
    with SessionLocal() as session:
        row = session.execute(
            select(AgentRuntimePipelineRun).where(AgentRuntimePipelineRun.pipeline_run_id == pipeline_run_id)
        ).scalar_one_or_none()
        agent_runs = session.execute(
            select(AgentRuntimeRun).where(AgentRuntimeRun.pipeline_run_id == pipeline_run_id).order_by(AgentRuntimeRun.started_at.asc())
        ).scalars().all()
        skill_usages = session.execute(
            select(AgentRuntimeSkillUsage).where(AgentRuntimeSkillUsage.pipeline_run_id == pipeline_run_id).order_by(AgentRuntimeSkillUsage.started_at.asc())
        ).scalars().all()
    if not row:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    return {
        **_pipeline_run_row(row),
        "agentRuns": [_agent_run_row(item) for item in agent_runs],
        "skillUsages": [_skill_usage_row(item) for item in skill_usages],
    }


@router.get("/logs/overview")
def get_agent_logs_overview():
    since_24h = _utc_now() - timedelta(hours=24)
    with SessionLocal() as session:
        agent_total = session.execute(select(func.count(AgentRuntimeRun.id))).scalar() or 0
        agent_failed_24h = session.execute(
            select(func.count(AgentRuntimeRun.id)).where(AgentRuntimeRun.status == "failed", AgentRuntimeRun.started_at >= since_24h)
        ).scalar() or 0
        skill_total = session.execute(select(func.count(AgentRuntimeSkillUsage.id))).scalar() or 0
        agent_pipeline_total = session.execute(select(func.count(AgentRuntimePipelineRun.id))).scalar() or 0
        agent_pipeline_failed_24h = session.execute(
            select(func.count(AgentRuntimePipelineRun.id)).where(
                AgentRuntimePipelineRun.status == "failed",
                AgentRuntimePipelineRun.started_at >= since_24h,
            )
        ).scalar() or 0
        skill_failed_24h = session.execute(
            select(func.count(AgentRuntimeSkillUsage.id)).where(AgentRuntimeSkillUsage.status == "failed", AgentRuntimeSkillUsage.started_at >= since_24h)
        ).scalar() or 0
        pipeline_failed_24h = session.execute(
            select(func.count(PipelineRun.id)).where(PipelineRun.status == "failed", PipelineRun.run_at >= since_24h)
        ).scalar() or 0
    overall = "healthy" if not (agent_failed_24h or skill_failed_24h or pipeline_failed_24h or agent_pipeline_failed_24h) else "degraded"
    return {
        "overallStatus": overall,
        "summary": f"AgentRun 总数 {agent_total}，SkillUsage 总数 {skill_total}，AgentPipelineRun 总数 {agent_pipeline_total}；最近24小时 Agent 失败 {agent_failed_24h} 次，Skill 失败 {skill_failed_24h} 次，Agent Pipeline 失败 {agent_pipeline_failed_24h} 次，数据管道失败 {pipeline_failed_24h} 次。",
        "agentRunTotal": agent_total,
        "skillUsageTotal": skill_total,
        "agentPipelineRunTotal": agent_pipeline_total,
        "agentFailed24h": agent_failed_24h,
        "skillFailed24h": skill_failed_24h,
        "agentPipelineFailed24h": agent_pipeline_failed_24h,
        "pipelineFailed24h": pipeline_failed_24h,
    }


@router.get("/tasks/{task_id}", responses={404: {"description": "Agent task not found"}})
def get_agent_task(task_id: str):
    with SessionLocal() as session:
        row = session.execute(select(AgentRuntimeTask).where(AgentRuntimeTask.task_id == task_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=AGENT_TASK_NOT_FOUND)
    return _task_row(row)


@router.get("/tasks/{task_id}/runs")
def get_agent_task_runs(task_id: str):
    with SessionLocal() as session:
        runs = session.execute(
            select(AgentRuntimeRun).where(AgentRuntimeRun.task_id == task_id).order_by(AgentRuntimeRun.started_at.asc())
        ).scalars().all()
        usages = session.execute(
            select(AgentRuntimeSkillUsage).where(AgentRuntimeSkillUsage.task_id == task_id).order_by(AgentRuntimeSkillUsage.started_at.asc())
        ).scalars().all()
    return {
        "taskId": task_id,
        "agentRuns": [_agent_run_row(row) for row in runs],
        "skillUsages": [_skill_usage_row(row) for row in usages],
    }


@router.post("/tasks/{task_id}/confirm", responses={400: {"description": "Task cannot be confirmed"}, 403: {"description": "Task is forbidden"}, 404: {"description": "Agent task not found"}})
def confirm_agent_task(task_id: str, request: AgentTaskConfirmRequest | None = None):
    request = request or AgentTaskConfirmRequest()
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="confirmed must be true")
    try:
        return _executor.confirm_task(
            task_id,
            confirmation_text=request.confirmationText,
            pipeline_run_id=request.pipelineRunId,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=AGENT_TASK_NOT_FOUND) from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/rerun", responses={400: {"description": "Task cannot be rerun"}, 403: {"description": "Task is forbidden"}, 404: {"description": "Agent task not found"}})
def rerun_agent_task(task_id: str, request: AgentTaskRerunRequest | None = None):
    request = request or AgentTaskRerunRequest()
    try:
        return _executor.rerun_task(
            task_id,
            confirmed=request.confirmed,
            confirmation_text=request.confirmationText,
            pipeline_run_id=request.pipelineRunId,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=AGENT_TASK_NOT_FOUND) from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logs/rerun-failed")
def rerun_failed_agent_tasks(request: AgentFailedRerunRequest | None = None):
    request = request or AgentFailedRerunRequest()
    with SessionLocal() as session:
        rows = session.execute(
            select(AgentRuntimeTask)
            .where(AgentRuntimeTask.status == "failed")
            .order_by(AgentRuntimeTask.updated_at.desc().nullslast(), AgentRuntimeTask.created_at.desc())
            .limit(request.limit)
        ).scalars().all()
    items = []
    for row in rows:
        try:
            response = _executor.rerun_task(
                row.task_id,
                confirmed=request.confirmed,
                confirmation_text=request.confirmationText,
            )
            items.append({
                "taskId": row.task_id,
                "status": "pending_confirmation" if response.requiresConfirmation else "rerun_started",
                "reply": response.reply,
                "requiresConfirmation": response.requiresConfirmation,
            })
        except (PermissionError, ValueError) as exc:
            items.append({"taskId": row.task_id, "status": "skipped", "error": str(exc)})
    return {"items": items, "count": len(items)}


@router.get("/logs/agent-runs")
def list_agent_runs(
    agent_name: Annotated[str | None, Query(alias="agentName")] = None,
    status: Annotated[str | None, Query()] = None,
    task_id_query: Annotated[str | None, Query(alias="taskId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    stmt = select(AgentRuntimeRun)
    if agent_name:
        stmt = stmt.where(AgentRuntimeRun.agent_name == agent_name)
    if status:
        stmt = stmt.where(AgentRuntimeRun.status == status)
    if task_id_query:
        stmt = stmt.where(AgentRuntimeRun.task_id == task_id_query)
    with SessionLocal() as session:
        rows = session.execute(stmt.order_by(AgentRuntimeRun.started_at.desc()).limit(limit)).scalars().all()
    return {"items": [_agent_run_row(row) for row in rows], "count": len(rows)}


@router.get("/logs/skill-usages")
def list_skill_usages(
    skill_key: Annotated[str | None, Query(alias="skillKey")] = None,
    owner_agent: Annotated[str | None, Query(alias="ownerAgent")] = None,
    status: Annotated[str | None, Query()] = None,
    task_id_query: Annotated[str | None, Query(alias="taskId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    stmt = select(AgentRuntimeSkillUsage)
    if skill_key:
        stmt = stmt.where(AgentRuntimeSkillUsage.skill_key == skill_key)
    if owner_agent:
        stmt = stmt.where(AgentRuntimeSkillUsage.owner_agent == owner_agent)
    if status:
        stmt = stmt.where(AgentRuntimeSkillUsage.status == status)
    if task_id_query:
        stmt = stmt.where(AgentRuntimeSkillUsage.task_id == task_id_query)
    with SessionLocal() as session:
        rows = session.execute(stmt.order_by(AgentRuntimeSkillUsage.started_at.desc()).limit(limit)).scalars().all()
    return {"items": [_skill_usage_row(row) for row in rows], "count": len(rows)}


@router.get("/logs/skill-audit")
def list_skill_audit(
    skill_key: Annotated[str | None, Query(alias="skillKey")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    with SessionLocal() as session:
        rows = skill_audit_logs(session, skill_key, limit)
    return {"items": [_skill_audit_row(row) for row in rows], "count": len(rows)}


def _toggle_skill(skill_key: str, enabled: bool, request: AgentSkillToggleRequest):
    try:
        with SessionLocal() as session:
            updated = update_skill_definition(
                session,
                skill_key,
                {"enabled": enabled},
                actor=request.actor,
                reason=request.reason or ("启用 Skill" if enabled else "禁用 Skill"),
                action="enable" if enabled else "disable",
            )
    except KeyError:
        raise HTTPException(status_code=404, detail=SKILL_NOT_FOUND) from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=SKILL_MIGRATION_REQUIRED) from exc
    return updated.model_dump(mode="json")


def _task_row(row: AgentRuntimeTask) -> dict[str, Any]:
    return {
        "taskId": row.task_id,
        "userMessage": row.user_message,
        "intent": row.intent,
        "riskLevel": row.risk_level,
        "status": row.status,
        "requiresConfirmation": row.requires_confirmation,
        "plan": row.plan_json,
        "finalSummary": row.final_summary,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
    }


def _agent_run_row(row: AgentRuntimeRun) -> dict[str, Any]:
    return {
        "runId": row.run_id,
        "taskId": row.task_id,
        "pipelineRunId": row.pipeline_run_id,
        "agentName": row.agent_name,
        "status": row.status,
        "inputSummary": row.input_summary,
        "outputSummary": row.output_summary,
        "startedAt": row.started_at.isoformat() if row.started_at else None,
        "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
        "durationMs": row.duration_ms,
        "error": row.error,
        "usedDataSources": row.used_data_sources or [],
        "usedSkills": row.used_skills or [],
        "output": row.output_json or {},
    }


def _skill_usage_row(row: AgentRuntimeSkillUsage) -> dict[str, Any]:
    return {
        "usageId": row.usage_id,
        "skillKey": row.skill_key,
        "skillName": row.skill_name,
        "ownerAgent": row.owner_agent,
        "taskId": row.task_id,
        "pipelineRunId": row.pipeline_run_id,
        "agentRunId": row.agent_run_id,
        "status": row.status,
        "startedAt": row.started_at.isoformat() if row.started_at else None,
        "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
        "durationMs": row.duration_ms,
        "inputSummary": row.input_summary,
        "outputSummary": row.output_summary,
        "error": row.error,
        "triggeredBy": row.triggered_by,
        "dataSourcesUsed": row.data_sources_used or [],
    }


def _pipeline_run_row(row: AgentRuntimePipelineRun) -> dict[str, Any]:
    return {
        "pipelineRunId": row.pipeline_run_id,
        "pipelineType": row.pipeline_type,
        "status": row.status,
        "triggeredBy": row.triggered_by,
        "userRequest": row.user_request,
        "startedAt": row.started_at.isoformat() if row.started_at else None,
        "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
        "durationMs": row.duration_ms,
        "finalSummary": row.final_summary,
        "warnings": row.warnings_json or [],
        "payload": row.payload_json or {},
    }


def _skill_version_row(row: AgentRuntimeSkillVersion) -> dict[str, Any]:
    return {
        "versionId": row.version_id,
        "skillKey": row.skill_key,
        "version": row.version,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "createdBy": row.created_by,
        "changeSummary": row.change_summary,
        "before": row.before_json,
        "after": row.after_json,
        "auditLogId": row.audit_log_id,
    }


def _skill_audit_row(row: AgentRuntimeSkillAuditLog) -> dict[str, Any]:
    return {
        "auditLogId": row.audit_log_id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "actor": row.actor,
        "action": row.action,
        "skillKey": row.skill_key,
        "before": row.before_json,
        "after": row.after_json,
        "reason": row.reason,
        "result": row.result,
        "riskLevel": row.risk_level,
    }


def _agent_status_snapshot(capability, skills, agent_rows: list[AgentRuntimeRun]) -> AgentStatusSnapshot:
    success = [row for row in agent_rows if row.status == "success"]
    failed = [row for row in agent_rows if row.status == "failed"]
    latest = max(agent_rows, key=lambda row: row.started_at or datetime.min) if agent_rows else None
    owned_skills = [item for item in skills if item.ownerAgent == capability.agentName]
    last_success_at = max((row.finished_at for row in success if row.finished_at), default=None)
    last_failure_at = max((row.finished_at for row in failed if row.finished_at), default=None)
    return AgentStatusSnapshot(
        agentName=capability.agentName,
        displayName=capability.displayName,
        status=_status_from_rows(capability.enabled, bool(agent_rows), bool(success), bool(failed)),
        lastRunAt=latest.started_at.isoformat() if latest and latest.started_at else None,
        lastSuccessAt=last_success_at.isoformat() if last_success_at else None,
        lastFailureAt=last_failure_at.isoformat() if last_failure_at else None,
        successRate24h=round(len(success) / len(agent_rows), 3) if agent_rows else None,
        avgDurationMs=int(sum(row.duration_ms or 0 for row in agent_rows) / len(agent_rows)) if agent_rows else None,
        recentError=latest.error if latest and latest.status == "failed" else None,
        enabledSkills=sum(1 for item in owned_skills if item.enabled),
        disabledSkills=sum(1 for item in owned_skills if not item.enabled),
    )


def _status_from_rows(enabled: bool, has_rows: bool, has_success: bool, has_failure: bool) -> str:
    if not enabled:
        return "disabled"
    if has_failure:
        return "degraded" if has_success else "failed"
    if has_rows:
        return "healthy"
    return "idle"