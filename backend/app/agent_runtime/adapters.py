from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from ..core.db import SessionLocal
from ..core.models import (
    AgentJob,
    AgentRuntimeRun,
    AgentRuntimeSkillUsage,
    Forecast,
    FundFlowDaily,
    PipelineRun,
    PriceDaily,
    Report,
)
from .registry import list_default_skills
from .schemas import AgentExecutionResult, AgentTaskPlan, UserAgentRequest


def _selected_symbol(request: UserAgentRequest) -> str | None:
    if request.context and request.context.selectedStockCode:
        return request.context.selectedStockCode.upper()
    import re

    match = re.search(r"(\d{6})(?:\.(SH|SZ))?", request.message, re.IGNORECASE)
    if not match:
        return None
    code, suffix = match.group(1), match.group(2)
    if suffix:
        return f"{code}.{suffix.upper()}"
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentAdapterRegistry:
    def execute(self, agent_name: str, plan: AgentTaskPlan, request: UserAgentRequest) -> AgentExecutionResult:
        handlers = {
            "ActionabilityAgent": self._run_actionability_agent,
            "DataStatusAgent": self._run_data_status_agent,
            "TradePlaybookAgent": self._run_trade_playbook_agent,
            "RiskControlAgent": self._run_risk_control_agent,
            "PriceForecastAgent": self._run_price_forecast_agent,
            "TechnicalAnalysisAgent": self._run_technical_analysis_agent,
            "OpportunityDiscoveryAgent": self._run_opportunity_discovery_agent,
            "ReviewAgent": self._run_review_agent,
            "SkillManagerAgent": self._run_skill_manager_agent,
            "LogAuditAgent": self._run_log_audit_agent,
            "ParameterAgent": self._run_parameter_agent,
            "UserInteractionAgent": self._run_user_interaction_agent,
        }
        handler = handlers.get(agent_name)
        if handler is None:
            return AgentExecutionResult(
                agentName=agent_name,
                status="degraded",
                summary=f"{agent_name} adapter 尚未完整接入，本次使用可用交易剧本摘要作为降级结果。",
            )
        try:
            return handler(plan, request)
        except Exception as exc:  # noqa: BLE001
            return AgentExecutionResult(
                agentName=agent_name,
                status="failed",
                summary=f"{agent_name} 执行失败：{str(exc)[:160]}",
                error=str(exc),
            )

    def _run_actionability_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        payload = self._load_tomorrow_playbook(limit=20)
        executable = payload.get("executableNow") or []
        near_buy = payload.get("waitForPullback") or []
        breakout = payload.get("waitForBreakout") or []
        reduce_or_sell = payload.get("reduceOrSell") or []
        avoid = payload.get("avoid") or []
        hold_watch = payload.get("holdWatch") or []
        all_playbooks = self._extract_playbooks(payload)
        holding_count = sum(1 for item in all_playbooks if (item.get("positionContext") or {}).get("isHolding"))
        reasons = []
        if not executable:
            reasons.append("当前股票池没有股票同时满足计划买入价位、风险阈值和模型置信度要求。")
        if not near_buy and not breakout:
            reasons.append("接近买点和突破确认列表为空，说明多数股票仍未进入计划执行区。")
        if reduce_or_sell or avoid:
            reasons.append(f"当前更需要关注 {len(reduce_or_sell)} 只卖出/减仓和 {len(avoid)} 只规避股票，而不是追高买入。")
        if not reasons:
            reasons.append("存在可关注标的，但仍需按交易剧本价位和风控条件逐项确认。")
        next_actions = [
            "优先查看卖出/减仓与规避列表，避免把风险信号误判为买入机会。",
            "等待股票进入计划买入区或突破确认区，再考虑小仓执行。",
            "必要时重新运行 Pipeline，确认行情、预测和交易剧本是否已更新。",
        ]
        summary = (
            f"立即可买 {len(executable)} 只，接近买点 {len(near_buy)} 只，突破确认 {len(breakout)} 只，"
            f"卖出/减仓 {len(reduce_or_sell)} 只，建议规避 {len(avoid)} 只，持有观察 {len(hold_watch)} 只；"
            f"其中已有持仓 {holding_count} 只。"
        )
        return AgentExecutionResult(
            agentName="ActionabilityAgent",
            status="success",
            summary=summary,
            output={
                "executableBuyCount": len(executable),
                "nearBuyCount": len(near_buy),
                "breakoutWatchCount": len(breakout),
                "sellOrReduceCount": len(reduce_or_sell),
                "avoidCount": len(avoid),
                "holdWatchCount": len(hold_watch),
                "holdingCount": holding_count,
                "plainSummary": summary,
                "reasons": reasons,
                "nextActions": next_actions,
                "topFocus": self._compact_playbooks(payload.get("topFocus") or []),
            },
            usedSkills=["summarize_actionability"],
            usedDataSources=["trade_playbook_service", "user_positions"],
        )

    def _run_risk_control_agent(self, _plan: AgentTaskPlan, request: UserAgentRequest) -> AgentExecutionResult:
        payload = self._load_playbook_payload(request)
        playbooks = self._extract_playbooks(payload)
        if not playbooks:
            return AgentExecutionResult(
                agentName="RiskControlAgent",
                status="degraded",
                summary="风控 Agent 暂未读取到可用交易剧本样本，无法形成完整仓位与止损约束。",
                output={"highRiskCount": 0, "riskControls": [], "source": "missing_playbook"},
                usedSkills=["evaluate_risk_control"],
                usedDataSources=["trade_playbook_service"],
            )
        high_risk = [item for item in playbooks if str(item.get("riskLevel") or "").lower() in {"high", "extreme"}]
        held = [item for item in playbooks if (item.get("positionContext") or {}).get("isHolding")]
        controls = [text for item in playbooks for text in (item.get("riskControl") or [])][:5]
        risk_summaries = [str(item.get("riskSummary") or "").strip() for item in playbooks if item.get("riskSummary")]
        risk_levels = sorted({str(item.get("riskLevel") or "unknown").lower() for item in playbooks if item.get("riskLevel")})
        summary = f"风控 Agent 已读取 {len(playbooks)} 个交易剧本样本，其中已有持仓 {len(held)} 个，发现 {len(high_risk)} 个高风险样本。"
        if controls:
            summary += f" 关键约束：{'；'.join(controls[:2])}。"
        elif risk_summaries:
            summary += f" 风险摘要：{risk_summaries[0]}"
        return AgentExecutionResult(
            agentName="RiskControlAgent",
            status="success",
            summary=summary,
            output={
                "sampleCount": len(playbooks),
                "holdingCount": len(held),
                "highRiskCount": len(high_risk),
                "riskControls": controls,
                "riskLevels": risk_levels,
                "riskSummaries": risk_summaries[:3],
                "source": "trade_playbook_service",
            },
            usedSkills=["evaluate_risk_control"],
            usedDataSources=["trade_playbook_service", "user_positions"],
        )

    def _run_price_forecast_agent(self, _plan: AgentTaskPlan, request: UserAgentRequest) -> AgentExecutionResult:
        payload = self._load_playbook_payload(request)
        playbooks = self._extract_playbooks(payload)
        forecast_view = self._agent_view_points(payload, "priceForecast")
        details = payload.get("professionalDetails") if isinstance(payload.get("professionalDetails"), dict) else {}
        prediction = details.get("prediction") if isinstance(details.get("prediction"), dict) else {}
        records = [item.get("modelTrackRecord") or {} for item in playbooks if isinstance(item.get("modelTrackRecord"), dict)]
        summaries = [str(item.get("plainSummary") or "").strip() for item in records if item.get("plainSummary")][:3]
        usable_records = [
            item for item in records
            if (item.get("sampleCount") or 0) > 0 or item.get("directionAccuracy") is not None or item.get("mape") is not None
        ]
        expected_ranges = [item.get("expectedReturnRange") for item in playbooks if item.get("expectedReturnRange")]
        prediction_fields = [prediction.get("directionProbUp"), prediction.get("predictedReturn"), prediction.get("confidence")]
        has_forecast_evidence = bool(usable_records or expected_ranges or any(value is not None for value in prediction_fields))
        if not has_forecast_evidence:
            summary = "价格预测 Agent 未读取到可用预测区间、方向概率或历史命中样本，预测侧仍需降级参考。"
            if summaries:
                summary += f" {'；'.join(summaries)}"
            return AgentExecutionResult(
                agentName="PriceForecastAgent",
                status="degraded",
                summary=summary,
                output={"modelTrackRecordSummaries": summaries, "source": "insufficient_forecast_evidence"},
                usedSkills=["query_price_forecast"],
                usedDataSources=["trade_playbook_service", "qe_predictions", "forecasts"],
            )

        summary_parts = []
        if expected_ranges:
            summary_parts.append(f"短线预期收益区间 {expected_ranges[0]}")
        if summaries:
            summary_parts.append(summaries[0])
        if forecast_view:
            summary_parts.append(forecast_view[0])
        summary = "价格预测 Agent 已读取预测区间、方向概率或历史表现证据。" + (f" {'；'.join(summary_parts[:3])}" if summary_parts else "")
        return AgentExecutionResult(
            agentName="PriceForecastAgent",
            status="success",
            summary=summary,
            output={
                "modelTrackRecordSummaries": summaries,
                "expectedReturnRanges": expected_ranges[:3],
                "prediction": prediction,
                "forecastPoints": forecast_view[:3],
                "source": "trade_playbook_service",
            },
            usedSkills=["query_price_forecast"],
            usedDataSources=["trade_playbook_service", "qe_predictions", "forecasts"],
        )

    def _run_technical_analysis_agent(self, _plan: AgentTaskPlan, request: UserAgentRequest) -> AgentExecutionResult:
        payload = self._load_playbook_payload(request)
        playbooks = self._extract_playbooks(payload)
        technical_points = self._agent_view_points(payload, "technicalTiming")
        technical_notes: list[str] = []
        for item in playbooks[:5]:
            name = item.get("stockName") or item.get("stockCode") or "标的"
            buy_plan = item.get("buyPlan") or {}
            ideal_range = buy_plan.get("idealBuyRange")
            breakout = buy_plan.get("breakoutBuyAbove")
            do_not_chase = buy_plan.get("doNotChaseAbove")
            if ideal_range or breakout:
                technical_notes.append(f"{name}：买入区 {ideal_range or '-'}，突破确认价 {breakout or '-'}，不追高线 {do_not_chase or '-'}")
        if not technical_notes and not technical_points:
            return AgentExecutionResult(
                agentName="TechnicalAnalysisAgent",
                status="degraded",
                summary="TechnicalAnalysisAgent 未读取到买入区、突破确认价或技术理由，技术侧暂时只能降级参考。",
                output={"technicalNotes": [], "source": "insufficient_technical_evidence"},
                usedSkills=["analyze_technical_timing"],
                usedDataSources=["trade_playbook_service", "qe_signals", "prices_daily"],
            )
        summary = "TechnicalAnalysisAgent 已读取交易剧本价位与技术条件。"
        if technical_notes:
            summary += f" {'；'.join(technical_notes[:2])}。"
        elif technical_points:
            summary += f" {technical_points[0]}"
        return AgentExecutionResult(
            agentName="TechnicalAnalysisAgent",
            status="success",
            summary=summary,
            output={"technicalNotes": technical_notes, "technicalPoints": technical_points[:3], "source": "trade_playbook_service"},
            usedSkills=["analyze_technical_timing"],
            usedDataSources=["trade_playbook_service", "qe_signals", "prices_daily"],
        )

    def _load_tomorrow_playbook(self, *, limit: int = 12) -> dict[str, Any]:
        from ..services.trade_playbook_service import build_tomorrow_playbook

        with SessionLocal() as session:
            return build_tomorrow_playbook(session, limit=limit)

    def _load_playbook_payload(self, request: UserAgentRequest) -> dict[str, Any]:
        from ..services.trade_playbook_service import build_stock_trade_playbook

        symbol = _selected_symbol(request)
        if symbol:
            with SessionLocal() as session:
                return build_stock_trade_playbook(session, symbol)
        return self._load_tomorrow_playbook(limit=12)

    def _extract_playbooks(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(payload.get("playbook"), dict):
            return [payload["playbook"]]
        groups = ["executableNow", "waitForPullback", "waitForBreakout", "holdWatch", "reduceOrSell", "avoid", "topFocus"]
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for group in groups:
            for item in payload.get(group) or []:
                key = str(item.get("stockCode") or item.get("symbol") or id(item))
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
        return items

    def _agent_view_points(self, payload: dict[str, Any], key: str) -> list[str]:
        views = payload.get("agentViews") if isinstance(payload.get("agentViews"), dict) else {}
        view = views.get(key) if isinstance(views, dict) else None
        if not isinstance(view, dict):
            return []
        return [str(item).strip() for item in (view.get("points") or []) if str(item or "").strip()]

    def _compact_playbooks(self, playbooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "stockCode": item.get("stockCode"),
                "stockName": item.get("stockName"),
                "actionCategory": item.get("actionCategory"),
                "actionLabel": item.get("actionLabel"),
                "confidenceScore": item.get("confidenceScore"),
                "riskLevel": item.get("riskLevel"),
                "positionContext": item.get("positionContext"),
            }
            for item in playbooks[:5]
        ]

    def _run_data_status_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        now = _utc_now()
        with SessionLocal() as session:
            latest_price = session.execute(select(func.max(PriceDaily.trade_date))).scalar()
            latest_forecast = session.execute(select(func.max(Forecast.run_at))).scalar()
            latest_fundflow = session.execute(select(func.max(FundFlowDaily.trade_date))).scalar()
            latest_report = session.execute(select(func.max(Report.created_at))).scalar()
            latest_pipeline = session.execute(select(PipelineRun).order_by(PipelineRun.run_at.desc()).limit(1)).scalar_one_or_none()
            failed_pipeline_count = session.execute(
                select(func.count(PipelineRun.id)).where(
                    PipelineRun.status == "failed",
                    PipelineRun.run_at >= now - timedelta(hours=24),
                )
            ).scalar() or 0

        modules = [
            {"module": "market_price", "lastUpdatedAt": latest_price.isoformat() if latest_price else None},
            {"module": "prediction", "lastUpdatedAt": latest_forecast.isoformat() if latest_forecast else None},
            {"module": "capital_flow", "lastUpdatedAt": latest_fundflow.isoformat() if latest_fundflow else None},
            {"module": "trade_playbook", "lastUpdatedAt": latest_report.isoformat() if latest_report else None},
            {
                "module": "pipeline",
                "lastUpdatedAt": latest_pipeline.run_at.isoformat() if latest_pipeline and latest_pipeline.run_at else None,
                "status": latest_pipeline.status if latest_pipeline else "missing",
                "issue": f"最近24小时有 {failed_pipeline_count} 次 pipeline 失败" if failed_pipeline_count else None,
            },
        ]
        overall = "healthy" if latest_price and failed_pipeline_count == 0 else "partial"
        summary = "关键数据可查询，最近 24 小时未发现 pipeline 失败。" if overall == "healthy" else "部分数据或 pipeline 存在缺口，需要查看诊断详情。"
        return AgentExecutionResult(
            agentName="DataStatusAgent",
            status="success",
            summary=summary,
            output={"overallStatus": overall, "modules": modules},
            usedSkills=["check_data_freshness"],
            usedDataSources=["prices_daily", "forecasts", "fundflow_daily", "reports", "pipeline_runs"],
        )

    def _run_trade_playbook_agent(self, _plan: AgentTaskPlan, request: UserAgentRequest) -> AgentExecutionResult:
        from ..services.trade_playbook_service import build_stock_trade_playbook, build_tomorrow_playbook

        symbol = _selected_symbol(request)
        with SessionLocal() as session:
            if symbol:
                payload = build_stock_trade_playbook(session, symbol)
                playbook = payload.get("playbook") or {}
                summary = playbook.get("plainSummary") or f"已生成 {symbol} 的交易剧本。"
                position = playbook.get("positionContext") or {}
                if position.get("isHolding"):
                    summary += f" 已识别当前持仓 {position.get('quantity')} 股，成本 {position.get('avgCost')}，浮盈亏 {position.get('unrealizedPnlPct')}%。"
            else:
                payload = build_tomorrow_playbook(session, limit=12)
                summary = (payload.get("marketSummary") or {}).get("plainSummary") or "已生成明日交易剧本概览。"
        return AgentExecutionResult(
            agentName="TradePlaybookAgent",
            status="success",
            summary=summary,
            output=payload,
            usedSkills=["generate_trade_playbook"],
            usedDataSources=["trade_playbook_service", "user_positions", "prices_daily", "qe_signals", "qe_predictions", "fundflow_daily"],
        )

    def _run_review_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        from ..services.trade_playbook_service import build_tomorrow_playbook

        with SessionLocal() as session:
            payload = build_tomorrow_playbook(session, limit=12)
        review = payload.get("yesterdayReviewSummary") or {}
        summary = review.get("plainSummary") or "暂无足够复盘样本。"
        return AgentExecutionResult(
            agentName="ReviewAgent",
            status="success",
            summary=summary,
            output={"reviewSummary": review, "reviews": payload.get("reviews", [])},
            usedSkills=["review_trade_plan"],
            usedDataSources=["trade_playbook_service", "prediction_evaluations"],
        )

    def _run_opportunity_discovery_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        from ..services.opportunity_discovery_service import discover_opportunities

        with SessionLocal() as session:
            payload = discover_opportunities(session, scan_limit=160, max_candidates=20, auto_pin=True)
            session.commit()
        candidates = payload.get("candidates") or []
        auto_pinned = payload.get("autoPinnedCount") or 0
        pending = payload.get("pendingCount") or 0
        top = candidates[0] if candidates else None
        if top:
            summary = (
                f"机会发现已扫描 {payload.get('scanned')} 个最新信号，生成 {len(candidates)} 个候选，"
                f"自动置顶 {auto_pinned} 个，待确认 {pending} 个。首选候选 {top.get('symbol')} "
                f"{top.get('name') or ''}，机会分 {top.get('opportunityScore')}。"
            )
        else:
            summary = f"机会发现已扫描 {payload.get('scanned')} 个最新信号，暂无达到阈值且未持仓/未置顶的候选。"
        return AgentExecutionResult(
            agentName="OpportunityDiscoveryAgent",
            status="success",
            summary=summary,
            output=payload,
            usedSkills=["discover_investment_opportunities"],
            usedDataSources=["qe_signals", "qe_predictions", "stock_pool_members", "watchlist", "user_positions"],
        )

    def _run_skill_manager_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        skills = list(list_default_skills())
        enabled = sum(1 for item in skills if item.enabled)
        high_risk = sum(1 for item in skills if item.riskLevel in {"high", "critical"})
        return AgentExecutionResult(
            agentName="SkillManagerAgent",
            status="success",
            summary=f"当前注册 {len(skills)} 个 Skill，启用 {enabled} 个，高风险 {high_risk} 个。",
            output={"skills": [item.model_dump(mode="json") for item in skills], "enabledCount": enabled, "highRiskCount": high_risk},
            usedSkills=["manage_agent_skill"],
            usedDataSources=["in_memory_skill_registry"],
        )

    def _run_log_audit_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        since = _utc_now() - timedelta(hours=24)
        with SessionLocal() as session:
            agent_runs = session.execute(
                select(AgentRuntimeRun).order_by(AgentRuntimeRun.started_at.desc()).limit(20)
            ).scalars().all()
            skill_usages = session.execute(
                select(AgentRuntimeSkillUsage).order_by(AgentRuntimeSkillUsage.started_at.desc()).limit(20)
            ).scalars().all()
            failed_pipelines = session.execute(
                select(func.count(PipelineRun.id)).where(PipelineRun.status == "failed", PipelineRun.run_at >= since)
            ).scalar() or 0
            legacy_jobs = session.execute(
                select(AgentJob).order_by(AgentJob.created_at.desc()).limit(10)
            ).scalars().all()
        failed_agents = sorted({row.agent_name for row in agent_runs if row.status == "failed"})
        failed_skills = sorted({row.skill_key for row in skill_usages if row.status == "failed"})
        overall = "healthy" if not failed_agents and not failed_skills and failed_pipelines == 0 else "degraded"
        summary = f"最近运行记录中失败 Agent {len(failed_agents)} 个，失败 Skill {len(failed_skills)} 个，24h 数据 pipeline 失败 {failed_pipelines} 次。"
        return AgentExecutionResult(
            agentName="LogAuditAgent",
            status="success",
            summary=summary,
            output={
                "overallStatus": overall,
                "failedAgents": failed_agents,
                "failedSkills": failed_skills,
                "failedPipelineRuns24h": failed_pipelines,
                "recentAgentRuns": [self._run_row(row) for row in agent_runs],
                "recentSkillUsages": [self._usage_row(row) for row in skill_usages],
                "legacyAgentJobs": [self._legacy_job(row) for row in legacy_jobs],
            },
            usedSkills=["query_agent_logs"],
            usedDataSources=["agent_runtime_runs", "agent_runtime_skill_usages", "pipeline_runs", "agent_jobs"],
        )

    def _run_parameter_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        return AgentExecutionResult(
            agentName="ParameterAgent",
            status="success",
            summary="已识别为参数调整请求。本阶段只生成草案和影响说明，不直接修改任何生产参数。",
            output={
                "draftOnly": True,
                "requiresConfirmation": True,
                "suggestedDraft": {
                    "tone": "slightly_more_active",
                    "constraints": ["不提高单票最大仓位", "不关闭止损", "只降低观察门槛，不改变风控否决条件"],
                },
            },
            usedSkills=["draft_parameter_change"],
            usedDataSources=["core.constants", "model_lifecycle_events"],
        )

    def _run_user_interaction_agent(self, _plan: AgentTaskPlan, _request: UserAgentRequest) -> AgentExecutionResult:
        return AgentExecutionResult(
            agentName="UserInteractionAgent",
            status="success",
            summary="已生成用户可读回复。",
            output={},
            usedSkills=["compose_user_reply"],
        )

    def _run_row(self, row: AgentRuntimeRun) -> dict[str, Any]:
        return {
            "runId": row.run_id,
            "agentName": row.agent_name,
            "status": row.status,
            "startedAt": row.started_at.isoformat() if row.started_at else None,
            "durationMs": row.duration_ms,
            "summary": row.output_summary,
            "error": row.error,
        }

    def _usage_row(self, row: AgentRuntimeSkillUsage) -> dict[str, Any]:
        return {
            "usageId": row.usage_id,
            "skillKey": row.skill_key,
            "ownerAgent": row.owner_agent,
            "status": row.status,
            "startedAt": row.started_at.isoformat() if row.started_at else None,
            "durationMs": row.duration_ms,
            "summary": row.output_summary,
            "error": row.error,
        }

    def _legacy_job(self, row: AgentJob) -> dict[str, Any]:
        return {
            "jobId": row.job_id,
            "status": row.status,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "durationSec": row.duration_sec,
            "error": row.error_message,
        }