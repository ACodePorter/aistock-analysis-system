import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { StockTradePlaybookResponse, TomorrowPlaybookResponse, TradePlaybook } from '../../../api/tradePlaybook'
import StockDetailTabs from '../StockDetailTabs'

vi.mock('../TradePlaybookCard', () => ({
  TradePlaybookCard: ({ response }: { response: StockTradePlaybookResponse }) => <div>剧本卡：{response.playbook.stockName}</div>,
}))

vi.mock('../../HomePriceChartSection', () => ({
  default: ({ current, professionalMode }: { current?: string; professionalMode?: boolean }) => <div>预测图表面板：{current} / {professionalMode ? '专业' : '普通'}</div>,
}))

vi.mock('../../HomeReviewDetailsSection', () => ({
  default: () => <div>专业复盘明细</div>,
}))

vi.mock('../../HomeModelStatusSection', () => ({
  default: ({ current }: { current?: string }) => <div>专业数据面板：{current}</div>,
}))

vi.mock('../../HomeStockReportSection', () => ({
  default: ({ currentName }: { currentName?: string }) => <div>个股报表：{currentName}</div>,
}))

const playbook: TradePlaybook = {
  stockCode: '002594.SZ',
  stockName: '比亚迪',
  asOfDate: '2026-04-24',
  targetTradeDate: '2026-04-27',
  targetHorizon: 'D3',
  currentPrice: 99.46,
  actionCategory: 'hold_watch',
  actionLabel: '持有观察',
  plainSummary: '按计划观察，不追高。',
  buyPlan: { idealBuyRange: [97.8, 99.2], breakoutBuyAbove: 102.97, doNotChaseAbove: 101.95, maxPositionPct: 8, buyConditions: [], cancelBuyConditions: [] },
  sellPlan: { takeProfitPrice1: 103.44, takeProfitPrice2: 107.17, stopLossPrice: 92.01, reduceBelow: 94, sellConditions: [] },
  scenarioPlan: { ifGapUp: '', ifGapDown: '', ifPullback: '', ifBreakout: '', ifBreakdown: '', ifSideways: '' },
  holdingPlan: { ifNotHolding: '', ifAlreadyHolding: '' },
  confidence: 'low',
  confidenceScore: 33,
  riskLevel: 'medium',
  riskSummary: '风险中等。',
  riskControl: [],
  reasons: [],
  expectedReturnRange: null,
  downsideRiskPct: null,
  riskRewardRatio: null,
  invalidationConditions: [],
  modelTrackRecord: { sampleCount: 0, plainSummary: '样本不足。' },
  dataWarnings: [],
  disclaimer: '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。',
}

const response: StockTradePlaybookResponse = {
  playbook,
  agentViews: {
    technical: { title: '技术面解释', points: ['价格接近计划区间。'] },
  },
  professionalDetails: {},
}

const tomorrowData: TomorrowPlaybookResponse = {
  asOfDate: '2026-04-24',
  targetTradeDate: '2026-04-27',
  marketSummary: { marketTone: 'mixed', plainSummary: '明日以观察为主。', suggestedOverallAction: 'defensive', suggestedPositionSummary: '轻仓执行。' },
  executableNow: [],
  waitForPullback: [],
  waitForBreakout: [],
  holdWatch: [playbook],
  reduceOrSell: [],
  avoid: [],
  topFocus: [playbook],
  riskWarnings: [],
  yesterdayReviewSummary: { plainSummary: '昨日计划整体按观察执行。', successfulPlans: [], failedPlans: [], lessons: [] },
  reviews: [{ id: 'r1', stockCode: '002594.SZ', stockName: '比亚迪', planResult: '未触发', plainReview: '价格没有进入买入区，继续等待。' }],
  disclaimer: playbook.disclaimer,
}

function renderTabs(professionalMode = false) {
  return render(
    <StockDetailTabs
      current="002594.SZ"
      currentName="比亚迪"
      response={response}
      tomorrowData={tomorrowData}
      professionalMode={professionalMode}
      timeRange="5d"
      predictionHistory={null}
      predictionHistoryLoading={false}
      loading={false}
      merged={[]}
      chartSeries={{ hasHistoryD1: false, hasHistoryD1Band: false, hasHistoryD5: false, hasForecast: false, hasForecastBand: false, hasExpiredForecast: false, hasExpiredForecastBand: false }}
      insight={null}
      insightLoading={false}
      report={null}
      onTimeRangeChange={vi.fn()}
      onOpenDiagnostics={vi.fn()}
      onRunDaily={vi.fn()}
      onRefreshPlaybook={vi.fn()}
    />,
  )
}

describe('StockDetailTabs', () => {
  it('renders playbook first and switches to agent reasons', () => {
    renderTabs()

    expect(screen.getByText('剧本卡：比亚迪')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /为什么这样判断/ }))

    expect(screen.getByText('技术面解释')).toBeInTheDocument()
    expect(screen.getByText('价格接近计划区间。')).toBeInTheDocument()
  })

  it('shows chart and professional panels through detail tabs', () => {
    renderTabs(true)

    fireEvent.click(screen.getByRole('button', { name: /预测图表/ }))
    expect(screen.getByText('预测图表面板：002594.SZ / 专业')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /复盘表现/ }))
    expect(screen.getByText('昨日计划整体按观察执行。')).toBeInTheDocument()
    expect(screen.getByText('专业复盘明细')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /专业数据/ }))
    expect(screen.getByText('专业数据面板：002594.SZ')).toBeInTheDocument()
    expect(screen.getByText('个股报表：比亚迪')).toBeInTheDocument()
  })
})