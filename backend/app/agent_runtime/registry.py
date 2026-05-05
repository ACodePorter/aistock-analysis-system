from __future__ import annotations

from functools import lru_cache

from .schemas import AgentCapability, AgentSkillDefinition, utc_now_iso


def _skill(
    key: str,
    name: str,
    owner: str,
    category: str,
    description: str,
    *,
    risk: str = "low",
    permission: str = "read_only",
    requires_confirmation: bool = False,
    data_sources: list[str] | None = None,
) -> dict:
    now = utc_now_iso()
    return {
        "skillKey": key,
        "skillName": name,
        "description": description,
        "ownerAgent": owner,
        "category": category,
        "enabled": True,
        "riskLevel": risk,
        "inputSchema": None,
        "outputSchema": None,
        "requiredDataSources": data_sources or [],
        "dependencies": [],
        "timeoutMs": 30000,
        "retryPolicy": {"maxRetries": 1, "retryDelayMs": 1000},
        "permission": permission,
        "editable": True,
        "requiresConfirmation": requires_confirmation,
        "version": "1.0.0",
        "createdAt": now,
        "updatedAt": now,
        "plainExplanation": description,
    }


DEFAULT_SKILLS: list[dict] = [
    _skill("summarize_actionability", "统计可操作交易机会", "ActionabilityAgent", "trade_actionability", "统计立即可买、接近买点、突破确认、卖出减仓和规避数量，并解释没有可买股票的原因。", data_sources=["trade_playbook_service", "user_positions"]),
    _skill("check_data_freshness", "检查数据新鲜度", "DataStatusAgent", "data_quality", "检查行情、预测、资金流、报告和 pipeline 最近更新时间。", data_sources=["postgresql"]),
    _skill("query_market_snapshot", "查询行情快照", "MarketDataAgent", "data_collection", "查询价格、成交量、涨跌幅与停牌/缺失状态。", data_sources=["prices_daily", "akshare/tushare"]),
    _skill("analyze_technical_timing", "分析技术买卖点", "TechnicalAnalysisAgent", "technical_analysis", "读取技术信号、均线和量价关系，生成支撑/压力与买卖点依据。", data_sources=["qe_signals", "prices_daily"]),
    _skill("analyze_news_sentiment", "分析新闻情绪", "NewsSentimentAgent", "news_analysis", "分析个股、行业和政策新闻对交易剧本的影响。", data_sources=["mongodb", "news_articles"]),
    _skill("analyze_macro_policy", "分析宏观政策", "MacroPolicyAgent", "macro_analysis", "汇总宏观主题、政策与市场广度对策略的影响。", data_sources=["macro_observations"]),
    _skill("analyze_company_fundamental", "分析企业实力", "CompanyFundamentalAgent", "fundamental_analysis", "读取公司画像和财务指标，给出基本面质量摘要。", data_sources=["stock_profiles", "financial_metrics"]),
    _skill("analyze_capital_flow", "分析资金流", "CapitalFlowAgent", "capital_flow", "分析主力净流入、净占比和资金行为证据。", data_sources=["fundflow_daily"]),
    _skill("query_price_forecast", "查询价格预测", "PriceForecastAgent", "forecast", "读取短线预测方向、区间和历史准确率。", data_sources=["qe_predictions", "forecasts"]),
    _skill("evaluate_risk_control", "评估风险控制", "RiskControlAgent", "risk_control", "结合风险评分、波动、样本质量、用户持仓成本和负面因素给出仓位与否决条件。", data_sources=["trade_playbook_service", "user_positions"]),
    _skill("generate_trade_playbook", "生成交易剧本", "TradePlaybookAgent", "trade_playbook", "汇总现有交易剧本服务，解释能否买、价位、止损、目标、持仓成本和场景计划。", data_sources=["trade_playbook_service", "user_positions"]),
    _skill("discover_investment_opportunities", "发现潜力股票", "OpportunityDiscoveryAgent", "opportunity_discovery", "扫描量化信号、预测和风险分，发现非持仓非置顶标的；高置信候选自动加入置顶，低置信候选等待确认。", risk="medium", permission="write_confirmed", data_sources=["qe_signals", "qe_predictions", "stock_pool_members", "watchlist", "user_positions"]),
    _skill("review_trade_plan", "复盘交易计划", "ReviewAgent", "review", "复盘买点、目标价、止损与模型预测命中情况。", data_sources=["prediction_evaluations", "agent_review_runs"]),
    _skill("draft_parameter_change", "生成参数变更草案", "ParameterAgent", "parameter_management", "解释参数并生成草案，不直接修改生产参数。", risk="high", permission="write_draft", requires_confirmation=True),
    _skill("manage_agent_skill", "管理 Agent Skill", "SkillManagerAgent", "system_diagnosis", "查看、测试、启用或禁用 Skill，并写入审计。", risk="high", permission="write_confirmed", requires_confirmation=True),
    _skill("query_agent_logs", "查询 Agent 日志", "LogAuditAgent", "system_diagnosis", "查询 AgentRun、PipelineRun、SkillUsage 和错误摘要。"),
    _skill("compose_user_reply", "生成用户答复", "UserInteractionAgent", "user_interaction", "把专业 Agent 输出转换成普通用户可读回复。"),
]


DEFAULT_CAPABILITIES: list[dict] = [
    {
        "agentName": "TaskManagerAgent",
        "displayName": "任务管家 Agent",
        "description": "识别用户意图、拆解任务、选择 Agent 和 Skill，并执行安全分级。",
        "capabilities": ["意图识别", "任务拆解", "风险分级", "调度规划"],
        "canHandleIntents": ["*"],
        "skills": [],
        "riskLevel": "medium",
        "enabled": True,
    },
    {
        "agentName": "DataStatusAgent",
        "displayName": "数据状态 Agent",
        "description": "检查行情、新闻、预测、复盘、参数和 pipeline 数据是否正常。",
        "capabilities": ["检查数据更新", "发现数据缺失", "解释数据状态"],
        "canHandleIntents": ["ask_data_status", "run_data_diagnosis", "ask_no_buy_candidates", "buy_decision_explanation", "position_diagnosis", "agent_trace_summary"],
        "skills": ["check_data_freshness"],
        "riskLevel": "low",
        "enabled": True,
    },
    {
        "agentName": "ActionabilityAgent",
        "displayName": "可操作性 Agent",
        "description": "统计当前交易剧本中可立即执行、接近买点、等待突破、卖出减仓和规避的股票数量。",
        "capabilities": ["统计操作清单", "解释无可买原因", "输出下一步行动"],
        "canHandleIntents": ["ask_no_buy_candidates", "buy_decision_explanation"],
        "skills": ["summarize_actionability"],
        "riskLevel": "low",
        "enabled": True,
    },
    {
        "agentName": "TradePlaybookAgent",
        "displayName": "交易剧本 Agent",
        "description": "调用现有交易剧本服务，输出普通用户可理解的计划和风险提示。",
        "capabilities": ["生成交易剧本", "解释交易分类", "生成明日操作清单"],
        "canHandleIntents": ["ask_no_buy_candidates", "buy_decision_explanation", "position_diagnosis", "agent_trace_summary", "ask_stock_decision", "ask_trade_playbook", "regenerate_playbook"],
        "skills": ["generate_trade_playbook"],
        "riskLevel": "medium",
        "enabled": True,
    },
    {
        "agentName": "RiskControlAgent",
        "displayName": "风控 Agent",
        "description": "评估交易剧本中的风险等级、仓位约束和追高风险。",
        "capabilities": ["风险阈值解释", "仓位约束", "风险否决"],
        "canHandleIntents": ["ask_no_buy_candidates", "buy_decision_explanation", "position_diagnosis", "agent_trace_summary", "ask_stock_decision", "ask_trade_playbook", "ask_agent_reasoning"],
        "skills": ["evaluate_risk_control"],
        "riskLevel": "medium",
        "enabled": True,
    },
    {
        "agentName": "TechnicalAnalysisAgent",
        "displayName": "技术分析 Agent",
        "description": "解释技术买点、突破确认、支撑压力和等待条件。",
        "capabilities": ["技术买点", "突破确认", "支撑压力"],
        "canHandleIntents": ["ask_no_buy_candidates", "buy_decision_explanation", "position_diagnosis", "agent_trace_summary", "ask_stock_decision", "ask_trade_playbook", "ask_agent_reasoning"],
        "skills": ["analyze_technical_timing"],
        "riskLevel": "medium",
        "enabled": True,
    },
    {
        "agentName": "PriceForecastAgent",
        "displayName": "价格预测 Agent",
        "description": "解释预测方向、置信度、历史样本质量和目标区间。",
        "capabilities": ["价格预测", "模型表现", "预测置信度"],
        "canHandleIntents": ["ask_no_buy_candidates", "buy_decision_explanation", "position_diagnosis", "agent_trace_summary", "ask_prediction_quality", "ask_agent_reasoning"],
        "skills": ["query_price_forecast"],
        "riskLevel": "medium",
        "enabled": True,
    },
    {
        "agentName": "ReviewAgent",
        "displayName": "复盘 Agent",
        "description": "复盘历史预测、交易计划和模型门禁。",
        "capabilities": ["复盘计划", "分析失败原因", "输出优化建议"],
        "canHandleIntents": ["ask_prediction_quality", "review_trade_plan"],
        "skills": ["review_trade_plan"],
        "riskLevel": "low",
        "enabled": True,
    },
    {
        "agentName": "OpportunityDiscoveryAgent",
        "displayName": "潜力股发现 Agent",
        "description": "扫描全市场候选信号，发现非持仓、非置顶的潜力股票，并按置信度生成候选或自动置顶。",
        "capabilities": ["发现潜力股", "候选打分", "高置信自动置顶", "低置信待确认"],
        "canHandleIntents": ["discover_opportunities", "ask_no_buy_candidates", "buy_decision_explanation"],
        "skills": ["discover_investment_opportunities"],
        "riskLevel": "medium",
        "enabled": True,
    },
    {
        "agentName": "ParameterAgent",
        "displayName": "参数管理 Agent",
        "description": "解释系统参数并生成参数调整草案，不直接静默修改参数。",
        "capabilities": ["参数解释", "变更草案", "影响分析"],
        "canHandleIntents": ["adjust_parameters"],
        "skills": ["draft_parameter_change"],
        "riskLevel": "high",
        "enabled": True,
    },
    {
        "agentName": "SkillManagerAgent",
        "displayName": "Skill 管理 Agent",
        "description": "管理 Skill 注册表、启停、测试、版本和审计。",
        "capabilities": ["Skill 查询", "Skill 变更", "Skill 测试", "审计"],
        "canHandleIntents": ["ask_skill_status", "manage_agent_skill"],
        "skills": ["manage_agent_skill"],
        "riskLevel": "high",
        "enabled": True,
    },
    {
        "agentName": "LogAuditAgent",
        "displayName": "日志与审计 Agent",
        "description": "查询运行历史、错误、Skill 使用和 Agent 健康状态。",
        "capabilities": ["日志查询", "健康摘要", "失败定位"],
        "canHandleIntents": ["ask_agent_logs", "ask_agent_reasoning"],
        "skills": ["query_agent_logs"],
        "riskLevel": "low",
        "enabled": True,
    },
    {
        "agentName": "UserInteractionAgent",
        "displayName": "用户交互 Agent",
        "description": "负责表达、总结、确认和普通用户解释。",
        "capabilities": ["自然语言总结", "确认提示", "风险免责声明"],
        "canHandleIntents": ["*"],
        "skills": ["compose_user_reply"],
        "riskLevel": "low",
        "enabled": True,
    },
]


@lru_cache(maxsize=1)
def list_default_skills() -> tuple[AgentSkillDefinition, ...]:
    return tuple(AgentSkillDefinition.model_validate(item) for item in DEFAULT_SKILLS)


@lru_cache(maxsize=1)
def list_default_capabilities() -> tuple[AgentCapability, ...]:
    return tuple(AgentCapability.model_validate(item) for item in DEFAULT_CAPABILITIES)


def get_skill(skill_key: str) -> AgentSkillDefinition | None:
    normalized = skill_key.strip()
    for item in list_default_skills():
        if item.skillKey == normalized:
            return item
    return None


def get_capability(agent_name: str) -> AgentCapability | None:
    normalized = agent_name.strip()
    for item in list_default_capabilities():
        if item.agentName == normalized:
            return item
    return None