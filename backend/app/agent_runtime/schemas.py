from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


AgentIntent = Literal[
    "ask_no_buy_candidates",
    "buy_decision_explanation",
    "position_diagnosis",
    "agent_trace_summary",
    "ask_data_status",
    "ask_agent_status",
    "ask_stock_decision",
    "ask_trade_playbook",
    "ask_prediction_quality",
    "ask_news_impact",
    "ask_agent_reasoning",
    "ask_agent_logs",
    "ask_skill_status",
    "run_data_diagnosis",
    "regenerate_playbook",
    "adjust_parameters",
    "review_trade_plan",
    "manage_agent_skill",
    "discover_opportunities",
    "general_question",
    "unknown",
]

RiskLevel = Literal["low", "medium", "high", "critical"]
ExecutionMode = Literal["single_agent", "parallel", "sequential"]
RunStatus = Literal["pending", "running", "success", "failed", "skipped", "timeout", "degraded"]
PipelineStatus = Literal["pending", "running", "success", "partial_success", "failed"]
AnswerAction = Literal["BUY", "WATCH", "HOLD", "REDUCE", "SELL", "AVOID", "NO_ACTION"]
AnswerConfidence = Literal["low", "medium", "high"]
AnswerRiskLevel = Literal["low", "medium", "high"]
DataQualityLevel = Literal["realtime", "cached", "mock", "insufficient"]
RelatedStockRole = Literal["current_context", "mentioned", "candidate", "holding"]
ActionPriority = Literal["high", "medium", "low"]


class UserAgentContext(BaseModel):
    currentPage: Optional[str] = None
    selectedStockCode: Optional[str] = None
    selectedDate: Optional[str] = None
    selectedMode: Optional[Literal["normal", "professional"]] = None
    currentRoute: Optional[str] = None


class UserAgentRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    context: Optional[UserAgentContext] = None


class AgentTaskStep(BaseModel):
    agentName: str
    skillKey: Optional[str] = None
    task: str
    dependsOn: list[str] = Field(default_factory=list)


class AgentTaskPlan(BaseModel):
    id: str
    userMessage: str
    intent: AgentIntent
    requiredAgents: list[str]
    requiredSkills: list[str] = Field(default_factory=list)
    executionMode: ExecutionMode = "single_agent"
    steps: list[AgentTaskStep] = Field(default_factory=list)
    requiresConfirmation: bool = False
    riskLevel: RiskLevel = "low"
    blockedReason: Optional[str] = None


class UserFacingAgentReply(BaseModel):
    reply: str
    summary: Optional[str] = None
    dataCards: list[dict[str, Any]] = Field(default_factory=list)
    suggestedActions: list[dict[str, Any]] = Field(default_factory=list)
    requiresUserConfirmation: bool = False
    confirmationText: Optional[str] = None


class AgentCapability(BaseModel):
    agentName: str
    displayName: str
    description: str
    capabilities: list[str]
    inputTypes: list[str] = Field(default_factory=list)
    outputTypes: list[str] = Field(default_factory=list)
    canHandleIntents: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    riskLevel: Literal["low", "medium", "high"] = "low"
    enabled: bool = True
    dependencies: list[str] = Field(default_factory=list)


class AgentSkillDefinition(BaseModel):
    skillKey: str
    skillName: str
    description: str
    ownerAgent: str
    category: str
    enabled: bool = True
    riskLevel: RiskLevel = "low"
    inputSchema: Optional[dict[str, Any]] = None
    outputSchema: Optional[dict[str, Any]] = None
    requiredDataSources: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    timeoutMs: int = 30000
    retryPolicy: dict[str, int] = Field(default_factory=lambda: {"maxRetries": 1, "retryDelayMs": 1000})
    permission: Literal["read_only", "write_draft", "write_confirmed", "admin_only"] = "read_only"
    editable: bool = True
    requiresConfirmation: bool = False
    version: str = "1.0.0"
    createdAt: str
    updatedAt: str
    updatedBy: Optional[str] = None
    plainExplanation: str


class AgentExecutionResult(BaseModel):
    agentName: str
    status: RunStatus
    summary: str
    output: dict[str, Any] = Field(default_factory=dict)
    usedSkills: list[str] = Field(default_factory=list)
    usedDataSources: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class AgentSkillUsageSummary(BaseModel):
    skillKey: str
    status: str
    summary: str


class AgentTraceItem(BaseModel):
    taskId: Optional[str] = None
    agentName: str
    skillKey: Optional[str] = None
    status: str
    userTextStatus: str
    summary: str
    usedSkills: list[str] = Field(default_factory=list)
    usedDataSources: list[str] = Field(default_factory=list)
    durationMs: Optional[int] = None
    error: Optional[str] = None
    degradedReason: Optional[str] = None


class AgentConclusion(BaseModel):
    label: str
    action: AnswerAction = "NO_ACTION"
    confidence: AnswerConfidence = "medium"
    riskLevel: AnswerRiskLevel = "medium"


class AgentKeyFindings(BaseModel):
    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)
    neutral: list[str] = Field(default_factory=list)


class AgentActionItem(BaseModel):
    condition: str
    action: str
    priority: ActionPriority = "medium"


class RelatedStock(BaseModel):
    code: str
    name: str
    role: RelatedStockRole = "mentioned"


class AgentDataQuality(BaseModel):
    level: DataQualityLevel = "cached"
    warning: Optional[str] = None


class AgentUserFacingAnswer(BaseModel):
    taskId: str
    status: Literal["success", "partial", "failed"] = "success"
    intent: str
    title: str
    directAnswer: str
    reasoningSummary: list[str] = Field(default_factory=list)
    conclusion: AgentConclusion
    keyFindings: AgentKeyFindings = Field(default_factory=AgentKeyFindings)
    actionPlan: list[AgentActionItem] = Field(default_factory=list)
    riskWarnings: list[str] = Field(default_factory=list)
    relatedStocks: list[RelatedStock] = Field(default_factory=list)
    dataQuality: AgentDataQuality = Field(default_factory=AgentDataQuality)
    technicalTrace: list[AgentTraceItem] = Field(default_factory=list)


class AgentTaskChatResponse(BaseModel):
    reply: str
    taskPlan: Optional[AgentTaskPlan] = None
    pipelineRunId: Optional[str] = None
    userFacingAnswer: Optional[AgentUserFacingAnswer] = None
    agentResults: list[AgentExecutionResult] = Field(default_factory=list)
    skillUsages: list[AgentSkillUsageSummary] = Field(default_factory=list)
    requiresConfirmation: bool = False
    confirmationPayload: Optional[dict[str, Any]] = None
    suggestedActions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = "本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。"


class AgentStatusSnapshot(BaseModel):
    agentName: str
    displayName: str
    status: Literal["idle", "running", "healthy", "degraded", "failed", "disabled"]
    lastRunAt: Optional[str] = None
    lastSuccessAt: Optional[str] = None
    lastFailureAt: Optional[str] = None
    successRate24h: Optional[float] = None
    successRate7d: Optional[float] = None
    avgDurationMs: Optional[int] = None
    recentError: Optional[str] = None
    enabledSkills: int = 0
    disabledSkills: int = 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()