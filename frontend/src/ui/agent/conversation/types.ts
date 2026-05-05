import type { AgentTraceItem, AgentUserFacingAnswer } from '../../../api/agent'

export type ConversationStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface AgentUserMessage {
  id: string
  content: string
  timestamp: string
  context?: {
    currentStockCode?: string | null
    currentStockName?: string | null
    page?: string
  }
}

export interface ConversationTurnTask {
  taskId?: string
  status: ConversationStatus
  progressText?: string
  requiresConfirmation?: boolean
  technicalTrace: AgentTraceItem[]
}

export interface ConversationTurn {
  id: string
  userMessage: AgentUserMessage
  assistantAnswer: AgentUserFacingAnswer | null
  task: ConversationTurnTask
  status: ConversationStatus
  createdAt: string
  updatedAt: string
}

export interface AgentConversation {
  id: string
  title?: string
  turns: ConversationTurn[]
  createdAt: string
  updatedAt: string
  schemaVersion: 1
}
