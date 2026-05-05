from __future__ import annotations

import re
import uuid

from .schemas import AgentTaskPlan, AgentTaskStep, UserAgentRequest


FORBIDDEN_PATTERNS = [
    (r"真实下单|实盘下单|帮我买入|帮我卖出|place\s+order|real\s+order", "系统不能执行真实下单或代替用户交易。"),
    (r"保证收益|稳赚|一定赚钱|guarantee\s+profit", "系统不能承诺收益。"),
    (r"关闭.*风控|绕过.*风控|disable.*risk", "系统不能关闭或绕过风控。"),
    (r"删除.*审计|伪造.*日志|伪造.*运行结果|delete.*audit|fake.*log", "系统不能删除、伪造或篡改审计记录。"),
]

NO_BUY_PATTERNS = [
    r"(为什么|为何).*(没有|无).*(可买|可以买|买入|立即可买)",
    r"没有.*(立即可买|可以买|可买)",
    r"都是等待价位",
    r"今天.*(要操作什么|怎么操作)",
    r"哪.*(最接近买点|接近买点)",
]

POSITION_PATTERNS = [
    r"我.*\d+(?:\.\d+)?.*(买|入).*(现在怎么办|怎么办|怎么处理|要卖吗|补仓|止损)",
    r"(成本|买入价).*\d+(?:\.\d+)?.*(现在怎么办|怎么办|怎么处理|要卖吗|补仓|止损)",
]

AGENT_TRACE_PATTERNS = [
    r"哪些.*agent.*(参与|判断|调用)",
    r"agent.*(参与|调用).*当前判断",
    r"谁.*参与.*判断",
]

SIMPLE_INTENT_PATTERNS = [
    (r"(发现|挖掘|扫描|推荐).*(潜力股|机会|候选|可以买|买入标的)|opportunit", "discover_opportunities"),
    (r"agent.*(正常|状态|工作)|当前.*agent", "ask_agent_status"),
    (r"日志|运行历史|哪个.*agent|失败最多|审计|pipeline.*跑|log", "ask_agent_logs"),
    (r"重新生成.*(明日|操作清单|交易剧本)|重新计算|rerun|regenerate", "regenerate_playbook"),
    (r"参数|阈值|积极|保守|仓位|风险.*调|调参|parameter", "adjust_parameters"),
    (r"复盘|昨天.*计划|准不准|命中|review", "review_trade_plan"),
    (r"新闻.*(参与|影响|情绪)|舆情|news", "ask_news_impact"),
    (r"预测.*(质量|准确|表现)|模型.*表现|prediction", "ask_prediction_quality"),
    (r"为什么|怎么买|能不能买|观望|等回调|低吸|交易剧本|操作清单|买入|止损", "ask_stock_decision"),
]


INTENT_AGENT_MAP: dict[str, tuple[list[str], list[str], str, str, bool]] = {
    "buy_decision_explanation": (
        [
            "ActionabilityAgent",
            "TradePlaybookAgent",
            "RiskControlAgent",
            "PriceForecastAgent",
            "TechnicalAnalysisAgent",
            "DataStatusAgent",
            "UserInteractionAgent",
        ],
        [
            "summarize_actionability",
            "generate_trade_playbook",
            "evaluate_risk_control",
            "query_price_forecast",
            "analyze_technical_timing",
            "check_data_freshness",
            "compose_user_reply",
        ],
        "parallel",
        "low",
        False,
    ),
    "ask_no_buy_candidates": (
        [
            "ActionabilityAgent",
            "TradePlaybookAgent",
            "RiskControlAgent",
            "PriceForecastAgent",
            "TechnicalAnalysisAgent",
            "DataStatusAgent",
            "UserInteractionAgent",
        ],
        [
            "summarize_actionability",
            "generate_trade_playbook",
            "evaluate_risk_control",
            "query_price_forecast",
            "analyze_technical_timing",
            "check_data_freshness",
            "compose_user_reply",
        ],
        "parallel",
        "low",
        False,
    ),
    "ask_data_status": (["DataStatusAgent", "UserInteractionAgent"], ["check_data_freshness", "compose_user_reply"], "single_agent", "low", False),
    "run_data_diagnosis": (["DataStatusAgent", "UserInteractionAgent"], ["check_data_freshness", "compose_user_reply"], "single_agent", "low", False),
    "ask_agent_status": (["LogAuditAgent", "UserInteractionAgent"], ["query_agent_logs", "compose_user_reply"], "single_agent", "low", False),
    "ask_agent_logs": (["LogAuditAgent", "UserInteractionAgent"], ["query_agent_logs", "compose_user_reply"], "single_agent", "low", False),
    "agent_trace_summary": (["TradePlaybookAgent", "RiskControlAgent", "TechnicalAnalysisAgent", "PriceForecastAgent", "DataStatusAgent", "UserInteractionAgent"], ["generate_trade_playbook", "evaluate_risk_control", "analyze_technical_timing", "query_price_forecast", "check_data_freshness", "compose_user_reply"], "sequential", "low", False),
    "position_diagnosis": (["TradePlaybookAgent", "RiskControlAgent", "TechnicalAnalysisAgent", "PriceForecastAgent", "DataStatusAgent", "UserInteractionAgent"], ["generate_trade_playbook", "evaluate_risk_control", "analyze_technical_timing", "query_price_forecast", "check_data_freshness", "compose_user_reply"], "sequential", "low", False),
    "ask_stock_decision": (["TradePlaybookAgent", "RiskControlAgent", "TechnicalAnalysisAgent", "UserInteractionAgent"], ["generate_trade_playbook", "evaluate_risk_control", "analyze_technical_timing", "compose_user_reply"], "sequential", "low", False),
    "ask_trade_playbook": (["TradePlaybookAgent", "RiskControlAgent", "TechnicalAnalysisAgent", "UserInteractionAgent"], ["generate_trade_playbook", "evaluate_risk_control", "analyze_technical_timing", "compose_user_reply"], "sequential", "low", False),
    "ask_news_impact": (["TradePlaybookAgent", "UserInteractionAgent"], ["generate_trade_playbook", "compose_user_reply"], "sequential", "low", False),
    "ask_prediction_quality": (["ReviewAgent", "PriceForecastAgent", "UserInteractionAgent"], ["review_trade_plan", "query_price_forecast", "compose_user_reply"], "sequential", "low", False),
    "review_trade_plan": (["ReviewAgent", "UserInteractionAgent"], ["review_trade_plan", "compose_user_reply"], "sequential", "low", False),
    "ask_skill_status": (["SkillManagerAgent", "UserInteractionAgent"], ["manage_agent_skill", "compose_user_reply"], "single_agent", "low", False),
    "manage_agent_skill": (["SkillManagerAgent", "UserInteractionAgent"], ["manage_agent_skill", "compose_user_reply"], "sequential", "high", True),
    "discover_opportunities": (["OpportunityDiscoveryAgent", "RiskControlAgent", "UserInteractionAgent"], ["discover_investment_opportunities", "evaluate_risk_control", "compose_user_reply"], "sequential", "medium", False),
    "regenerate_playbook": (["TradePlaybookAgent", "UserInteractionAgent"], ["generate_trade_playbook", "compose_user_reply"], "sequential", "medium", True),
    "adjust_parameters": (["ParameterAgent", "UserInteractionAgent"], ["draft_parameter_change", "compose_user_reply"], "sequential", "high", True),
}


class TaskManagerAgent:
    """Rule-first task planner for the initial Agent runtime phase."""

    def plan(self, request: UserAgentRequest) -> AgentTaskPlan:
        message = request.message.strip()
        blocked = self._blocked_reason(message)
        if blocked:
            return AgentTaskPlan(
                id=self._new_id(),
                userMessage=message,
                intent="unknown",
                requiredAgents=["UserInteractionAgent"],
                requiredSkills=["compose_user_reply"],
                executionMode="single_agent",
                steps=[AgentTaskStep(agentName="UserInteractionAgent", skillKey="compose_user_reply", task="解释安全边界并拒绝禁止命令。")],
                requiresConfirmation=False,
                riskLevel="critical",
                blockedReason=blocked,
            )

        intent = self._infer_intent(message)
        agents, skills, mode, risk, requires_confirmation = self._route(intent)
        steps = self._build_steps(agents, skills)
        return AgentTaskPlan(
            id=self._new_id(),
            userMessage=message,
            intent=intent,
            requiredAgents=agents,
            requiredSkills=skills,
            executionMode=mode,
            steps=steps,
            requiresConfirmation=requires_confirmation,
            riskLevel=risk,
        )

    def _blocked_reason(self, message: str) -> str | None:
        lowered = message.lower()
        for pattern, reason in FORBIDDEN_PATTERNS:
            if re.search(pattern, lowered, re.IGNORECASE):
                return reason
        return None

    def _infer_intent(self, message: str):
        lowered = message.lower()
        if self._is_agent_trace_question(lowered):
            return "agent_trace_summary"
        if self._is_position_diagnosis(lowered):
            return "position_diagnosis"
        if self._is_no_buy_question(lowered):
            return "buy_decision_explanation"
        if re.search(r"数据.*(正常|更新|状态|缺失)|更新了吗|管道.*(正常|检查|诊断)|diagnos", lowered):
            return "run_data_diagnosis" if re.search(r"检查|诊断|diagnos", lowered) else "ask_data_status"
        if re.search(r"skill|能力|启用|禁用|测试.*skill|技能", lowered):
            return "manage_agent_skill" if re.search(r"启用|禁用|修改|编辑|回滚|测试", lowered) else "ask_skill_status"
        for pattern, intent in SIMPLE_INTENT_PATTERNS:
            if re.search(pattern, lowered):
                return intent
        if message:
            return "general_question"
        return "unknown"

    def _is_no_buy_question(self, lowered_message: str) -> bool:
        return any(re.search(pattern, lowered_message) for pattern in NO_BUY_PATTERNS)

    def _is_position_diagnosis(self, lowered_message: str) -> bool:
        return any(re.search(pattern, lowered_message) for pattern in POSITION_PATTERNS)

    def _is_agent_trace_question(self, lowered_message: str) -> bool:
        return any(re.search(pattern, lowered_message) for pattern in AGENT_TRACE_PATTERNS)

    def _route(self, intent: str):
        return INTENT_AGENT_MAP.get(intent, (["UserInteractionAgent"], ["compose_user_reply"], "single_agent", "low", False))

    def _build_steps(self, agents: list[str], skills: list[str]) -> list[AgentTaskStep]:
        steps: list[AgentTaskStep] = []
        for index, agent in enumerate(agents):
            skill = skills[index] if index < len(skills) else None
            if agent == "UserInteractionAgent":
                task = "汇总前序 Agent 输出，生成普通用户可读答复。"
                depends = [item.agentName for item in steps]
            else:
                task = self._task_text(agent)
                depends = []
            steps.append(AgentTaskStep(agentName=agent, skillKey=skill, task=task, dependsOn=depends))
        return steps

    def _task_text(self, agent: str) -> str:
        return {
            "DataStatusAgent": "检查系统关键数据模块的新鲜度、缺失、失败和可用诊断信息。",
            "ActionabilityAgent": "统计今日/明日操作清单，解释为什么没有立即可买股票，并给出替代行动。",
            "TradePlaybookAgent": "读取现有交易剧本和相关 Agent 视角，解释交易分类、价位、风险和数据证据。",
            "RiskControlAgent": "评估风险阈值、仓位约束和追高风险，给出风控解释。",
            "PriceForecastAgent": "读取预测方向、样本质量和历史表现，解释预测侧是否支持买入。",
            "TechnicalAnalysisAgent": "读取技术买卖点、支撑压力和等待条件，解释是否到达买点。",
            "ReviewAgent": "查询预测/交易计划复盘记录，说明命中、偏差和下一步优化建议。",
            "OpportunityDiscoveryAgent": "扫描最新量化信号和预测，发现非持仓、非置顶的潜力标的，并按置信度入观察或置顶。",
            "SkillManagerAgent": "查询 Skill 注册表状态；涉及修改时只生成待确认计划。",
            "LogAuditAgent": "汇总 Agent、Skill、Pipeline 的最近运行状态和错误。",
            "ParameterAgent": "解释相关参数并生成变更草案，不直接修改生产配置。",
        }.get(agent, "执行用户请求相关的辅助任务。")

    def _new_id(self) -> str:
        return f"agtask_{uuid.uuid4().hex[:16]}"