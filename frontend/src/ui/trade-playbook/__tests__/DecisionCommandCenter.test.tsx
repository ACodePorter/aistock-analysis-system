import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { StockTradePlaybookResponse, TomorrowPlaybookResponse, TradePlaybook } from '../../../api/tradePlaybook'
import DecisionCommandCenter from '../DecisionCommandCenter'

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
  buyPlan: { idealBuyRange: [97.8, 99.2], breakoutBuyAbove: 102.97, doNotChaseAbove: 101.95, maxPositionPct: 8, buyConditions: ['回调到计划区间。'], cancelBuyConditions: ['高于不追高价。'] },
  sellPlan: { takeProfitPrice1: 103.44, takeProfitPrice2: 107.17, stopLossPrice: 92.01, reduceBelow: 94, sellConditions: ['跌破止损。'] },
  scenarioPlan: { ifGapUp: '高开不追。', ifGapDown: '低开观察。', ifPullback: '回调再看。', ifBreakout: '突破确认。', ifBreakdown: '跌破止损。', ifSideways: '横盘观察。' },
  holdingPlan: { ifNotHolding: '未持有等待计划区间。', ifAlreadyHolding: '已持有按止损和目标处理。' },
  confidence: 'low',
  confidenceScore: 33,
  riskLevel: 'medium',
  riskSummary: '风险中等。',
  riskControl: ['小仓。'],
  reasons: [],
  expectedReturnRange: null,
  downsideRiskPct: null,
  riskRewardRatio: null,
  invalidationConditions: ['跌破止损。'],
  modelTrackRecord: { sampleCount: 0, plainSummary: '样本不足。' },
  dataWarnings: [],
  disclaimer: '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。',
}

const tomorrowData: TomorrowPlaybookResponse = {
  asOfDate: '2026-04-24',
  targetTradeDate: '2026-04-27',
  marketSummary: { marketTone: 'mixed', plainSummary: '明日以观察为主。', suggestedOverallAction: 'defensive', suggestedPositionSummary: '轻仓执行计划。' },
  executableNow: [],
  waitForPullback: [],
  waitForBreakout: [],
  holdWatch: [playbook],
  reduceOrSell: [],
  avoid: [],
  topFocus: [playbook],
  riskWarnings: [],
  yesterdayReviewSummary: { plainSummary: '等待复盘。', successfulPlans: [], failedPlans: [], lessons: [] },
  reviews: [],
  disclaimer: playbook.disclaimer,
}

const stockResponse: StockTradePlaybookResponse = { playbook, agentViews: {}, professionalDetails: {} }

describe('DecisionCommandCenter', () => {
  it('shows market strategy and selected stock playbook summary', () => {
    render(<DecisionCommandCenter current="002594.SZ" data={tomorrowData} stockResponse={stockResponse} loading={false} stockLoading={false} onRefresh={vi.fn()} onSelectSymbol={vi.fn()} />)

    expect(screen.getByText('明日以观察为主。')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '比亚迪：持有观察' })).toBeInTheDocument()
    expect(screen.getAllByText('97.80 - 99.20').length).toBeGreaterThan(0)
    expect(screen.getByText('103.44 / 107.17')).toBeInTheDocument()
  })

  it('selects a stock from the action board', () => {
    const onSelectSymbol = vi.fn()
    render(<DecisionCommandCenter current="" data={tomorrowData} stockResponse={stockResponse} loading={false} stockLoading={false} onRefresh={vi.fn()} onSelectSymbol={onSelectSymbol} />)

    fireEvent.click(screen.getByRole('button', { name: /比亚迪/ }))

    expect(onSelectSymbol).toHaveBeenCalledWith('002594.SZ')
  })
})