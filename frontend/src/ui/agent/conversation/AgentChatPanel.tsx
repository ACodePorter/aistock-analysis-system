import React from 'react'
import { Button, Popconfirm, message } from 'antd'
import { ClearOutlined } from '@ant-design/icons'
import { confirmAgentTask, sendAgentTaskChat, type AgentTaskChatContext, type AgentTaskChatResponse } from '../../../api/agent'
import AgentInputBox from './AgentInputBox'
import ConversationHistory from './ConversationHistory'
import { fallbackAnswer, taskIdFrom } from './answerFallback'
import { clearConversation, loadConversation, saveConversation } from './conversationStorage'
import type { ConversationTurn } from './types'

const DEFAULT_QUICK_QUESTIONS = [
  '为什么今天没有可以买的股票？',
  '我350买了天孚通信，现在怎么办？',
  '哪些 Agent 参与了当前判断？',
  '哪只股票最接近买点？',
  '如果我持有当前股票，今天要卖吗？',
]

function currentRoute(fallback: string) {
  return globalThis.window?.location.hash || globalThis.window?.location.pathname || fallback
}

function createTurn(content: string, selectedStockCode?: string | null, page?: string): ConversationTurn {
  const now = new Date().toISOString()
  const id = `turn_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`
  return {
    id,
    userMessage: {
      id: `msg_${id}`,
      content,
      timestamp: now,
      context: { currentStockCode: selectedStockCode, page },
    },
    assistantAnswer: null,
    task: {
      status: 'running',
      progressText: '正在理解问题',
      technicalTrace: [],
    },
    status: 'running',
    createdAt: now,
    updatedAt: now,
  }
}

function answerFromResponse(response: AgentTaskChatResponse, userMessage: string) {
  return response.userFacingAnswer || fallbackAnswer(response, userMessage)
}

export default function AgentChatPanel({
  scope,
  currentPage,
  selectedStockCode,
  selectedMode = 'professional',
  quickQuestions = DEFAULT_QUICK_QUESTIONS,
  onOpenLogs,
}: Readonly<{
  scope: string
  currentPage: string
  selectedStockCode?: string | null
  selectedMode?: 'normal' | 'professional'
  quickQuestions?: string[]
  onOpenLogs?: (taskId?: string) => void
}>) {
  const [input, setInput] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [confirmingTaskId, setConfirmingTaskId] = React.useState<string | null>(null)
  const [turns, setTurns] = React.useState<ConversationTurn[]>(() => loadConversation(scope).turns)

  React.useEffect(() => {
    saveConversation(scope, turns)
  }, [scope, turns])

  const updateTurn = React.useCallback((turnId: string, updater: (turn: ConversationTurn) => ConversationTurn) => {
    setTurns(current => current.map(turn => (turn.id === turnId ? updater(turn) : turn)).slice(-20))
  }, [])

  const deleteTurn = React.useCallback((turnId: string) => {
    setTurns(current => current.filter(turn => turn.id !== turnId))
    message.success('已删除该条对话')
  }, [])

  const clearTurns = React.useCallback(() => {
    clearConversation(scope)
    setTurns([])
    message.success('已清空聊天记录')
  }, [scope])

  const submit = async (messageText?: string) => {
    const finalMessage = (messageText ?? input).trim()
    if (!finalMessage) return
    const turn = createTurn(finalMessage, selectedStockCode, currentPage)
    setTurns(current => [...current, turn].slice(-20))
    setInput('')
    setLoading(true)

    try {
      updateTurn(turn.id, item => ({ ...item, task: { ...item.task, progressText: '正在读取当前股票、策略和风控结果' }, updatedAt: new Date().toISOString() }))
      const context: AgentTaskChatContext = {
        currentPage,
        selectedStockCode,
        selectedMode,
        currentRoute: currentRoute(currentPage),
      }
      const response = await sendAgentTaskChat(finalMessage, context)
      const answer = answerFromResponse(response, finalMessage)
      const taskId = taskIdFrom(response) || answer.taskId
      updateTurn(turn.id, item => ({
        ...item,
        assistantAnswer: answer,
        status: response.requiresConfirmation ? 'pending' : 'completed',
        task: {
          taskId,
          status: response.requiresConfirmation ? 'pending' : 'completed',
          progressText: response.requiresConfirmation ? '等待确认后执行' : '已完成',
          requiresConfirmation: response.requiresConfirmation,
          technicalTrace: answer.technicalTrace || [],
        },
        updatedAt: new Date().toISOString(),
      }))
    } catch (error_: any) {
      updateTurn(turn.id, item => ({
        ...item,
        status: 'failed',
        task: { ...item.task, status: 'failed', progressText: error_?.message || 'Agent 对话失败' },
        updatedAt: new Date().toISOString(),
      }))
      message.error(error_?.message || 'Agent 对话失败')
    } finally {
      setLoading(false)
    }
  }

  const confirmTurn = async (turn: ConversationTurn) => {
    const taskId = turn.task.taskId
    if (!taskId) return
    setConfirmingTaskId(taskId)
    try {
      const response = await confirmAgentTask(taskId, { confirmationText: `确认执行 ${taskId}` })
      const answer = answerFromResponse(response, turn.userMessage.content)
      updateTurn(turn.id, item => ({
        ...item,
        assistantAnswer: answer,
        status: 'completed',
        task: {
          taskId,
          status: 'completed',
          progressText: '已确认并执行',
          requiresConfirmation: false,
          technicalTrace: answer.technicalTrace || [],
        },
        updatedAt: new Date().toISOString(),
      }))
      message.success('已确认并执行')
    } catch (error_: any) {
      message.error(error_?.message || '确认执行失败')
    } finally {
      setConfirmingTaskId(null)
    }
  }

  return (
    <section className="agent-conversation-shell">
      <div className="agent-conversation-header">
        <div>
          <div className="agent-page-eyebrow">AGENT ANALYSIS CHAT</div>
          <h2>智能分析对话</h2>
          <p>默认展示结论、理由、建议和风险；底层调用链路收纳在技术详情中。</p>
        </div>
        <Popconfirm
          title="清空聊天记录？"
          description="该操作会删除当前会话范围内的所有本地聊天记录。"
          okText="清空"
          cancelText="取消"
          onConfirm={clearTurns}
          disabled={!turns.length}
        >
          <Button aria-label="清空记录" icon={<ClearOutlined />} disabled={!turns.length}>清空记录</Button>
        </Popconfirm>
      </div>
      <ConversationHistory turns={turns} confirmingTaskId={confirmingTaskId} onConfirm={confirmTurn} onOpenLogs={onOpenLogs} onDelete={deleteTurn} />
      <AgentInputBox
        value={input}
        loading={loading}
        selectedStockCode={selectedStockCode}
        quickQuestions={quickQuestions}
        onChange={setInput}
        onSubmit={submit}
      />
    </section>
  )
}
