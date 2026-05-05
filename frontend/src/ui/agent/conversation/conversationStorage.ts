import type { AgentConversation, ConversationTurn } from './types'

const MAX_TURNS = 20

export function conversationStorageKey(scope: string) {
  return `aistock.agentConversation.${scope}`
}

export function createEmptyConversation(scope: string): AgentConversation {
  const now = new Date().toISOString()
  return {
    id: `conv_${scope}`,
    title: 'Agent 智能分析对话',
    turns: [],
    createdAt: now,
    updatedAt: now,
    schemaVersion: 1,
  }
}

export function loadConversation(scope: string): AgentConversation {
  const fallback = createEmptyConversation(scope)
  try {
    const raw = globalThis.localStorage?.getItem(conversationStorageKey(scope))
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as AgentConversation
    if (parsed?.schemaVersion !== 1 || !Array.isArray(parsed.turns)) return fallback
    return { ...parsed, turns: parsed.turns.slice(-MAX_TURNS) }
  } catch {
    return fallback
  }
}

export function saveConversation(scope: string, turns: ConversationTurn[]) {
  try {
    if (turns.length === 0) {
      globalThis.localStorage?.removeItem(conversationStorageKey(scope))
      return
    }
    const now = new Date().toISOString()
    const conversation: AgentConversation = {
      id: `conv_${scope}`,
      title: 'Agent 智能分析对话',
      turns: turns.slice(-MAX_TURNS),
      createdAt: turns[0]?.createdAt || now,
      updatedAt: now,
      schemaVersion: 1,
    }
    globalThis.localStorage?.setItem(conversationStorageKey(scope), JSON.stringify(conversation))
  } catch {
    // localStorage may be unavailable in privacy mode; the in-memory conversation still works.
  }
}

export function clearConversation(scope: string) {
  try {
    globalThis.localStorage?.removeItem(conversationStorageKey(scope))
  } catch {
    // localStorage may be unavailable in privacy mode; the in-memory conversation still works.
  }
}
