from __future__ import annotations

import time
import uuid
from typing import Any

from .executor import AgentRuntimeExecutor
from .recorder import finish_pipeline_run, start_pipeline_run
from .schemas import AgentTaskChatResponse, UserAgentContext, UserAgentRequest


CHECK_DATA_STATUS_MESSAGE = "检查系统关键数据状态"
CHECK_AGENT_LOGS_MESSAGE = "查看最近 Agent 和 Skill 运行异常"
GENERATE_TRADE_PLAYBOOK_MESSAGE = "生成明日交易剧本概览"

PIPELINE_MESSAGES: dict[str, list[str]] = {
    "data-diagnosis": ["检查系统关键数据状态和最近管道失败情况", "查看 Agent 日志状态"],
    "pre-market": [CHECK_DATA_STATUS_MESSAGE, GENERATE_TRADE_PLAYBOOK_MESSAGE, CHECK_AGENT_LOGS_MESSAGE],
    "post-market": ["复盘昨天交易计划和预测表现", CHECK_DATA_STATUS_MESSAGE, CHECK_AGENT_LOGS_MESSAGE],
    "intraday": [CHECK_DATA_STATUS_MESSAGE, GENERATE_TRADE_PLAYBOOK_MESSAGE],
    "skill-management": ["查看当前 Agent Skill 状态"],
    "parameter-adjustment": ["生成参数调整草案，不直接修改生产参数"],
}

PIPELINE_LABELS: dict[str, str] = {
    "data-diagnosis": "数据体检 Pipeline",
    "pre-market": "盘前 Agent Pipeline",
    "post-market": "盘后复盘 Pipeline",
    "intraday": "盘中低频 Pipeline",
    "user-question": "用户问题 Pipeline",
    "skill-management": "Skill 管理 Pipeline",
    "parameter-adjustment": "参数调整草案 Pipeline",
}


class AgentPipelineOrchestrator:
    def __init__(self, executor: AgentRuntimeExecutor | None = None) -> None:
        self.executor = executor or AgentRuntimeExecutor()

    def run_pipeline(
        self,
        pipeline_type: str,
        *,
        message: str | None = None,
        triggered_by: str = "user",
        context: UserAgentContext | None = None,
    ) -> dict[str, Any]:
        normalized_type = pipeline_type.strip().lower()
        messages = self._messages_for(normalized_type, message)
        pipeline_run_id = f"agpipe_{uuid.uuid4().hex[:16]}"
        started = time.monotonic()
        start_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            pipeline_type=normalized_type,
            triggered_by=triggered_by,
            user_request=message,
            payload={"messages": messages, "label": PIPELINE_LABELS.get(normalized_type, normalized_type)},
        )

        responses: list[AgentTaskChatResponse] = []
        warnings: list[str] = []
        for item in messages:
            response = self.executor.run_task_chat(UserAgentRequest(message=item, context=context), pipeline_run_id=pipeline_run_id)
            responses.append(response)
            warnings.extend(response.warnings)
            if response.requiresConfirmation:
                warnings.append(f"任务 {response.taskPlan.id if response.taskPlan else '-'} 需要确认，已停留在待确认状态。")

        status = self._final_status(responses)
        summary = self._summary(normalized_type, responses)
        duration_ms = int((time.monotonic() - started) * 1000)
        payload = {
            "messages": messages,
            "taskIds": [item.taskPlan.id for item in responses if item.taskPlan],
            "steps": [self._response_step(item) for item in responses],
        }
        finish_pipeline_run(
            pipeline_run_id,
            status,
            final_summary=summary,
            warnings=warnings,
            payload=payload,
            duration_ms=duration_ms,
        )
        return {
            "pipelineRunId": pipeline_run_id,
            "pipelineType": normalized_type,
            "status": status,
            "summary": summary,
            "warnings": warnings,
            "durationMs": duration_ms,
            "steps": payload["steps"],
        }

    def supported_pipelines(self) -> list[dict[str, str]]:
        items = sorted({*PIPELINE_MESSAGES.keys(), "user-question"})
        return [{"pipelineType": item, "label": PIPELINE_LABELS.get(item, item)} for item in items]

    def _messages_for(self, pipeline_type: str, message: str | None) -> list[str]:
        if pipeline_type == "user-question":
            if not message or not message.strip():
                raise ValueError("user-question pipeline requires message")
            return [message.strip()]
        messages = PIPELINE_MESSAGES.get(pipeline_type)
        if not messages:
            raise KeyError(pipeline_type)
        if message and message.strip():
            return [message.strip(), *messages]
        return messages

    def _final_status(self, responses: list[AgentTaskChatResponse]) -> str:
        if any(item.requiresConfirmation for item in responses):
            return "partial_success"
        statuses = [result.status for item in responses for result in item.agentResults]
        if statuses and all(item == "failed" for item in statuses):
            return "failed"
        if any(item in {"failed", "timeout", "skipped"} for item in statuses):
            return "partial_success"
        return "success"

    def _summary(self, pipeline_type: str, responses: list[AgentTaskChatResponse]) -> str:
        label = PIPELINE_LABELS.get(pipeline_type, pipeline_type)
        success_count = sum(1 for item in responses if not item.requiresConfirmation)
        confirmation_count = sum(1 for item in responses if item.requiresConfirmation)
        failed_count = sum(1 for item in responses for result in item.agentResults if result.status == "failed")
        return f"{label} 已执行 {len(responses)} 个任务：{success_count} 个已完成，{confirmation_count} 个待确认，{failed_count} 个失败。"

    def _response_step(self, response: AgentTaskChatResponse) -> dict[str, Any]:
        return {
            "taskId": response.taskPlan.id if response.taskPlan else None,
            "intent": response.taskPlan.intent if response.taskPlan else None,
            "riskLevel": response.taskPlan.riskLevel if response.taskPlan else None,
            "requiresConfirmation": response.requiresConfirmation,
            "reply": response.reply,
            "agentResults": [item.model_dump(mode="json") for item in response.agentResults],
            "skillUsages": [item.model_dump(mode="json") for item in response.skillUsages],
        }
