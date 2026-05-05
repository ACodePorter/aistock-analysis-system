import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import TomorrowPlaybookBoard from '../TomorrowPlaybookBoard'
import { fetchTomorrowPlaybook } from '../../../api/tradePlaybook'

vi.mock('../../../api/tradePlaybook', () => ({
  fetchTomorrowPlaybook: vi.fn(),
}))

const mockedFetchTomorrowPlaybook = vi.mocked(fetchTomorrowPlaybook)

const playbook = {
  stockCode: '002460.SZ',
  stockName: '测试股份',
  asOfDate: '2026-04-24',
  targetTradeDate: '2026-04-27',
  targetHorizon: 'D3',
  currentPrice: 10,
  actionCategory: 'executable_now',
  actionLabel: '立即可执行',
  plainSummary: '当前落在计划区间，可以小仓试探。',
  buyPlan: {
    idealBuyRange: [9.8, 10.1],
    breakoutBuyAbove: 10.35,
    doNotChaseAbove: 10.25,
    maxPositionPct: 18,
    buyConditions: ['价格仍在计划区间内。'],
    cancelBuyConditions: ['高开快速拉升超过不追高价。'],
  },
  sellPlan: {
    takeProfitPrice1: 10.8,
    takeProfitPrice2: 11.2,
    stopLossPrice: 9.35,
    reduceBelow: 9.45,
    sellConditions: ['跌破止损，本次计划失效。'],
  },
  scenarioPlan: {
    ifGapUp: '高开不追。',
    ifGapDown: '低开等待企稳。',
    ifPullback: '回调到计划区间再看。',
    ifBreakout: '突破确认后小仓。',
    ifBreakdown: '跌破止损退出。',
    ifSideways: '横盘观察。',
  },
  holdingPlan: {
    ifNotHolding: '未持有只在计划区间执行。',
    ifAlreadyHolding: '已持有按目标和止损处理。',
  },
  confidence: 'medium',
  confidenceScore: 68,
  riskLevel: 'medium',
  riskSummary: '风险中等。',
  riskControl: ['最大仓位不超过 18%。'],
  reasons: [],
  expectedReturnRange: [3, 8],
  downsideRiskPct: 4,
  riskRewardRatio: 1.5,
  invalidationConditions: ['跌破止损。'],
  modelTrackRecord: { sampleCount: 40, plainSummary: '近窗方向准确率约 63.0%。', directionAccuracy: 63 },
  dataWarnings: [],
  disclaimer: '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。',
} as const

const response = {
  asOfDate: '2026-04-24',
  targetTradeDate: '2026-04-27',
  marketSummary: {
    marketTone: 'mixed',
    plainSummary: '明日可关注少数计划内机会。',
    suggestedOverallAction: 'selective',
    suggestedPositionSummary: '建议轻仓到中低仓位。',
  },
  executableNow: [playbook],
  waitForPullback: [],
  waitForBreakout: [],
  holdWatch: [],
  reduceOrSell: [],
  avoid: [],
  topFocus: [playbook],
  riskWarnings: ['高开急拉不追。'],
  yesterdayReviewSummary: {
    plainSummary: '最近计划回放中，1 个计划有效或部分有效。',
    successfulPlans: [],
    failedPlans: [],
    lessons: ['只执行计划内价位。'],
  },
  reviews: [],
  disclaimer: playbook.disclaimer,
} as const

describe('TomorrowPlaybookBoard', () => {
  beforeEach(() => {
    mockedFetchTomorrowPlaybook.mockReset()
  })

  it('renders playbook groups and supports selecting a symbol', async () => {
    mockedFetchTomorrowPlaybook.mockResolvedValue(response as any)
    const onSelectSymbol = vi.fn()

    render(<TomorrowPlaybookBoard current="002460.SZ" onSelectSymbol={onSelectSymbol} />)

    expect(await screen.findByText(response.marketSummary.plainSummary)).toBeInTheDocument()
    expect(screen.getAllByText('立即可执行').length).toBeGreaterThan(0)
    expect(screen.getByText('测试股份')).toBeInTheDocument()
    expect(screen.getByText('9.80 - 10.10')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /测试股份/ }))
    expect(onSelectSymbol).toHaveBeenCalledWith('002460.SZ')
    expect(mockedFetchTomorrowPlaybook).toHaveBeenCalledWith(12)
  })

  it('renders an error fallback when the API fails', async () => {
    mockedFetchTomorrowPlaybook.mockRejectedValue(new Error('api unavailable'))

    render(<TomorrowPlaybookBoard onSelectSymbol={vi.fn()} />)

    expect(await screen.findByText(/交易剧本暂不可用/)).toBeInTheDocument()
    expect(screen.getByText(/api unavailable/)).toBeInTheDocument()
    expect(screen.getByText(playbook.disclaimer)).toBeInTheDocument()
  })
})