import { apiFetch } from './client'

export type AgentRiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type AgentCapabilityRiskLevel = 'low' | 'medium' | 'high'
export type AgentRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'timeout' | 'degraded'
export type AgentAnswerConfidence = 'low' | 'medium' | 'high'

export interface AgentCapability {
  agentName: string
  displayName: string
  description: string
  capabilities: string[]
  inputTypes: string[]
  outputTypes: string[]
  canHandleIntents: string[]
  skills: string[]
  riskLevel: AgentCapabilityRiskLevel
  enabled: boolean
  dependencies: string[]
}

export interface AgentSkillDefinition {
  skillKey: string
  skillName: string
  description: string
  ownerAgent: string
  category: string
  enabled: boolean
  riskLevel: AgentRiskLevel
  inputSchema?: Record<string, any> | null
  outputSchema?: Record<string, any> | null
  requiredDataSources: string[]
  dependencies: string[]
  timeoutMs: number
  retryPolicy: Record<string, number>
  permission: 'read_only' | 'write_draft' | 'write_confirmed' | 'admin_only'
  editable: boolean
  requiresConfirmation: boolean
  version: string
  createdAt: string
  updatedAt: string
  updatedBy?: string | null
  plainExplanation: string
}

export interface AgentStatusSnapshot {
  agentName: string
  displayName: string
  status: 'idle' | 'running' | 'healthy' | 'degraded' | 'failed' | 'disabled'
  lastRunAt?: string | null
  lastSuccessAt?: string | null
  lastFailureAt?: string | null
  successRate24h?: number | null
  successRate7d?: number | null
  avgDurationMs?: number | null
  recentError?: string | null
  enabledSkills: number
  disabledSkills: number
}

export interface AgentLogsOverview {
  overallStatus: string
  summary: string
  agentRunTotal: number
  skillUsageTotal: number
  agentPipelineRunTotal?: number
  agentFailed24h: number
  skillFailed24h: number
  agentPipelineFailed24h?: number
  pipelineFailed24h: number
}

export interface AgentRunLog {
  runId: string
  taskId: string
  pipelineRunId?: string | null
  agentName: string
  status: AgentRunStatus
  inputSummary: string
  outputSummary?: string | null
  startedAt?: string | null
  finishedAt?: string | null
  durationMs?: number | null
  error?: string | null
  usedDataSources: string[]
  usedSkills: string[]
  output: Record<string, any>
}

export interface AgentSkillUsageLog {
  usageId: string
  skillKey: string
  skillName: string
  ownerAgent: string
  taskId?: string | null
  pipelineRunId?: string | null
  agentRunId?: string | null
  status: string
  startedAt?: string | null
  finishedAt?: string | null
  durationMs?: number | null
  inputSummary?: string | null
  outputSummary?: string | null
  error?: string | null
  triggeredBy: string
  dataSourcesUsed: string[]
}

export interface AgentTaskDetail {
  taskId: string
  userMessage: string
  intent: string
  riskLevel: AgentRiskLevel
  status: string
  requiresConfirmation: boolean
  plan: Record<string, any>
  finalSummary?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  finishedAt?: string | null
}

export interface AgentTaskRunsResponse {
  taskId: string
  agentRuns: AgentRunLog[]
  skillUsages: AgentSkillUsageLog[]
}

export interface AgentTraceItem {
  taskId?: string | null
  agentName: string
  skillKey?: string | null
  status: string
  userTextStatus: string
  summary: string
  usedSkills: string[]
  usedDataSources: string[]
  durationMs?: number | null
  error?: string | null
  degradedReason?: string | null
}

export interface AgentConclusion {
  label: string
  action: 'BUY' | 'WATCH' | 'HOLD' | 'REDUCE' | 'SELL' | 'AVOID' | 'NO_ACTION'
  confidence: AgentAnswerConfidence
  riskLevel: AgentCapabilityRiskLevel
}

export interface AgentKeyFindings {
  positive: string[]
  negative: string[]
  neutral: string[]
}

export interface AgentActionItem {
  condition: string
  action: string
  priority: 'high' | 'medium' | 'low'
}

export interface RelatedStock {
  code: string
  name: string
  role: 'current_context' | 'mentioned' | 'candidate' | 'holding'
}

export interface AgentDataQuality {
  level: 'realtime' | 'cached' | 'mock' | 'insufficient'
  warning?: string | null
}

export interface AgentUserFacingAnswer {
  taskId: string
  status: 'success' | 'partial' | 'failed'
  intent: string
  title: string
  directAnswer: string
  reasoningSummary: string[]
  conclusion: AgentConclusion
  keyFindings: AgentKeyFindings
  actionPlan: AgentActionItem[]
  riskWarnings: string[]
  relatedStocks: RelatedStock[]
  dataQuality: AgentDataQuality
  technicalTrace: AgentTraceItem[]
}

export interface AgentTaskChatResponse {
  reply: string
  taskPlan?: Record<string, any> | null
  pipelineRunId?: string | null
  userFacingAnswer?: AgentUserFacingAnswer | null
  agentResults: Array<Record<string, any>>
  skillUsages: Array<Record<string, any>>
  requiresConfirmation: boolean
  confirmationPayload?: Record<string, any> | null
  suggestedActions: Array<Record<string, any>>
  warnings: string[]
  disclaimer: string
}

export interface AgentTaskChatContext {
  currentPage?: string
  selectedStockCode?: string | null
  selectedDate?: string | null
  selectedMode?: 'normal' | 'professional'
  currentRoute?: string
}

export interface AgentFailedRerunItem {
  taskId: string
  status: string
  reply?: string
  requiresConfirmation?: boolean
  error?: string
}

export interface AgentPipelineDefinition {
  pipelineType: string
  label: string
}

export interface AgentPipelineStep {
  taskId?: string | null
  intent?: string | null
  riskLevel?: AgentRiskLevel | null
  requiresConfirmation: boolean
  reply: string
  agentResults: Array<Record<string, any>>
  skillUsages: Array<Record<string, any>>
}

export interface AgentPipelineRunLog {
  pipelineRunId: string
  pipelineType: string
  status: 'pending' | 'running' | 'success' | 'partial_success' | 'failed'
  triggeredBy: string
  userRequest?: string | null
  startedAt?: string | null
  finishedAt?: string | null
  durationMs?: number | null
  finalSummary?: string | null
  warnings: string[]
  payload: Record<string, any>
}

export interface AgentPipelineRunDetail extends AgentPipelineRunLog {
  agentRuns: AgentRunLog[]
  skillUsages: AgentSkillUsageLog[]
}

export interface AgentPipelineRunResponse {
  pipelineRunId: string
  pipelineType: string
  status: AgentPipelineRunLog['status']
  summary: string
  warnings: string[]
  durationMs: number
  steps: AgentPipelineStep[]
}

export interface AgentSkillUpdatePayload {
  description?: string
  enabled?: boolean
  riskLevel?: string
  timeoutMs?: number
  retryPolicy?: Record<string, number>
  requiredDataSources?: string[]
  dependencies?: string[]
  permission?: string
  requiresConfirmation?: boolean
  plainExplanation?: string
  reason?: string
  actor?: string
}

export interface AgentSkillVersionLog {
  versionId: string
  skillKey: string
  version: string
  createdAt?: string | null
  createdBy: string
  changeSummary: string
  before?: Record<string, any> | null
  after: Record<string, any>
  auditLogId?: string | null
}

export interface AgentSkillAuditLog {
  auditLogId: string
  timestamp?: string | null
  actor: string
  action: string
  skillKey: string
  before?: Record<string, any> | null
  after?: Record<string, any> | null
  reason?: string | null
  result: string
  riskLevel: string
}

export interface AgentSkillTestRunResponse {
  skillKey: string
  skillName: string
  status: string
  reply: string
  requiresConfirmation: boolean
  taskPlan?: Record<string, any> | null
  warnings: string[]
}

export interface AgentSkillExportPayload {
  skill: AgentSkillDefinition
  versions: AgentSkillVersionLog[]
  auditLogs: AgentSkillAuditLog[]
}

function withQuery(path: string, params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  })
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

export function fetchAgentCapabilities() {
  return apiFetch<{ items: AgentCapability[] }>('/api/agent/capabilities')
}

export function fetchAgentSkills(filters: {
  ownerAgent?: string
  category?: string
  riskLevel?: string
  enabled?: boolean | null
} = {}) {
  return apiFetch<{ items: AgentSkillDefinition[]; count: number }>(withQuery('/api/agent/skills', filters))
}

export function fetchAgentSkill(skillKey: string) {
  return apiFetch<AgentSkillDefinition>(`/api/agent/skills/${encodeURIComponent(skillKey)}`)
}

export function updateAgentSkill(skillKey: string, payload: AgentSkillUpdatePayload) {
  return apiFetch<AgentSkillDefinition>(`/api/agent/skills/${encodeURIComponent(skillKey)}`, {
    method: 'PATCH',
    json: payload,
  })
}

export function enableAgentSkill(skillKey: string, reason?: string) {
  return apiFetch<AgentSkillDefinition>(`/api/agent/skills/${encodeURIComponent(skillKey)}/enable`, {
    method: 'POST',
    json: { reason },
  })
}

export function disableAgentSkill(skillKey: string, reason?: string) {
  return apiFetch<AgentSkillDefinition>(`/api/agent/skills/${encodeURIComponent(skillKey)}/disable`, {
    method: 'POST',
    json: { reason },
  })
}

export function testAgentSkill(skillKey: string, message?: string) {
  return apiFetch<AgentSkillTestRunResponse>(`/api/agent/skills/${encodeURIComponent(skillKey)}/test-run`, {
    method: 'POST',
    json: { message },
  })
}

export function fetchAgentSkillVersions(skillKey: string, limit = 50) {
  return apiFetch<{ items: AgentSkillVersionLog[]; count: number }>(`/api/agent/skills/${encodeURIComponent(skillKey)}/versions?limit=${limit}`)
}

export function fetchAgentSkillAuditLogs(skillKey: string, limit = 50) {
  return apiFetch<{ items: AgentSkillAuditLog[]; count: number }>(`/api/agent/skills/${encodeURIComponent(skillKey)}/audit-logs?limit=${limit}`)
}

export function rollbackAgentSkill(skillKey: string, versionId: string, reason?: string) {
  return apiFetch<AgentSkillDefinition>(`/api/agent/skills/${encodeURIComponent(skillKey)}/rollback`, {
    method: 'POST',
    json: { versionId, reason },
  })
}

export function exportAgentSkill(skillKey: string) {
  return apiFetch<AgentSkillExportPayload>(`/api/agent/skills/${encodeURIComponent(skillKey)}/export`)
}

export function fetchAgentStatus() {
  return apiFetch<{ items: AgentStatusSnapshot[]; count: number }>('/api/agent/status')
}

export function fetchAgentLogsOverview() {
  return apiFetch<AgentLogsOverview>('/api/agent/logs/overview')
}

export function fetchAgentPipelines() {
  return apiFetch<{ items: AgentPipelineDefinition[]; count: number }>('/api/agent/pipelines')
}

export function runAgentPipeline(pipelineType: string, payload: { message?: string; triggeredBy?: string; context?: Record<string, any> } = {}) {
  return apiFetch<AgentPipelineRunResponse>(`/api/agent/pipelines/${encodeURIComponent(pipelineType)}/run`, {
    method: 'POST',
    json: payload,
  })
}

export function fetchAgentPipelineRuns(filters: { pipelineType?: string; status?: string; limit?: number } = {}) {
  return apiFetch<{ items: AgentPipelineRunLog[]; count: number }>(withQuery('/api/agent/pipelines/runs', filters))
}

export function fetchAgentPipelineRun(pipelineRunId: string) {
  return apiFetch<AgentPipelineRunDetail>(`/api/agent/pipelines/runs/${encodeURIComponent(pipelineRunId)}`)
}

export function fetchAgentRuns(filters: {
  agentName?: string
  status?: string
  taskId?: string
  limit?: number
} = {}) {
  return apiFetch<{ items: AgentRunLog[]; count: number }>(withQuery('/api/agent/logs/agent-runs', filters))
}

export function fetchSkillUsages(filters: {
  skillKey?: string
  ownerAgent?: string
  status?: string
  taskId?: string
  limit?: number
} = {}) {
  return apiFetch<{ items: AgentSkillUsageLog[]; count: number }>(withQuery('/api/agent/logs/skill-usages', filters))
}

export function fetchSkillAuditLogs(filters: { skillKey?: string; limit?: number } = {}) {
  return apiFetch<{ items: AgentSkillAuditLog[]; count: number }>(withQuery('/api/agent/logs/skill-audit', filters))
}

export function fetchAgentTask(taskId: string) {
  return apiFetch<AgentTaskDetail>(`/api/agent/tasks/${encodeURIComponent(taskId)}`)
}

export function fetchAgentTaskRuns(taskId: string) {
  return apiFetch<AgentTaskRunsResponse>(`/api/agent/tasks/${encodeURIComponent(taskId)}/runs`)
}

export function confirmAgentTask(taskId: string, payload: { confirmationText?: string; actor?: string; pipelineRunId?: string | null } = {}) {
  return apiFetch<AgentTaskChatResponse>(`/api/agent/tasks/${encodeURIComponent(taskId)}/confirm`, {
    method: 'POST',
    json: { confirmed: true, ...payload },
  })
}

export function rerunAgentTask(taskId: string, payload: { confirmed?: boolean; confirmationText?: string; actor?: string; pipelineRunId?: string | null } = {}) {
  return apiFetch<AgentTaskChatResponse>(`/api/agent/tasks/${encodeURIComponent(taskId)}/rerun`, {
    method: 'POST',
    json: payload,
  })
}

export function rerunFailedAgentTasks(payload: { limit?: number; confirmed?: boolean; confirmationText?: string; actor?: string } = {}) {
  return apiFetch<{ items: AgentFailedRerunItem[]; count: number }>('/api/agent/logs/rerun-failed', {
    method: 'POST',
    json: payload,
  })
}

export function sendAgentTaskChat(message: string, context?: AgentTaskChatContext) {
  return apiFetch<AgentTaskChatResponse>('/api/agent/task-chat', {
    method: 'POST',
    json: { message, context },
  })
}