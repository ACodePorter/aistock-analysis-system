import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import RetailTradeDecisionCard from '../RetailTradeDecisionCard'
import { fetchRetailDecision } from '../../../api/retailDecision'

vi.mock('../../../api/retailDecision', () => ({
  fetchRetailDecision: vi.fn(),
}))

const mockedFetchRetailDecision = vi.mocked(fetchRetailDecision)

const response = {
  symbol: '002460.SZ',
  generatedAt: '2026-04-26T00:00:00Z',
  card: {
    stockCode: '002460.SZ',
    stockName: '测试股份',
    finalAction: 'can_buy',
    finalActionLabel: '可以小仓试买',
    plainConclusion: '测试股份短线条件较完整，可以按计划小仓试买，但必须预先设好止损。',
    oneSentenceReason: '模型上涨概率 62.0%',
    currentPrice: 10,
    latestPriceDate: '2026-04-24',
    suggestedBuyRange: { min: 9.8, max: 10.1, label: '9.80 - 10.10' },
    lowAbsorbPrice: 9.8,
    doNotChaseAbove: 10.25,
    stopLossPrice: 9.35,
    takeProfitPrice1: 10.8,
    takeProfitPrice2: 11.2,
    suggestedPositionPct: { min: 0.08, max: 0.18, label: '8% - 18%' },
    applicableHorizon: '1-5个交易日',
    confidence: 0.66,
    confidenceLabel: '中等',
    riskLevel: 'medium',
    riskLabel: '中等',
    riskScore: 38,
    invalidationCondition: '跌破止损价，本次短线计划失效。',
    dataWarnings: [],
    disclaimer: '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。',
  },
  agentViews: {
    companyFundamental: { title: '公司本身', stance: 'support', points: ['公司业务稳定。'] },
    riskControl: { title: '风险控制', stance: 'high', points: ['需要严格止损。'] },
  },
  professionalDetails: {},
  disclaimer: '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。',
} as const

describe('RetailTradeDecisionCard', () => {
  beforeEach(() => {
    mockedFetchRetailDecision.mockReset()
  })

  it('renders nothing without a symbol', () => {
    const { container } = render(<RetailTradeDecisionCard />)
    expect(container.firstChild).toBeNull()
    expect(mockedFetchRetailDecision).not.toHaveBeenCalled()
  })

  it('renders the retail decision card and translated stance labels', async () => {
    mockedFetchRetailDecision.mockResolvedValue(response as any)

    render(<RetailTradeDecisionCard symbol="002460.SZ" />)

    expect(await screen.findByText(response.card.plainConclusion)).toBeInTheDocument()
    expect(screen.getByText('可以小仓试买')).toBeInTheDocument()
    expect(screen.getByText('9.80 - 10.10')).toBeInTheDocument()
    expect(screen.getByText('偏支持')).toBeInTheDocument()
    expect(screen.getByText('风险偏高')).toBeInTheDocument()
    expect(screen.getByText(response.card.disclaimer)).toBeInTheDocument()
    expect(mockedFetchRetailDecision).toHaveBeenCalledWith('002460.SZ')
  })

  it('renders an error fallback when the API fails', async () => {
    mockedFetchRetailDecision.mockRejectedValue(new Error('network down'))

    render(<RetailTradeDecisionCard symbol="002460.SZ" />)

    expect(await screen.findByText(/新散户决策卡暂不可用/)).toBeInTheDocument()
    expect(screen.getByText(/network down/)).toBeInTheDocument()
  })
})