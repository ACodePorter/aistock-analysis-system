import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import TomorrowRetailActionList from '../TomorrowRetailActionList'
import { fetchTomorrowRetailActions } from '../../../api/retailDecision'

vi.mock('../../../api/retailDecision', () => ({
  fetchTomorrowRetailActions: vi.fn(),
}))

const mockedFetchTomorrowRetailActions = vi.mocked(fetchTomorrowRetailActions)

const response = {
  generatedAt: '2026-04-26T00:00:00Z',
  source: 'pinned-watchlist',
  marketSummary: '当前清单基于最新模型生成。',
  tomorrowStrategy: '明日优先看低吸计划，不追高。',
  buyCandidates: [
    {
      symbol: '002460.SZ',
      name: '测试股份',
      action: 'can_buy',
      actionLabel: '可以小仓试买',
      currentPrice: 10,
      suggestedBuyRange: { min: 9.8, max: 10.1, label: '9.80 - 10.10' },
      doNotChaseAbove: 10.25,
      stopLossPrice: 9.35,
      takeProfitPrice1: 10.8,
      riskLevel: 'medium',
      riskLabel: '中等',
      confidence: 0.66,
      oneSentenceReason: '模型上涨概率 62.0%',
      plainConclusion: '可以按计划小仓试买。',
    },
  ],
  watchCandidates: [],
  sellCandidates: [],
  avoidCandidates: [],
  dataHealth: {
    requestedCount: 1,
    returnedCount: 1,
    buyCount: 1,
    watchCount: 0,
    sellCount: 0,
    avoidCount: 0,
    warnings: [],
  },
  disclaimer: '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。',
} as const

describe('TomorrowRetailActionList', () => {
  beforeEach(() => {
    mockedFetchTomorrowRetailActions.mockReset()
  })

  it('renders grouped candidates and supports selecting a symbol', async () => {
    mockedFetchTomorrowRetailActions.mockResolvedValue(response as any)
    const onSelectSymbol = vi.fn()

    render(<TomorrowRetailActionList current="002460.SZ" onSelectSymbol={onSelectSymbol} />)

    expect(await screen.findByText(response.tomorrowStrategy)).toBeInTheDocument()
    expect(screen.getByText('可以买入')).toBeInTheDocument()
    expect(screen.getByText('1 只')).toBeInTheDocument()
    expect(screen.getByText('9.80 - 10.10')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /测试股份/ }))
    expect(onSelectSymbol).toHaveBeenCalledWith('002460.SZ')
    expect(mockedFetchTomorrowRetailActions).toHaveBeenCalledWith(12)
  })

  it('renders an error fallback when the API fails', async () => {
    mockedFetchTomorrowRetailActions.mockRejectedValue(new Error('api unavailable'))

    render(<TomorrowRetailActionList onSelectSymbol={vi.fn()} />)

    expect(await screen.findByText(/新清单暂不可用/)).toBeInTheDocument()
    expect(screen.getByText(/api unavailable/)).toBeInTheDocument()
    expect(screen.getByText(response.disclaimer)).toBeInTheDocument()
  })
})