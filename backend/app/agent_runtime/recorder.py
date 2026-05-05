from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from ..core.db import SessionLocal
from ..core.models import AgentRuntimePipelineRun, AgentRuntimeTask, AgentRuntimeRun, AgentRuntimeSkillUsage
from .schemas import AgentExecutionResult, AgentTaskPlan


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def persist_task_plan(plan: AgentTaskPlan, *, status: str = "pending") -> None:
    try:
        with SessionLocal() as session:
            existing = session.execute(
                select(AgentRuntimeTask).where(AgentRuntimeTask.task_id == plan.id)
            ).scalar_one_or_none()
            if existing:
                existing.status = status
                existing.plan_json = plan.model_dump(mode="json")
                existing.updated_at = _utc_now()
            else:
                session.add(
                    AgentRuntimeTask(
                        task_id=plan.id,
                        user_message=plan.userMessage,
                        intent=plan.intent,
                        risk_level=plan.riskLevel,
                        status=status,
                        requires_confirmation=plan.requiresConfirmation,
                        plan_json=plan.model_dump(mode="json"),
                    )
                )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("persist_task_plan failed for %s: %s", plan.id, exc)


def update_task_status(task_id: str, status: str, *, final_summary: Optional[str] = None) -> None:
    try:
        with SessionLocal() as session:
            row = session.execute(
                select(AgentRuntimeTask).where(AgentRuntimeTask.task_id == task_id)
            ).scalar_one_or_none()
            if not row:
                return
            row.status = status
            row.final_summary = final_summary
            row.updated_at = _utc_now()
            if status in {"success", "failed", "blocked", "pending_confirmation"}:
                row.finished_at = _utc_now()
            elif status == "running":
                row.finished_at = None
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("update_task_status failed for %s: %s", task_id, exc)


def start_pipeline_run(
    *,
    pipeline_run_id: str,
    pipeline_type: str,
    triggered_by: str,
    user_request: str | None = None,
    payload: dict | None = None,
) -> None:
    try:
        with SessionLocal() as session:
            session.add(
                AgentRuntimePipelineRun(
                    pipeline_run_id=pipeline_run_id,
                    pipeline_type=pipeline_type,
                    status="running",
                    triggered_by=triggered_by,
                    user_request=user_request,
                    started_at=_utc_now(),
                    payload_json=payload or {},
                    warnings_json=[],
                )
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("start_pipeline_run failed for %s: %s", pipeline_run_id, exc)


def finish_pipeline_run(
    pipeline_run_id: str,
    status: str,
    *,
    final_summary: str | None = None,
    warnings: list[str] | None = None,
    payload: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    try:
        with SessionLocal() as session:
            row = session.execute(
                select(AgentRuntimePipelineRun).where(AgentRuntimePipelineRun.pipeline_run_id == pipeline_run_id)
            ).scalar_one_or_none()
            if not row:
                return
            row.status = status
            row.finished_at = _utc_now()
            row.duration_ms = duration_ms
            row.final_summary = final_summary
            row.warnings_json = warnings or []
            if payload is not None:
                row.payload_json = payload
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("finish_pipeline_run failed for %s: %s", pipeline_run_id, exc)


def persist_agent_result(
    task_id: str,
    result: AgentExecutionResult,
    *,
    duration_ms: Optional[int] = None,
    pipeline_run_id: str | None = None,
) -> str | None:
    try:
        with SessionLocal() as session:
            now = _utc_now()
            run_id = f"run_{now.strftime('%Y%m%d%H%M%S%f')}"
            session.add(
                AgentRuntimeRun(
                    run_id=run_id,
                    task_id=task_id,
                    pipeline_run_id=pipeline_run_id,
                    agent_name=result.agentName,
                    status=result.status,
                    input_summary="由 TaskManagerAgent 调度执行。",
                    output_summary=result.summary,
                    duration_ms=duration_ms,
                    error=result.error,
                    used_data_sources=result.usedDataSources,
                    used_skills=result.usedSkills,
                    output_json=result.output,
                    started_at=now,
                    finished_at=now,
                )
            )
            session.commit()
            return run_id
    except Exception as exc:  # noqa: BLE001
        logger.debug("persist_agent_result failed for %s/%s: %s", task_id, result.agentName, exc)
    return None


def persist_skill_usage(
    *,
    skill_key: str,
    skill_name: str,
    owner_agent: str,
    task_id: str,
    status: str,
    summary: str,
    data_sources: list[str] | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    pipeline_run_id: str | None = None,
    agent_run_id: str | None = None,
) -> None:
    try:
        with SessionLocal() as session:
            now = _utc_now()
            session.add(
                AgentRuntimeSkillUsage(
                    usage_id=f"usage_{now.strftime('%Y%m%d%H%M%S%f')}",
                    skill_key=skill_key,
                    skill_name=skill_name,
                    owner_agent=owner_agent,
                    task_id=task_id,
                    pipeline_run_id=pipeline_run_id,
                    agent_run_id=agent_run_id,
                    status=status,
                    started_at=now,
                    finished_at=now,
                    duration_ms=duration_ms,
                    output_summary=summary,
                    error=error,
                    triggered_by="user",
                    data_sources_used=data_sources or [],
                )
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("persist_skill_usage failed for %s/%s: %s", task_id, skill_key, exc)