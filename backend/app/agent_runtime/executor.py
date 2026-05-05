from __future__ import annotations

import time

from sqlalchemy import select

from .adapters import AgentAdapterRegistry
from .answer_composer import AgentAnswerComposer
from .recorder import persist_agent_result, persist_skill_usage, persist_task_plan, update_task_status
from .registry import get_skill
from .schemas import AgentExecutionResult, AgentSkillUsageSummary, AgentTaskChatResponse, AgentTaskPlan, AgentTaskStep, UserAgentRequest
from .skill_store import get_effective_skill
from .task_manager_agent import TaskManagerAgent
from ..core.db import SessionLocal
from ..core.models import AgentRuntimeTask


class AgentRuntimeExecutor:
    def __init__(self) -> None:
        self.task_manager = TaskManagerAgent()
        self.adapters = AgentAdapterRegistry()
        self.answer_composer = AgentAnswerComposer()

    def run_task_chat(self, request: UserAgentRequest, *, pipeline_run_id: str | None = None) -> AgentTaskChatResponse:
        plan = self.task_manager.plan(request)

        if plan.blockedReason:
            persist_task_plan(plan, status="blocked")
            answer = self.answer_composer.blocked_answer(plan, plan.blockedReason)
            return AgentTaskChatResponse(
                reply=answer.directAnswer,
                taskPlan=plan,
                userFacingAnswer=answer,
                warnings=[plan.blockedReason],
            )

        if plan.requiresConfirmation:
            persist_task_plan(plan, status="pending_confirmation")
            confirmation = self._confirmation_text(plan)
            answer = self.answer_composer.confirmation_answer(plan, confirmation)
            return AgentTaskChatResponse(
                reply=confirmation,
                taskPlan=plan,
                userFacingAnswer=answer,
                requiresConfirmation=True,
                confirmationPayload={"taskId": plan.id, "riskLevel": plan.riskLevel, "intent": plan.intent},
                warnings=["该操作需要确认后才能执行。"],
            )

        return self._run_plan(plan, request, pipeline_run_id=pipeline_run_id)

    def confirm_task(
        self,
        task_id: str,
        *,
        confirmation_text: str | None = None,
        pipeline_run_id: str | None = None,
    ) -> AgentTaskChatResponse:
        with SessionLocal() as session:
            row = session.execute(select(AgentRuntimeTask).where(AgentRuntimeTask.task_id == task_id)).scalar_one_or_none()
        if not row:
            raise KeyError(task_id)
        if row.status != "pending_confirmation":
            raise ValueError(f"task status is {row.status}, expected pending_confirmation")
        plan = AgentTaskPlan.model_validate(row.plan_json)
        if plan.blockedReason:
            raise PermissionError(plan.blockedReason)
        if plan.riskLevel in {"high", "critical"} and not (confirmation_text and confirmation_text.strip()):
            raise ValueError("high risk task requires confirmationText")
        request = UserAgentRequest(message=row.user_message)
        return self._run_plan(plan, request, pipeline_run_id=pipeline_run_id, reply_prefix="已确认并执行")

    def rerun_task(
        self,
        task_id: str,
        *,
        confirmed: bool = False,
        confirmation_text: str | None = None,
        pipeline_run_id: str | None = None,
    ) -> AgentTaskChatResponse:
        with SessionLocal() as session:
            row = session.execute(select(AgentRuntimeTask).where(AgentRuntimeTask.task_id == task_id)).scalar_one_or_none()
        if not row:
            raise KeyError(task_id)
        if row.status == "running":
            raise ValueError("running task cannot be rerun")
        plan = AgentTaskPlan.model_validate(row.plan_json)
        if plan.blockedReason:
            raise PermissionError(plan.blockedReason)
        if plan.requiresConfirmation and not confirmed:
            persist_task_plan(plan, status="pending_confirmation")
            return AgentTaskChatResponse(
                reply=self._confirmation_text(plan),
                taskPlan=plan,
                requiresConfirmation=True,
                confirmationPayload={"taskId": plan.id, "riskLevel": plan.riskLevel, "intent": plan.intent, "rerun": True},
                warnings=["重跑该任务需要确认后才能执行。"],
            )
        if plan.riskLevel in {"high", "critical"} and not (confirmation_text and confirmation_text.strip()):
            raise ValueError("high risk task requires confirmationText")
        request = UserAgentRequest(message=row.user_message)
        return self._run_plan(plan, request, pipeline_run_id=pipeline_run_id, reply_prefix="已重新执行")

    def _run_plan(
        self,
        plan: AgentTaskPlan,
        request: UserAgentRequest,
        *,
        pipeline_run_id: str | None = None,
        reply_prefix: str | None = None,
    ) -> AgentTaskChatResponse:
        persist_task_plan(plan, status="running")
        agent_results: list[AgentExecutionResult] = []
        skill_usages: list[AgentSkillUsageSummary] = []

        for step in plan.steps:
            if step.agentName == "UserInteractionAgent":
                continue
            result, usage_items = self._execute_step(step, plan, request, pipeline_run_id=pipeline_run_id)
            agent_results.append(result)
            skill_usages.extend(usage_items)

        answer = self.answer_composer.compose(plan, request, agent_results, skill_usages, pipeline_run_id=pipeline_run_id)
        reply = answer.directAnswer
        final_status = "failed" if any(item.status == "failed" for item in agent_results) else "success"
        update_task_status(plan.id, final_status, final_summary=reply)
        return AgentTaskChatResponse(
            reply=f"{reply_prefix}：{reply}" if reply_prefix else reply,
            taskPlan=plan,
            pipelineRunId=pipeline_run_id,
            userFacingAnswer=answer,
            agentResults=agent_results,
            skillUsages=skill_usages,
            suggestedActions=self._suggested_actions(plan.intent),
        )

    def _execute_step(
        self,
        step: AgentTaskStep,
        plan: AgentTaskPlan,
        request: UserAgentRequest,
        *,
        pipeline_run_id: str | None = None,
    ) -> tuple[AgentExecutionResult, list[AgentSkillUsageSummary]]:
        disabled_result = self._disabled_skill_result(step, plan, pipeline_run_id=pipeline_run_id)
        if disabled_result:
            return disabled_result, [AgentSkillUsageSummary(skillKey=step.skillKey or "unknown", status="skipped", summary=disabled_result.summary)]

        started = time.monotonic()
        result = self.adapters.execute(step.agentName, plan, request)
        duration_ms = int((time.monotonic() - started) * 1000)
        agent_run_id = persist_agent_result(plan.id, result, duration_ms=duration_ms, pipeline_run_id=pipeline_run_id)
        usage_items = self._persist_result_skill_usages(plan.id, result, duration_ms, pipeline_run_id=pipeline_run_id, agent_run_id=agent_run_id)
        return result, usage_items

    def _disabled_skill_result(self, step: AgentTaskStep, plan: AgentTaskPlan, *, pipeline_run_id: str | None = None) -> AgentExecutionResult | None:
        if not step.skillKey:
            return None
        with SessionLocal() as session:
            effective_skill = get_effective_skill(step.skillKey, session)
        if not effective_skill or effective_skill.enabled:
            return None
        result = AgentExecutionResult(
            agentName=step.agentName,
            status="skipped",
            summary=f"Skill {effective_skill.skillName} 当前已禁用，已跳过该 Agent 步骤。",
            usedSkills=[step.skillKey],
        )
        agent_run_id = persist_agent_result(plan.id, result, duration_ms=0, pipeline_run_id=pipeline_run_id)
        persist_skill_usage(
            skill_key=step.skillKey,
            skill_name=effective_skill.skillName,
            owner_agent=step.agentName,
            task_id=plan.id,
            pipeline_run_id=pipeline_run_id,
            agent_run_id=agent_run_id,
            status="skipped",
            summary=result.summary,
            data_sources=[],
        )
        return result

    def _persist_result_skill_usages(
        self,
        task_id: str,
        result: AgentExecutionResult,
        duration_ms: int,
        *,
        pipeline_run_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> list[AgentSkillUsageSummary]:
        usage_items: list[AgentSkillUsageSummary] = []
        for skill_key in result.usedSkills:
            skill = get_skill(skill_key)
            skill_name = skill.skillName if skill else skill_key
            persist_skill_usage(
                skill_key=skill_key,
                skill_name=skill_name,
                owner_agent=result.agentName,
                task_id=task_id,
                status="success" if result.status == "success" else result.status,
                summary=result.summary,
                data_sources=result.usedDataSources,
                error=result.error,
                duration_ms=duration_ms,
                pipeline_run_id=pipeline_run_id,
                agent_run_id=agent_run_id,
            )
            usage_items.append(AgentSkillUsageSummary(skillKey=skill_key, status=result.status, summary=result.summary))
        return usage_items

    def _confirmation_text(self, plan) -> str:
        if plan.riskLevel in {"high", "critical"}:
            return "这是高风险操作，需要二次确认后才会执行。我已经生成任务计划，但不会直接修改参数、Skill 或生产数据。"
        return "这是中风险操作，需要你确认后再执行。我已经生成任务计划，当前未触发写入动作。"

    def _compose_reply(self, intent: str, results: list[AgentExecutionResult]) -> str:
        if not results:
            return "我已经理解请求。当前问题会由 UserInteractionAgent 直接答复；如果你希望我检查交易机会、数据状态或 Agent 运行情况，请描述具体目标。"
        primary = results[0]
        if intent == "ask_no_buy_candidates":
            return self._compose_no_buy_candidates_reply(results)
        if intent in {"ask_stock_decision", "ask_trade_playbook", "ask_news_impact"}:
            return f"结论：{primary.summary} 已记录本次调用链路，可在后续日志中心按任务 ID 追踪。"
        if intent in {"ask_data_status", "run_data_diagnosis"}:
            return f"数据状态：{primary.summary}"
        if intent in {"ask_agent_logs", "ask_skill_status", "review_trade_plan", "ask_prediction_quality"}:
            return primary.summary
        return primary.summary

    def _compose_no_buy_candidates_reply(self, results: list[AgentExecutionResult]) -> str:
        by_agent = {item.agentName: item for item in results}
        actionability = by_agent.get("ActionabilityAgent")
        output = actionability.output if actionability else {}
        called_agents = "、".join(item.agentName for item in results)
        degraded = [item.agentName for item in results if item.status == "degraded"]
        lines = [
            "今天没有立即可买股票，并不是 Agent 没工作，而是当前交易条件没有触发。",
            "",
            f"本次调用了：{called_agents}。",
            "",
            "结果：",
            f"- 立即可买：{output.get('executableBuyCount', 0)} 只",
            f"- 接近买点：{output.get('nearBuyCount', 0)} 只",
            f"- 突破确认：{output.get('breakoutWatchCount', 0)} 只",
            f"- 卖出/减仓：{output.get('sellOrReduceCount', 0)} 只",
            f"- 建议规避：{output.get('avoidCount', 0)} 只",
            "",
            "主要原因：",
        ]
        reasons = output.get("reasons") if isinstance(output.get("reasons"), list) else []
        for index, reason in enumerate(reasons[:4], start=1):
            lines.append(f"{index}. {reason}")
        if not reasons:
            lines.append(f"1. {actionability.summary if actionability else '当前没有满足完整买入条件的专业结果。'}")
        risk = by_agent.get("RiskControlAgent")
        trade = by_agent.get("TradePlaybookAgent")
        data_status = by_agent.get("DataStatusAgent")
        if risk:
            lines.append(f"{len(reasons[:4]) + 1}. {risk.summary}")
        if trade:
            lines.append(f"{len(reasons[:4]) + 2}. TradePlaybookAgent：{trade.summary}")
        if data_status:
            lines.append(f"数据状态补充：{data_status.summary}")
        next_actions = output.get("nextActions") if isinstance(output.get("nextActions"), list) else []
        lines.extend(["", "你现在可以做："])
        for action in next_actions[:4] or ["查看卖出/减仓列表", "等待接近买点提醒", "重新运行 Pipeline 检查最新数据"]:
            lines.append(f"- {action}")
        if degraded:
            lines.extend(["", f"降级说明：{', '.join(degraded)} 当前使用交易剧本或可用数据摘要作为 degraded 结果。"])
        return "\n".join(lines)

    def _suggested_actions(self, intent: str) -> list[dict]:
        if intent in {"ask_data_status", "run_data_diagnosis"}:
            return [{"label": "查看数据管道诊断", "action": "open_agent_logs"}]
        if intent == "ask_no_buy_candidates":
            return [
                {"label": "查看交易剧本详情", "action": "open_trade_playbook"},
                {"label": "打开 Agent 日志中心", "action": "open_agent_logs"},
                {"label": "重新运行 Pipeline", "action": "run_pipeline"},
            ]
        if intent in {"ask_stock_decision", "ask_trade_playbook"}:
            return [{"label": "查看交易剧本详情", "action": "open_trade_playbook"}]
        if intent in {"ask_agent_logs", "ask_skill_status"}:
            return [{"label": "打开 Agent 日志中心", "action": "open_agent_logs"}]
        return []