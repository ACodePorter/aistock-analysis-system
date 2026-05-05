import pytest

from app.agent_runtime.adapters import AgentAdapterRegistry
from app.agent_runtime.answer_composer import AgentAnswerComposer
from app.agent_runtime.executor import AgentRuntimeExecutor
from app.agent_runtime.pipeline_orchestrator import AgentPipelineOrchestrator
from app.agent_runtime.registry import get_capability, get_skill
from app.agent_runtime.schemas import AgentExecutionResult, AgentTaskChatResponse, AgentTaskPlan, UserAgentRequest
from app.agent_runtime.task_manager_agent import TaskManagerAgent


def test_task_manager_blocks_real_order_requests():
    plan = TaskManagerAgent().plan(UserAgentRequest(message="帮我真实下单买入 600519"))

    assert plan.blockedReason == "系统不能执行真实下单或代替用户交易。"
    assert plan.riskLevel == "critical"
    assert plan.intent == "unknown"
    assert plan.requiresConfirmation is False
    assert plan.requiredAgents == ["UserInteractionAgent"]


def test_task_manager_requires_confirmation_for_skill_mutation():
    plan = TaskManagerAgent().plan(UserAgentRequest(message="禁用数据新鲜度检查 skill"))

    assert plan.intent == "manage_agent_skill"
    assert plan.riskLevel == "high"
    assert plan.requiresConfirmation is True
    assert plan.requiredAgents == ["SkillManagerAgent", "UserInteractionAgent"]
    assert "manage_agent_skill" in plan.requiredSkills


def test_task_manager_routes_data_diagnosis_as_low_risk():
    plan = TaskManagerAgent().plan(UserAgentRequest(message="检查系统关键数据状态和最近管道失败情况"))

    assert plan.intent == "run_data_diagnosis"
    assert plan.riskLevel == "low"
    assert plan.requiresConfirmation is False
    assert plan.requiredAgents == ["DataStatusAgent", "UserInteractionAgent"]
    assert "check_data_freshness" in plan.requiredSkills


def test_task_manager_routes_no_buy_question_to_professional_agents():
    plan = TaskManagerAgent().plan(UserAgentRequest(message="为什么今天没有可以买的股票？"))

    assert plan.intent == "buy_decision_explanation"
    assert plan.executionMode == "parallel"
    assert plan.riskLevel == "low"
    assert plan.requiresConfirmation is False
    assert plan.requiredAgents == [
        "ActionabilityAgent",
        "TradePlaybookAgent",
        "RiskControlAgent",
        "PriceForecastAgent",
        "TechnicalAnalysisAgent",
        "DataStatusAgent",
        "UserInteractionAgent",
    ]
    assert plan.requiredSkills == [
        "summarize_actionability",
        "generate_trade_playbook",
        "evaluate_risk_control",
        "query_price_forecast",
        "analyze_technical_timing",
        "check_data_freshness",
        "compose_user_reply",
    ]
    assert plan.steps[-1].agentName == "UserInteractionAgent"
    assert plan.steps[-1].dependsOn == plan.requiredAgents[:-1]


def test_actionability_skill_and_capability_are_registered():
    skill = get_skill("summarize_actionability")
    capability = get_capability("ActionabilityAgent")

    assert skill is not None
    assert skill.ownerAgent == "ActionabilityAgent"
    assert capability is not None
    assert "buy_decision_explanation" in capability.canHandleIntents


def test_task_manager_routes_position_diagnosis_question():
    plan = TaskManagerAgent().plan(UserAgentRequest(message="我350买了天孚通信，现在怎么办？"))

    assert plan.intent == "position_diagnosis"
    assert plan.requiredAgents == [
        "TradePlaybookAgent",
        "RiskControlAgent",
        "TechnicalAnalysisAgent",
        "PriceForecastAgent",
        "DataStatusAgent",
        "UserInteractionAgent",
    ]


def test_task_manager_routes_agent_trace_summary_question():
    plan = TaskManagerAgent().plan(UserAgentRequest(message="哪些 Agent 参与了当前判断？"))

    assert plan.intent == "agent_trace_summary"
    assert "RiskControlAgent" in plan.requiredAgents


def test_answer_composer_returns_user_facing_no_buy_answer(monkeypatch):
    monkeypatch.setenv("AGENT_ANSWER_USE_LLM", "false")
    plan = TaskManagerAgent().plan(UserAgentRequest(message="为什么今天没有可以买的股票？"))
    answer = AgentAnswerComposer().compose(
        plan,
        UserAgentRequest(message="为什么今天没有可以买的股票？"),
        [
            AgentExecutionResult(
                agentName="ActionabilityAgent",
                status="success",
                summary="立即可买 0 只，接近买点 2 只。",
                output={
                    "executableBuyCount": 0,
                    "nearBuyCount": 2,
                    "breakoutWatchCount": 1,
                    "sellOrReduceCount": 1,
                    "avoidCount": 3,
                    "reasons": ["没有股票同时满足买入区间和风控条件。"],
                    "nextActions": ["等待股票进入计划买入区。"],
                },
                usedSkills=["summarize_actionability"],
            ),
            AgentExecutionResult(agentName="RiskControlAgent", status="degraded", summary="不建议追高。"),
        ],
        [],
    )

    assert answer.title == "为什么今天没有立即可买股票？"
    assert "没有同时满足买入信号" in answer.directAnswer
    assert answer.conclusion.action == "WATCH"
    assert answer.technicalTrace[0].agentName == "ActionabilityAgent"
    assert "RiskControlAgent degraded" not in answer.directAnswer
    assert "当前部分分析依赖降级结果" in "；".join(answer.riskWarnings)


def test_answer_composer_returns_position_diagnosis_answer(monkeypatch):
    monkeypatch.setenv("AGENT_ANSWER_USE_LLM", "false")
    plan = TaskManagerAgent().plan(UserAgentRequest(message="我350买了天孚通信，现在怎么办？"))
    answer = AgentAnswerComposer().compose(plan, UserAgentRequest(message="我350买了天孚通信，现在怎么办？"), [], [])

    assert answer.intent == "position_diagnosis"
    assert answer.relatedStocks[0].code == "300394.SZ"
    assert "350" in "；".join(answer.reasoningSummary)
    assert "风险控制" in answer.directAnswer


def test_answer_composer_refines_answer_with_llm_payload(monkeypatch):
    monkeypatch.setenv("AGENT_ANSWER_USE_LLM", "true")
    composer = AgentAnswerComposer()
    monkeypatch.setattr(
        composer,
        "_generate_llm_answer",
        lambda fallback, plan, request, results: {
            "title": "为什么今天不该强行买入？",
            "directAnswer": "今天没有立即买入机会的核心原因，是候选股只进入观察区，还没有同时满足确认价、风险收益比和仓位约束。",
            "reasoningSummary": ["接近买点不等于可买，需要突破确认或回踩到计划区。"],
            "conclusion": {"label": "继续观察", "action": "WATCH", "confidence": "medium", "riskLevel": "medium"},
            "keyFindings": {"positive": [], "negative": ["立即可买 0 只。"], "neutral": ["等待下一轮信号确认。"]},
            "actionPlan": [{"condition": "未突破确认价", "action": "不追高，设置提醒。", "priority": "high"}],
            "riskWarnings": ["部分分析依赖降级结果，结论按中等置信度看待。"],
        },
    )
    plan = TaskManagerAgent().plan(UserAgentRequest(message="为什么今天没有可以买的股票？"))

    answer = composer.compose(
        plan,
        UserAgentRequest(message="为什么今天没有可以买的股票？"),
        [AgentExecutionResult(agentName="RiskControlAgent", status="degraded", summary="不建议追高。")],
        [],
    )

    assert answer.title == "为什么今天不该强行买入？"
    assert "候选股只进入观察区" in answer.directAnswer
    assert answer.conclusion.label == "继续观察"
    assert answer.technicalTrace[0].agentName == "RiskControlAgent"


def test_executor_composes_no_buy_reply_from_agent_results():
    reply = AgentRuntimeExecutor()._compose_reply(
        "ask_no_buy_candidates",
        [
            AgentExecutionResult(
                agentName="ActionabilityAgent",
                status="success",
                summary="立即可买 0 只，接近买点 2 只。",
                output={
                    "executableBuyCount": 0,
                    "nearBuyCount": 2,
                    "breakoutWatchCount": 1,
                    "sellOrReduceCount": 1,
                    "avoidCount": 3,
                    "reasons": ["没有股票同时满足买入区间和风控条件。"],
                    "nextActions": ["等待股票进入计划买入区。"],
                },
            ),
            AgentExecutionResult(
                agentName="RiskControlAgent",
                status="degraded",
                summary="不建议追高。",
            ),
        ],
    )

    assert "本次调用了：ActionabilityAgent、RiskControlAgent" in reply
    assert "立即可买：0 只" in reply
    assert "接近买点：2 只" in reply
    assert "没有股票同时满足买入区间和风控条件" in reply
    assert "降级说明" in reply
    assert "当前没有需要调用的专业 Agent" not in reply


def test_actionability_agent_outputs_structured_counts(monkeypatch):
    registry = AgentAdapterRegistry()
    plan = TaskManagerAgent().plan(UserAgentRequest(message="为什么今天没有可以买的股票？"))

    monkeypatch.setattr(
        registry,
        "_load_tomorrow_playbook",
        lambda limit=20: {
            "executableNow": [],
            "waitForPullback": [{"stockCode": "002594.SZ", "stockName": "比亚迪"}],
            "waitForBreakout": [{"stockCode": "300750.SZ", "stockName": "宁德时代"}],
            "holdWatch": [],
            "reduceOrSell": [{"stockCode": "600519.SH", "stockName": "贵州茅台"}],
            "avoid": [{"stockCode": "000001.SZ", "stockName": "平安银行"}],
            "topFocus": [{"stockCode": "002594.SZ", "stockName": "比亚迪", "actionCategory": "wait_for_pullback"}],
        },
    )

    result = registry.execute("ActionabilityAgent", plan, UserAgentRequest(message="为什么今天没有可以买的股票？"))

    assert result.status == "success"
    assert result.output["executableBuyCount"] == 0
    assert result.output["nearBuyCount"] == 1
    assert result.output["breakoutWatchCount"] == 1
    assert result.output["sellOrReduceCount"] == 1
    assert result.output["avoidCount"] == 1
    assert result.output["reasons"]
    assert result.output["nextActions"]
    assert result.usedSkills == ["summarize_actionability"]


def test_playbook_backed_agents_return_success_when_evidence_exists(monkeypatch):
    registry = AgentAdapterRegistry()
    plan = TaskManagerAgent().plan(UserAgentRequest(message="为什么今天没有可以买的股票？"))
    payload = {
        "playbook": {
            "stockCode": "002594.SZ",
            "stockName": "比亚迪",
            "riskLevel": "high",
            "riskSummary": "当前风险偏高，风险评分约76/100。",
            "riskControl": ["最大仓位不超过 10%。"],
            "modelTrackRecord": {"plainSummary": "近窗方向准确率约 63.0%。", "sampleCount": 40, "directionAccuracy": 63.0},
            "expectedReturnRange": [2.1, 4.3],
            "buyPlan": {"idealBuyRange": [97.8, 99.2], "breakoutBuyAbove": 102.97},
        }
    }
    monkeypatch.setattr(registry, "_load_playbook_payload", lambda request: payload)

    request = UserAgentRequest(message="002594 今天能不能买？")
    risk_result = registry.execute("RiskControlAgent", plan, request)
    forecast_result = registry.execute("PriceForecastAgent", plan, request)
    technical_result = registry.execute("TechnicalAnalysisAgent", plan, request)

    assert risk_result.status == "success"
    assert risk_result.output["highRiskCount"] == 1
    assert risk_result.output["source"] == "trade_playbook_service"
    assert forecast_result.status == "success"
    assert "近窗方向准确率" in forecast_result.summary
    assert forecast_result.output["expectedReturnRanges"] == [[2.1, 4.3]]
    assert technical_result.status == "success"
    assert technical_result.output["technicalNotes"]


def test_pipeline_orchestrator_requires_user_question_message():
    orchestrator = AgentPipelineOrchestrator()

    with pytest.raises(ValueError, match="user-question pipeline requires message"):
        orchestrator._messages_for("user-question", None)


def test_pipeline_orchestrator_marks_confirmation_as_partial_success():
    orchestrator = AgentPipelineOrchestrator()

    assert orchestrator._final_status([_response(requires_confirmation=True)]) == "partial_success"


def test_pipeline_orchestrator_marks_skipped_step_as_partial_success():
    orchestrator = AgentPipelineOrchestrator()

    assert orchestrator._final_status([_response(status="skipped")]) == "partial_success"


def _response(status: str = "success", requires_confirmation: bool = False) -> AgentTaskChatResponse:
    return AgentTaskChatResponse(
        reply="ok",
        taskPlan=AgentTaskPlan(
            id="agtask_test",
            userMessage="检查数据",
            intent="ask_data_status",
            requiredAgents=["DataStatusAgent"],
            requiredSkills=["check_data_freshness"],
        ),
        requiresConfirmation=requires_confirmation,
        agentResults=[]
        if requires_confirmation
        else [
            AgentExecutionResult(
                agentName="DataStatusAgent",
                status=status,
                summary="done",
            )
        ],
    )