import { API_ENDPOINTS, buildApiUrl } from '../config/api'

export type TradeActionCategory =
  | 'executable_now'
  | 'wait_for_pullback'
  | 'wait_for_breakout'
  | 'hold_watch'
  | 'reduce'
  | 'sell'
  | 'avoid'

export type TradeRiskLevel = 'low' | 'medium' | 'high' | 'extreme' | (string & {})
export type TradeConfidence = 'low' | 'medium' | 'high' | (string & {})
export type ReasonImpact = 'positive' | 'negative' | 'neutral' | (string & {})

export interface TradePlaybookReason {
  type: string
  title: string
  plainText: string
  impact: ReasonImpact
}

export interface BuyPlan {
  idealBuyRange: [number, number] | null
  breakoutBuyAbove: number | null
  doNotChaseAbove: number | null
  maxPositionPct: number
  buyConditions: string[]
  cancelBuyConditions: string[]
}

export interface SellPlan {
  takeProfitPrice1: number | null
  takeProfitPrice2: number | null
  stopLossPrice: number | null
  reduceBelow: number | null
  sellConditions: string[]
}

export interface ScenarioPlan {
  ifGapUp: string
  ifGapDown: string
  ifPullback: string
  ifBreakout: string
  ifBreakdown: string
  ifSideways: string
}

export interface HoldingPlan {
  ifNotHolding: string
  ifAlreadyHolding: string
}

export interface PositionContext {
  isHolding: boolean
  quantity?: number
  avgCost?: number | null
  totalCost?: number | null
  marketValue?: number | null
  unrealizedPnl?: number | null
  unrealizedPnlPct?: number | null
  realizedPnl?: number | null
  firstEntryDate?: string | null
  lastTradeDate?: string | null
  holdingDays?: number | null
  costToStopPct?: number | null
  priceToStopPct?: number | null
  priceToTarget1Pct?: number | null
}

export interface ModelTrackRecord {
  sampleCount: number
  plainSummary: string
  directionAccuracy?: number | null
  mape?: number | null
  intervalHitRate?: number | null
}

export interface TradePlaybook {
  stockCode: string
  stockName: string
  asOfDate: string
  targetTradeDate: string
  targetHorizon: 'D1' | 'D2' | 'D3' | 'D5' | (string & {})
  currentPrice: number | null
  actionCategory: TradeActionCategory
  actionLabel: string
  plainSummary: string
  buyPlan: BuyPlan
  sellPlan: SellPlan
  scenarioPlan: ScenarioPlan
  holdingPlan: HoldingPlan
  positionContext: PositionContext
  confidence: TradeConfidence
  confidenceScore: number
  riskLevel: TradeRiskLevel
  riskSummary: string
  riskControl: string[]
  reasons: TradePlaybookReason[]
  expectedReturnRange: [number, number] | null
  downsideRiskPct: number | null
  riskRewardRatio: number | null
  invalidationConditions: string[]
  modelTrackRecord: ModelTrackRecord
  dataWarnings: string[]
  disclaimer: string
}

export interface TradePlanReview {
  id: string
  stockCode: string
  stockName: string
  planDate: string
  targetTradeDate: string
  originalActionCategory: TradeActionCategory
  plannedBuyRange: [number, number] | null
  plannedStopLoss: number | null
  plannedTakeProfit1: number | null
  plannedTakeProfit2: number | null
  actualOpen: number | null
  actualHigh: number | null
  actualLow: number | null
  actualClose: number | null
  buyTriggered: boolean
  stopLossTriggered: boolean
  takeProfit1Triggered: boolean
  takeProfit2Triggered: boolean
  planResult: string
  plainReview: string
  lessons: string[]
}

export interface PlaybookAgentView {
  title: string
  stance: string
  points: string[]
}

export interface StockTradePlaybookResponse {
  playbook: TradePlaybook
  agentViews: Record<string, PlaybookAgentView | null>
  professionalDetails: Record<string, any>
}

export interface TomorrowMarketSummary {
  marketTone: string
  plainSummary: string
  suggestedOverallAction: string
  suggestedPositionSummary: string
}

export interface YesterdayReviewSummary {
  plainSummary: string
  successfulPlans: string[]
  failedPlans: string[]
  lessons: string[]
}

export interface TomorrowPlaybookResponse {
  asOfDate: string
  targetTradeDate: string
  marketSummary: TomorrowMarketSummary
  executableNow: TradePlaybook[]
  waitForPullback: TradePlaybook[]
  waitForBreakout: TradePlaybook[]
  holdWatch: TradePlaybook[]
  reduceOrSell: TradePlaybook[]
  avoid: TradePlaybook[]
  topFocus: TradePlaybook[]
  riskWarnings: string[]
  yesterdayReviewSummary: YesterdayReviewSummary
  reviews: TradePlanReview[]
  disclaimer: string
}

async function jfetch<T>(path: string): Promise<T> {
  const res = await fetch(buildApiUrl(path), { cache: 'no-store' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchTradePlaybook(symbol: string): Promise<StockTradePlaybookResponse> {
  return jfetch<StockTradePlaybookResponse>(API_ENDPOINTS.STOCKS.TRADE_PLAYBOOK(symbol))
}

export async function fetchTomorrowPlaybook(limit = 12): Promise<TomorrowPlaybookResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  return jfetch<TomorrowPlaybookResponse>(`${API_ENDPOINTS.DASHBOARD.TOMORROW_PLAYBOOK}?${params.toString()}`)
}