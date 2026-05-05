import type { AgentTaskChatResponse, AgentTraceItem, AgentUserFacingAnswer } from '../../../api/agent'

export function taskIdFrom(response?: AgentTaskChatResponse | null) {
  return String((response?.taskPlan as any)?.id || response?.userFacingAnswer?.taskId || '')
}

export function mapAgentStatusToUserText(status?: string) {
  if (status === 'success') return '已完成'
  if (status === 'degraded') return '部分数据不足，已降级分析'
  if (status === 'failed') return '分析失败'
  if (status === 'running') return '分析中'
  if (status === 'skipped') return '已跳过'
  if (status === 'timeout') return '分析超时'
  return '待处理'
}

export function fallbackAnswer(response: AgentTaskChatResponse, userMessage: string): AgentUserFacingAnswer {
  const taskId = taskIdFrom(response) || `local_${Date.now()}`
  const trace = buildTraceFromLegacy(response, taskId)
  const hasDegraded = trace.some(item => item.status === 'degraded')
  return {
    taskId,
    status: hasDegraded ? 'partial' : 'success',
    intent: String((response.taskPlan as any)?.intent || 'general_question'),
    title: titleFromMessage(userMessage),
    directAnswer: response.reply || '已完成分析。',
    reasoningSummary: ['已读取当前问题和上下文。', '已调用相关 Agent 能力并综合结果。', '技术调用链路已收纳到折叠详情中。'],
    conclusion: {
      label: hasDegraded ? '已完成降级分析' : '已完成分析',
      action: 'NO_ACTION',
      confidence: hasDegraded ? 'medium' : 'high',
      riskLevel: 'medium',
    },
    keyFindings: {
      positive: [],
      negative: [],
      neutral: response.reply ? [response.reply] : [],
    },
    actionPlan: response.suggestedActions?.map(item => ({
      condition: String(item.label || '需要进一步查看'),
      action: String(item.action || item.label || '查看详情'),
      priority: 'medium' as const,
    })) || [],
    riskWarnings: [
      ...(hasDegraded ? ['当前部分分析依赖降级结果，因此结论置信度为中等。'] : []),
      ...(response.warnings || []),
    ],
    relatedStocks: [],
    dataQuality: {
      level: hasDegraded ? 'cached' : 'cached',
      warning: hasDegraded ? '部分 Agent 使用降级摘要，建议结合最新行情复核。' : undefined,
    },
    technicalTrace: trace,
  }
}

function buildTraceFromLegacy(response: AgentTaskChatResponse, taskId: string): AgentTraceItem[] {
  const agentTrace = (response.agentResults || []).map(item => ({
    taskId,
    agentName: String(item.agentName || 'Agent'),
    skillKey: Array.isArray(item.usedSkills) ? String(item.usedSkills[0] || '') || null : null,
    status: String(item.status || 'unknown'),
    userTextStatus: mapAgentStatusToUserText(String(item.status || '')),
    summary: String(item.summary || ''),
    usedSkills: Array.isArray(item.usedSkills) ? item.usedSkills.map(String) : [],
    usedDataSources: Array.isArray(item.usedDataSources) ? item.usedDataSources.map(String) : [],
    error: item.error ? String(item.error) : null,
    degradedReason: item.status === 'degraded' ? String(item.summary || '') : null,
  }))
  const skillTrace = (response.skillUsages || []).map(item => ({
    taskId,
    agentName: String(item.ownerAgent || item.skillKey || 'Skill'),
    skillKey: String(item.skillKey || ''),
    status: String(item.status || 'unknown'),
    userTextStatus: mapAgentStatusToUserText(String(item.status || '')),
    summary: String(item.summary || ''),
    usedSkills: item.skillKey ? [String(item.skillKey)] : [],
    usedDataSources: [],
    error: null,
    degradedReason: null,
  }))
  return [...agentTrace, ...skillTrace]
}

function titleFromMessage(message: string) {
  if (message.includes('没有') && message.includes('买')) return '为什么今天没有立即可买股票？'
  if (message.includes('参与') && message.toLowerCase().includes('agent')) return '哪些 Agent 参与了当前判断？'
  return 'Agent 综合分析'
}
