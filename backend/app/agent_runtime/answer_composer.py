from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from .schemas import (
    AgentActionItem,
    AgentConclusion,
    AgentDataQuality,
    AgentExecutionResult,
    AgentKeyFindings,
    AgentSkillUsageSummary,
    AgentTaskPlan,
    AgentTraceItem,
    AgentUserFacingAnswer,
    RelatedStock,
    UserAgentRequest,
)

STOCK_NAME_MAP = {
    "天孚通信": ("300394.SZ", "天孚通信"),
}

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "analysis" / "agent_answer_composer.md"


class AgentAnswerComposer:
    """Builds user-facing answers from technical Agent execution results."""

    def compose(
        self,
        plan: AgentTaskPlan,
        request: UserAgentRequest,
        results: list[AgentExecutionResult],
        skill_usages: list[AgentSkillUsageSummary] | None = None,
        *,
        pipeline_run_id: str | None = None,
    ) -> AgentUserFacingAnswer:
        trace = self._technical_trace(plan.id, results, skill_usages or [])
        status = self._answer_status(results)
        if plan.intent in {"buy_decision_explanation", "ask_no_buy_candidates"}:
            answer = self._compose_buy_decision(plan, request, results, trace, status)
            return self._maybe_refine_with_llm(answer, plan, request, results)
        if plan.intent == "position_diagnosis":
            answer = self._compose_position_diagnosis(plan, request, results, trace, status)
            return self._maybe_refine_with_llm(answer, plan, request, results)
        if plan.intent == "agent_trace_summary":
            answer = self._compose_agent_trace_summary(plan, results, trace, status)
            return self._maybe_refine_with_llm(answer, plan, request, results)
        if plan.intent == "discover_opportunities":
            answer = self._compose_opportunity_discovery(plan, results, trace, status)
            return self._maybe_refine_with_llm(answer, plan, request, results)
        answer = self._compose_generic(plan, request, results, trace, status, pipeline_run_id=pipeline_run_id)
        return self._maybe_refine_with_llm(answer, plan, request, results)

    def blocked_answer(self, plan: AgentTaskPlan, reason: str) -> AgentUserFacingAnswer:
        return AgentUserFacingAnswer(
            taskId=plan.id,
            status="failed",
            intent=plan.intent,
            title="这个请求无法执行",
            directAnswer=f"这个请求我不能执行：{reason}",
            reasoningSummary=["请求触发了系统安全边界。", "系统不会执行真实下单、绕过风控或篡改审计记录。"],
            conclusion=AgentConclusion(label="已拒绝执行", action="NO_ACTION", confidence="high", riskLevel="high"),
            keyFindings=AgentKeyFindings(negative=[reason]),
            riskWarnings=[reason],
            dataQuality=AgentDataQuality(level="cached"),
        )

    def confirmation_answer(self, plan: AgentTaskPlan, confirmation_text: str) -> AgentUserFacingAnswer:
        return AgentUserFacingAnswer(
            taskId=plan.id,
            status="partial",
            intent=plan.intent,
            title="需要确认后执行",
            directAnswer=confirmation_text,
            reasoningSummary=["该任务可能修改参数、Skill 或触发重跑。", "系统已生成计划，但在你确认前不会继续执行。"],
            conclusion=AgentConclusion(label="等待确认", action="NO_ACTION", confidence="medium", riskLevel="high" if plan.riskLevel in {"high", "critical"} else "medium"),
            riskWarnings=["该操作需要确认后才能执行。"],
            dataQuality=AgentDataQuality(level="cached"),
        )

    def _compose_buy_decision(
        self,
        plan: AgentTaskPlan,
        _request: UserAgentRequest,
        results: list[AgentExecutionResult],
        trace: list[AgentTraceItem],
        status: str,
    ) -> AgentUserFacingAnswer:
        by_agent = {item.agentName: item for item in results}
        actionability = by_agent.get("ActionabilityAgent")
        output = actionability.output if actionability else {}
        executable = int(output.get("executableBuyCount") or 0)
        reasons = [str(item) for item in output.get("reasons") or [] if item]
        degraded = [item.agentName for item in results if item.status == "degraded"]
        direct = self._buy_direct_answer(output)
        if executable > 0:
            direct = f"当前存在 {executable} 只可执行候选，但仍需要按计划价位、仓位上限和止损条件逐项确认。"
        related = self._related_from_focus(output.get("topFocus") or [])
        return AgentUserFacingAnswer(
            taskId=plan.id,
            status=status,
            intent=plan.intent,
            title="为什么今天没有立即可买股票？",
            directAnswer=direct,
            reasoningSummary=self._buy_reasoning(reasons),
            conclusion=AgentConclusion(label="等待确认，不建议追高", action="WATCH" if executable == 0 else "BUY", confidence="medium" if degraded else "high", riskLevel="medium"),
            keyFindings=self._buy_key_findings(output, reasons),
            actionPlan=self._buy_action_plan(output),
            riskWarnings=self._risk_warnings(degraded),
            relatedStocks=related,
            dataQuality=self._data_quality(results),
            technicalTrace=trace,
        )

    def _buy_reasoning(self, reasons: list[str]) -> list[str]:
        reasoning = [
            "现在的问题不是系统没有发现机会，而是没有标的同时满足“买入信号、风险收益比、风控约束”三个条件。",
            "接近买点或突破确认只代表进入观察区，不等于已经满足立即买入阈值。",
            "若减仓、规避或止损信号同时存在，系统会优先保护回撤，而不是为了交易而交易。",
            "在信号未确认前，等待比追高更符合当前风控逻辑。",
        ]
        return [*reasoning, *reasons[:3]] if reasons else reasoning

    def _buy_direct_answer(self, output: dict[str, Any]) -> str:
        near_buy = int(output.get("nearBuyCount") or 0)
        breakout = int(output.get("breakoutWatchCount") or 0)
        reduce_or_sell = int(output.get("sellOrReduceCount") or 0)
        avoid = int(output.get("avoidCount") or 0)
        focus = output.get("topFocus") or []
        focus_names = [str(item.get("stockName") or item.get("stockCode") or "").strip() for item in focus[:2] if isinstance(item, dict)]
        focus_text = f"，例如 {'、'.join([item for item in focus_names if item])} 仍更适合观察确认" if focus_names else ""
        return (
            f"今天没有立即买入股票，是因为当前候选股没有同时满足买入信号、风险收益比和风控约束。"
            f"目前更像是等待确认的盘面：接近买点 {near_buy} 只、突破确认 {breakout} 只、减仓/卖出 {reduce_or_sell} 只、建议规避 {avoid} 只{focus_text}。"
            "所以系统建议先观察确认，而不是为了交易而追高。"
        )

    def _buy_key_findings(self, output: dict[str, Any], reasons: list[str]) -> AgentKeyFindings:
        near_buy = int(output.get("nearBuyCount") or 0)
        breakout = int(output.get("breakoutWatchCount") or 0)
        executable = int(output.get("executableBuyCount") or 0)
        reduce_or_sell = int(output.get("sellOrReduceCount") or 0)
        avoid = int(output.get("avoidCount") or 0)
        positive = [f"接近买点 {near_buy} 只，突破确认 {breakout} 只。"] if near_buy or breakout else []
        negative = [f"立即可买 {executable} 只。", f"减仓/卖出 {reduce_or_sell} 只，建议规避 {avoid} 只。"]
        return AgentKeyFindings(positive=positive, negative=negative, neutral=reasons[:3] or ["当前交易剧本更偏向等待确认。"])

    def _buy_action_plan(self, output: dict[str, Any]) -> list[AgentActionItem]:
        action_items = [
            AgentActionItem(condition="股票进入计划买入区或突破确认价", action="再考虑小仓执行，并同步设置止损。", priority="high"),
            AgentActionItem(condition="仍处于接近买点但未确认", action="继续观察，不追高。", priority="high"),
            AgentActionItem(condition="已经持有且出现减仓/止损信号", action="优先执行减仓或止损剧本。", priority="medium"),
        ]
        next_actions = [str(item) for item in output.get("nextActions") or [] if item]
        for item in next_actions[:2]:
            action_items.append(AgentActionItem(condition="下一轮 Pipeline 更新前", action=item, priority="medium"))
        return action_items

    def _risk_warnings(self, degraded_agents: list[str]) -> list[str]:
        warnings = []
        if degraded_agents:
            warnings.append("当前部分分析依赖降级结果，因此结论置信度为中等。")
        warnings.append("本系统仅为模型辅助分析，不构成投资建议；不要在信号未确认时强行交易。")
        return warnings

    def _compose_position_diagnosis(
        self,
        plan: AgentTaskPlan,
        request: UserAgentRequest,
        results: list[AgentExecutionResult],
        trace: list[AgentTraceItem],
        status: str,
    ) -> AgentUserFacingAnswer:
        stock = self._extract_stock(request)
        cost = self._extract_cost(request.message)
        name = stock[1] if stock else "当前持仓"
        cost_text = f"，成本价约 {cost:g} 元" if cost is not None else ""
        direct = f"{name}{cost_text} 当前应优先做风险控制，而不是盲目补仓。若价格没有重新站上关键确认位，应以谨慎持有或分批减仓为主。"
        risk_warnings = ["如果当前价格低于成本且趋势未修复，持仓风险会升高。", "不要用补仓替代止损，仓位上限应优先服从风控。"]
        degraded = [item.agentName for item in results if item.status == "degraded"]
        if degraded:
            risk_warnings.append("当前部分分析依赖降级结果，因此持仓诊断置信度为中等。")
        related = [RelatedStock(code=stock[0], name=stock[1], role="holding")] if stock else []
        return AgentUserFacingAnswer(
            taskId=plan.id,
            status=status,
            intent=plan.intent,
            title=f"{name}持仓诊断",
            directAnswer=direct,
            reasoningSummary=[
                f"已识别股票：{name}。" if stock else "尚未稳定识别股票代码，建议补充 6 位代码。",
                f"已识别成本价：{cost:g}。" if cost is not None else "尚未识别成本价，建议补充买入价。",
                "需要比较现价与成本价、支撑位、压力位和止损位。",
                "若趋势未修复，不应盲目补仓；若重新突破确认价并放量，才考虑继续持有。",
            ],
            conclusion=AgentConclusion(label="先控风险，再等确认", action="HOLD", confidence="medium", riskLevel="high"),
            keyFindings=AgentKeyFindings(
                negative=["当前问题属于持仓风险管理，第一优先级是控制回撤。"],
                neutral=["需要结合最新交易剧本、技术确认价和止损位执行。"],
            ),
            actionPlan=[
                AgentActionItem(condition="跌破交易剧本止损位", action="减仓或止损，不继续摊低成本。", priority="high"),
                AgentActionItem(condition="重新站上确认价并放量", action="谨慎持有，等待下一轮信号确认。", priority="medium"),
                AgentActionItem(condition="在成本价附近震荡", action="不要加仓，等待方向明确。", priority="medium"),
                AgentActionItem(condition="风险等级升高", action="降低仓位，优先保护本金。", priority="high"),
            ],
            riskWarnings=risk_warnings,
            relatedStocks=related,
            dataQuality=self._data_quality(results),
            technicalTrace=trace,
        )

    def _compose_agent_trace_summary(
        self,
        plan: AgentTaskPlan,
        results: list[AgentExecutionResult],
        trace: list[AgentTraceItem],
        status: str,
    ) -> AgentUserFacingAnswer:
        names = [item.agentName for item in results]
        degraded = [item.agentName for item in results if item.status == "degraded"]
        direct = "本次判断主要由交易剧本生成、风控检查、技术时机分析、预测质量和数据状态检查共同参与。"
        if names:
            direct = "本次判断主要由这些能力参与：交易剧本生成、风控检查、技术时机分析、预测质量和数据状态检查。"
        risk_warnings = []
        if degraded:
            risk_warnings.append("部分能力使用了降级结果，因此最终结论需要降低置信度看待。")
        return AgentUserFacingAnswer(
            taskId=plan.id,
            status=status,
            intent=plan.intent,
            title="哪些 Agent 参与了当前判断？",
            directAnswer=direct,
            reasoningSummary=[
                "交易剧本生成负责判断是否有可执行买入、卖出或观察条件。",
                "风控检查负责校验仓位、止损、风险收益比和追高风险。",
                "技术时机分析负责判断是否接近买点、突破确认或趋势破坏。",
                "数据状态检查用于判断结论是否依赖过期或缺失数据。",
            ],
            conclusion=AgentConclusion(label="已汇总参与能力", action="NO_ACTION", confidence="medium" if degraded else "high", riskLevel="medium"),
            keyFindings=AgentKeyFindings(
                positive=[f"已完成能力：{self._join_names([item.agentName for item in results if item.status == 'success'])}"],
                neutral=["技术链路已保留在折叠详情中。"],
                negative=["存在降级能力，结论置信度需要降低。"] if degraded else [],
            ),
            riskWarnings=risk_warnings,
            dataQuality=self._data_quality(results),
            technicalTrace=trace,
        )

    def _compose_generic(
        self,
        plan: AgentTaskPlan,
        _request: UserAgentRequest,
        results: list[AgentExecutionResult],
        trace: list[AgentTraceItem],
        status: str,
        *,
        pipeline_run_id: str | None = None,
    ) -> AgentUserFacingAnswer:
        primary = results[0] if results else None
        direct = primary.summary if primary else "我已经理解请求，但当前没有足够的专业分析结果。"
        title = "Agent 分析结果"
        if plan.intent in {"ask_data_status", "run_data_diagnosis"}:
            title = "数据状态分析"
        elif plan.intent in {"ask_stock_decision", "ask_trade_playbook"}:
            title = "交易剧本分析"
        risk_warnings = ["本系统仅为模型辅助分析，不构成投资建议。"]
        if any(item.status == "degraded" for item in results):
            risk_warnings.insert(0, "当前部分分析依赖降级结果，因此结论置信度为中等。")
        if pipeline_run_id:
            risk_warnings.append(f"本次任务已记录到 Pipeline：{pipeline_run_id}。")
        return AgentUserFacingAnswer(
            taskId=plan.id,
            status=status,
            intent=plan.intent,
            title=title,
            directAnswer=direct,
            reasoningSummary=[item.summary for item in results[:4]] or ["当前问题未触发专业 Agent 输出。"],
            conclusion=AgentConclusion(label="已完成分析" if results else "信息不足", action="NO_ACTION", confidence="medium", riskLevel="medium"),
            keyFindings=AgentKeyFindings(neutral=[item.summary for item in results[:3]]),
            actionPlan=[AgentActionItem(condition="需要进一步核验", action="展开技术详情或打开 Agent 日志中心查看调用链路。", priority="low")],
            riskWarnings=risk_warnings,
            dataQuality=self._data_quality(results),
            technicalTrace=trace,
        )

    def _compose_opportunity_discovery(
        self,
        plan: AgentTaskPlan,
        results: list[AgentExecutionResult],
        trace: list[AgentTraceItem],
        status: str,
    ) -> AgentUserFacingAnswer:
        result = next((item for item in results if item.agentName == "OpportunityDiscoveryAgent"), None)
        output = result.output if result else {}
        candidates = output.get("candidates") or []
        auto_pinned = int(output.get("autoPinnedCount") or 0)
        pending = int(output.get("pendingCount") or 0)
        top = candidates[0] if candidates else None
        direct = result.summary if result else "机会发现 Agent 暂未返回候选结果。"
        if top:
            direct = (
                f"已发现 {len(candidates)} 个潜力候选，其中 {auto_pinned} 个高置信候选已自动加入置顶，"
                f"{pending} 个进入待确认。当前首选是 {top.get('symbol')} {top.get('name') or ''}，"
                f"机会分 {top.get('opportunityScore')}。"
            )
        related = [
            RelatedStock(code=str(item.get("symbol")), name=str(item.get("name") or item.get("symbol")), role="candidate")
            for item in candidates[:5]
            if item.get("symbol")
        ]
        positives = [str(item.get("rationale")) for item in candidates[:3] if item.get("rationale")]
        actions = []
        if pending:
            actions.append(AgentActionItem(condition="待确认候选存在", action="进入机会候选列表，逐只确认是否置顶观察。", priority="medium"))
        if auto_pinned:
            actions.append(AgentActionItem(condition="高置信候选已自动置顶", action="打开置顶列表，用交易剧本确认买入价位、止损和仓位。", priority="high"))
        if not actions:
            actions.append(AgentActionItem(condition="暂无达标候选", action="等待下一轮量化信号和预测更新，不为交易而交易。", priority="low"))
        return AgentUserFacingAnswer(
            taskId=plan.id,
            status=status,
            intent=plan.intent,
            title="潜力股票机会发现",
            directAnswer=direct,
            reasoningSummary=[item.summary for item in results[:4]] or ["机会发现 Agent 未返回可用摘要。"],
            conclusion=AgentConclusion(label="已生成候选" if candidates else "暂无候选", action="WATCH", confidence="medium", riskLevel="medium"),
            keyFindings=AgentKeyFindings(positive=positives[:3], neutral=[f"扫描样本 {output.get('scanned', 0)} 个。"]),
            actionPlan=actions,
            riskWarnings=["候选只代表进入观察与剧本验证，不等同于立即买入。", "本系统仅为模型辅助分析，不构成投资建议。"],
            relatedStocks=related,
            dataQuality=self._data_quality(results),
            technicalTrace=trace,
        )

    def _maybe_refine_with_llm(
        self,
        fallback: AgentUserFacingAnswer,
        plan: AgentTaskPlan,
        request: UserAgentRequest,
        results: list[AgentExecutionResult],
    ) -> AgentUserFacingAnswer:
        if os.getenv("AGENT_ANSWER_USE_LLM", "true").lower() not in {"1", "true", "yes"}:
            return fallback
        data = self._generate_llm_answer(fallback, plan, request, results)
        if not data:
            return fallback
        return self._merge_llm_answer(fallback, data)

    def _generate_llm_answer(
        self,
        fallback: AgentUserFacingAnswer,
        plan: AgentTaskPlan,
        request: UserAgentRequest,
        results: list[AgentExecutionResult],
    ) -> dict[str, Any] | None:
        try:
            prompt_parts = self._build_llm_prompt(fallback, plan, request, results)
            if not prompt_parts:
                return None
            prompt, system_prompt = prompt_parts
            from ..news.llm_service_proxy import get_llm_service_proxy

            proxy = get_llm_service_proxy()
            if not proxy.is_available():
                return None
            try:
                asyncio.get_running_loop()
                logger.info("Skip Agent answer LLM refinement because a running event loop is already active")
                return None
            except RuntimeError:
                pass
            return asyncio.run(proxy.generate_json(prompt=prompt, system_prompt=system_prompt, temperature=0.2, max_tokens=1600))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent answer LLM refinement failed: %s", exc)
            return None

    def _build_llm_prompt(
        self,
        fallback: AgentUserFacingAnswer,
        plan: AgentTaskPlan,
        request: UserAgentRequest,
        results: list[AgentExecutionResult],
    ) -> tuple[str, str | None] | None:
        try:
            system_prompt, template = self._load_prompt_parts()
            context = request.context.model_dump(mode="json") if request.context else {}
            prompt = template.format(
                user_message=request.message,
                intent=plan.intent,
                context_json=json.dumps(context, ensure_ascii=False),
                fallback_answer_json=json.dumps(self._answer_for_prompt(fallback), ensure_ascii=False),
                agent_evidence_json=json.dumps(self._agent_evidence_for_prompt(results), ensure_ascii=False),
            )
            return prompt, system_prompt
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to build Agent answer prompt: %s", exc)
            return None

    def _load_prompt_parts(self) -> tuple[str | None, str]:
        text = PROMPT_PATH.read_text(encoding="utf-8")
        system_marker = "## System Prompt"
        user_marker = "## User Prompt Template"
        if system_marker not in text or user_marker not in text:
            return None, text
        system_text = text.split(system_marker, 1)[1].split(user_marker, 1)[0].strip()
        user_text = text.split(user_marker, 1)[1].strip()
        return system_text, user_text

    def _answer_for_prompt(self, answer: AgentUserFacingAnswer) -> dict[str, Any]:
        payload = answer.model_dump(mode="json")
        payload.pop("technicalTrace", None)
        return payload

    def _agent_evidence_for_prompt(self, results: list[AgentExecutionResult]) -> list[dict[str, Any]]:
        evidence = []
        for item in results:
            evidence.append(
                {
                    "agentName": item.agentName,
                    "status": item.status,
                    "summary": item.summary,
                    "output": self._compact_output(item.output),
                    "usedSkills": item.usedSkills,
                    "usedDataSources": item.usedDataSources,
                    "error": item.error,
                }
            )
        return evidence

    def _compact_output(self, output: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "executableBuyCount",
            "nearBuyCount",
            "breakoutWatchCount",
            "sellOrReduceCount",
            "avoidCount",
            "holdWatchCount",
            "plainSummary",
            "reasons",
            "nextActions",
            "topFocus",
            "highRiskCount",
            "riskControls",
            "modelTrackRecordSummaries",
            "technicalNotes",
            "overallStatus",
            "modules",
            "source",
        }
        compact = {key: value for key, value in output.items() if key in allowed_keys}
        if "topFocus" in compact and isinstance(compact["topFocus"], list):
            compact["topFocus"] = compact["topFocus"][:5]
        return compact

    def _merge_llm_answer(self, fallback: AgentUserFacingAnswer, data: dict[str, Any]) -> AgentUserFacingAnswer:
        merged = fallback.model_dump(mode="json")
        for key in ["title", "directAnswer", "reasoningSummary", "keyFindings", "actionPlan", "riskWarnings"]:
            if key in data and data[key]:
                merged[key] = data[key]
        if isinstance(data.get("conclusion"), dict):
            merged["conclusion"] = {**merged.get("conclusion", {}), **data["conclusion"]}
        try:
            refined = AgentUserFacingAnswer.model_validate(merged)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invalid LLM Agent answer JSON, using fallback: %s", exc)
            return fallback
        refined.technicalTrace = fallback.technicalTrace
        refined.dataQuality = fallback.dataQuality
        refined.relatedStocks = fallback.relatedStocks
        return refined

    def _technical_trace(
        self,
        task_id: str,
        results: list[AgentExecutionResult],
        skill_usages: list[AgentSkillUsageSummary],
    ) -> list[AgentTraceItem]:
        trace = [
            AgentTraceItem(
                taskId=task_id,
                agentName=item.agentName,
                skillKey=item.usedSkills[0] if item.usedSkills else None,
                status=item.status,
                userTextStatus=self._status_text(item.status),
                summary=item.summary,
                usedSkills=item.usedSkills,
                usedDataSources=item.usedDataSources,
                error=item.error,
                degradedReason=item.summary if item.status == "degraded" else None,
            )
            for item in results
        ]
        known = {item.skillKey for item in trace if item.skillKey}
        for usage in skill_usages:
            if usage.skillKey in known:
                continue
            trace.append(
                AgentTraceItem(
                    taskId=task_id,
                    agentName=usage.skillKey,
                    skillKey=usage.skillKey,
                    status=usage.status,
                    userTextStatus=self._status_text(usage.status),
                    summary=usage.summary,
                    usedSkills=[usage.skillKey],
                )
            )
        return trace

    def _answer_status(self, results: list[AgentExecutionResult]) -> str:
        if any(item.status == "failed" for item in results):
            return "failed"
        if any(item.status in {"degraded", "skipped", "timeout"} for item in results):
            return "partial"
        return "success"

    def _data_quality(self, results: list[AgentExecutionResult]) -> AgentDataQuality:
        if any(item.status == "failed" for item in results):
            return AgentDataQuality(level="insufficient", warning="部分 Agent 执行失败，结论只能作为初步参考。")
        if any(item.status == "degraded" for item in results):
            return AgentDataQuality(level="cached", warning="部分 Agent 使用可用摘要降级分析，建议结合最新行情复核。")
        return AgentDataQuality(level="cached")

    def _related_from_focus(self, rows: list[dict[str, Any]]) -> list[RelatedStock]:
        related: list[RelatedStock] = []
        for item in rows[:5]:
            code = str(item.get("stockCode") or item.get("symbol") or "").strip()
            name = str(item.get("stockName") or code or "候选股").strip()
            if code:
                related.append(RelatedStock(code=code, name=name, role="candidate"))
        return related

    def _extract_stock(self, request: UserAgentRequest) -> tuple[str, str] | None:
        if request.context and request.context.selectedStockCode:
            code = request.context.selectedStockCode.upper()
            return code, code
        for name, value in STOCK_NAME_MAP.items():
            if name in request.message:
                return value
        match = re.search(r"(\d{6})(?:\.(SH|SZ))?", request.message, re.IGNORECASE)
        if not match:
            return None
        code, suffix = match.group(1), match.group(2)
        if suffix:
            symbol = f"{code}.{suffix.upper()}"
        elif code.startswith("6"):
            symbol = f"{code}.SH"
        else:
            symbol = f"{code}.SZ"
        return symbol, symbol

    def _extract_cost(self, message: str) -> float | None:
        patterns = [
            r"(?:我|成本|买入价)?\s*(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:买|入)",
            r"(?:成本|买入价)\s*(?:是|为|:|：)?\s*(\d+(?:\.\d+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return float(match.group(1))
        return None

    def _status_text(self, status: str) -> str:
        if status == "success":
            return "已完成"
        if status == "degraded":
            return "部分数据不足，已降级分析"
        if status == "failed":
            return "分析失败"
        if status == "running":
            return "分析中"
        if status == "skipped":
            return "已跳过"
        if status == "timeout":
            return "分析超时"
        return "待处理"

    def _join_names(self, names: list[str]) -> str:
        return "、".join(names) if names else "暂无"
