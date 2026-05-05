import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { sendAgentTaskChat } from '../../../api/agent'
import AgentChatPage from '../AgentChatPage'

vi.mock('../../../api/agent', () => ({
  confirmAgentTask: vi.fn(),
  sendAgentTaskChat: vi.fn(),
}))

function responseFor(message: string) {
  const isSecond = message.includes('哪些')
  return {
    reply: isSecond ? '本次判断主要由交易剧本、风控和技术时机分析参与。' : '今天没有立即买入股票，是因为当前候选股没有同时满足买入信号、风险收益比和风控约束。',
    taskPlan: {
      id: isSecond ? 'agtask_trace' : 'agtask_no_buy',
      intent: isSecond ? 'agent_trace_summary' : 'buy_decision_explanation',
      riskLevel: 'low',
      requiredAgents: ['ActionabilityAgent', 'RiskControlAgent', 'UserInteractionAgent'],
      requiredSkills: ['summarize_actionability', 'evaluate_risk_control', 'compose_user_reply'],
    },
    userFacingAnswer: {
      taskId: isSecond ? 'agtask_trace' : 'agtask_no_buy',
      status: 'partial',
      intent: isSecond ? 'agent_trace_summary' : 'buy_decision_explanation',
      title: isSecond ? '哪些 Agent 参与了当前判断？' : '为什么今天没有立即可买股票？',
      directAnswer: isSecond ? '本次判断主要由交易剧本、风控和技术时机分析参与。' : '今天没有立即买入股票，是因为当前候选股没有同时满足买入信号、风险收益比和风控约束。',
      reasoningSummary: ['检查今日候选股票池。', '校验风险控制。'],
      conclusion: { label: '等待确认，不建议追高', action: 'WATCH', confidence: 'medium', riskLevel: 'medium' },
      keyFindings: { positive: [], negative: ['立即可买 0 只。'], neutral: ['当前交易剧本更偏向等待确认。'] },
      actionPlan: [{ condition: '仍处于接近买点但未确认', action: '继续观察，不追高。', priority: 'high' }],
      riskWarnings: ['当前部分分析依赖降级结果，因此结论置信度为中等。'],
      relatedStocks: [],
      dataQuality: { level: 'cached', warning: '部分 Agent 使用降级摘要，建议结合最新行情复核。' },
      technicalTrace: [
        {
          taskId: isSecond ? 'agtask_trace' : 'agtask_no_buy',
          agentName: 'RiskControlAgent',
          skillKey: 'evaluate_risk_control',
          status: 'degraded',
          userTextStatus: '部分数据不足，已降级分析',
          summary: '不建议追高。',
          usedSkills: ['evaluate_risk_control'],
          usedDataSources: ['trade_playbook_service'],
        },
      ],
    },
    agentResults: [{ agentName: 'RiskControlAgent', status: 'degraded' }],
    skillUsages: [],
    requiresConfirmation: false,
    suggestedActions: [],
    warnings: [],
    disclaimer: '仅供测试。',
  }
}

function clickLastButton(name: RegExp) {
  const buttons = screen.getAllByRole('button', { name })
  fireEvent.click(buttons[buttons.length - 1])
}

function storedTurn(id: string, content: string) {
  const now = new Date().toISOString()
  return {
    id,
    userMessage: { id: `msg_${id}`, content, timestamp: now, context: { currentStockCode: '002594.SZ', page: 'agent-chat' } },
    assistantAnswer: responseFor(content).userFacingAnswer,
    task: { taskId: responseFor(content).userFacingAnswer.taskId, status: 'completed', progressText: '已完成', technicalTrace: [] },
    status: 'completed',
    createdAt: now,
    updatedAt: now,
  }
}

describe('AgentChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    globalThis.localStorage.clear()
    globalThis.window.location.hash = '#agent-chat'
    vi.mocked(sendAgentTaskChat).mockImplementation(async (message: string) => responseFor(message) as any)
  })

  it('keeps conversation history and hides technical trace by default', async () => {
    render(<AgentChatPage selectedStockCode="002594.SZ" />)

    fireEvent.change(screen.getByPlaceholderText('问 Agent：为什么今天没有可以买的股票？'), {
      target: { value: '为什么今天没有可以买的股票？' },
    })
    fireEvent.click(screen.getByRole('button', { name: /发\s*送/ }))

    await waitFor(() => expect(screen.getAllByText('为什么今天没有可以买的股票？').length).toBeGreaterThanOrEqual(1))
    expect(screen.getByText(/今天没有立即买入股票/)).toBeInTheDocument()
    expect(screen.queryByText('RiskControlAgent')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看技术详情' }))
    expect(screen.getByText('RiskControlAgent')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('问 Agent：为什么今天没有可以买的股票？'), {
      target: { value: '哪些 Agent 参与了当前判断？' },
    })
    fireEvent.click(screen.getByRole('button', { name: /发\s*送/ }))

    await waitFor(() => expect(sendAgentTaskChat).toHaveBeenCalledTimes(2))
    expect(screen.getAllByText('为什么今天没有可以买的股票？').length).toBeGreaterThanOrEqual(1)
    await waitFor(() => expect(screen.getAllByText('哪些 Agent 参与了当前判断？').length).toBeGreaterThanOrEqual(1))
  })

  it('deletes a single conversation turn', async () => {
    render(<AgentChatPage selectedStockCode="002594.SZ" />)

    fireEvent.change(screen.getByPlaceholderText('问 Agent：为什么今天没有可以买的股票？'), {
      target: { value: '为什么今天没有可以买的股票？' },
    })
    fireEvent.click(screen.getByRole('button', { name: /发\s*送/ }))
    await waitFor(() => expect(screen.getByText(/今天没有立即买入股票/)).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '删除这条对话' }))
    clickLastButton(/删\s*除/)

    await waitFor(() => expect(screen.queryByText(/今天没有立即买入股票/)).not.toBeInTheDocument())
    expect(screen.getByText('还没有对话。你可以直接询问交易结论、持仓处理或 Agent 判断依据。')).toBeInTheDocument()
  })

  it('clears all conversation turns', async () => {
    globalThis.localStorage.setItem('aistock.agentConversation.agent-chat', JSON.stringify({
      id: 'conv_agent-chat',
      title: 'Agent 智能分析对话',
      turns: [
        storedTurn('turn_one', '为什么今天没有可以买的股票？'),
        storedTurn('turn_two', '哪些 Agent 参与了当前判断？'),
      ],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      schemaVersion: 1,
    }))

    render(<AgentChatPage selectedStockCode="002594.SZ" />)

    expect(screen.getByText(/今天没有立即买入股票/)).toBeInTheDocument()
    expect(screen.getByText(/本次判断主要由交易剧本/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '清空记录' }))
  clickLastButton(/清\s*空/)

    await waitFor(() => expect(screen.queryByText(/今天没有立即买入股票/)).not.toBeInTheDocument())
    expect(screen.queryByText(/本次判断主要由交易剧本/)).not.toBeInTheDocument()
    expect(globalThis.localStorage.getItem('aistock.agentConversation.agent-chat')).toBeNull()
  })
})
