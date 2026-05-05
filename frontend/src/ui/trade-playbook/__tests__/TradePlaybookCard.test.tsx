import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { StockTradePlaybookResponse, TradePlaybook } from '../../../api/tradePlaybook'
import { TradePlaybookCard } from '../TradePlaybookCard'

const basePlaybook: TradePlaybook = {
  stockCode: '002460.SZ',
  stockName: '测试股份',
  asOfDate: '2026-04-24',
  targetTradeDate: '2026-04-27',
  targetHorizon: 'D3',
  currentPrice: 10,
  actionCategory: 'hold_watch',
  actionLabel: '持有观察',
  plainSummary: '等待计划内价位。',
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
  modelTrackRecord: {
    sampleCount: 40,
    plainSummary: '近窗方向准确率约 63.0%。',
    directionAccuracy: 63,
  },
  dataWarnings: [],
  disclaimer: '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。',
}

function responseWith(playbook: TradePlaybook): StockTradePlaybookResponse {
  return {
    playbook,
    agentViews: {},
    professionalDetails: {},
  }
}

describe('TradePlaybookCard', () => {
  it('uses retail metric explanations for model track record', () => {
    render(<TradePlaybookCard response={responseWith(basePlaybook)} />)

    expect(screen.getByText('63.0%')).toBeInTheDocument()
    expect(screen.getByText(/最近模型方向判断相对较好/)).toBeInTheDocument()
  })

  it('does not render undefined when direction accuracy is missing', () => {
    const playbook: TradePlaybook = {
      ...basePlaybook,
      modelTrackRecord: {
        sampleCount: 12,
        plainSummary: '方向准确率样本不足，保守参考。',
      },
    }

    const { container } = render(<TradePlaybookCard response={responseWith(playbook)} />)

    expect(screen.getByText('样本不足')).toBeInTheDocument()
    expect(screen.getByText('方向准确率样本不足，保守参考。')).toBeInTheDocument()
    expect(container).not.toHaveTextContent('undefined%')
  })
})