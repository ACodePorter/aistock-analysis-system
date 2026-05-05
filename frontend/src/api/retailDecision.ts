import { API_ENDPOINTS, buildApiUrl } from '../config/api'

export type RetailFinalAction = 'can_buy' | 'small_position_watch' | 'wait' | 'sell_reduce' | 'avoid'
export type RetailRiskLevel = 'low' | 'medium' | 'high' | 'extreme' | string

export interface RetailPriceRange {
  min: number
  max: number
  label: string
}

export interface RetailPositionPct {
  min: number
  max: number
  label: string
}

export interface RetailTradeDecisionCardData {
  stockCode: string
  stockName: string
  finalAction: RetailFinalAction
  finalActionLabel: string
  plainConclusion: string
  oneSentenceReason: string
  currentPrice: number | null
  latestPriceDate: string | null
  suggestedBuyRange: RetailPriceRange | null
  lowAbsorbPrice: number | null
  doNotChaseAbove: number | null
  stopLossPrice: number | null
  takeProfitPrice1: number | null
  takeProfitPrice2: number | null
  suggestedPositionPct: RetailPositionPct | null
  applicableHorizon: string
  confidence: number
  confidenceLabel: string
  riskLevel: RetailRiskLevel
  riskLabel: string
  riskScore: number | null
  invalidationCondition: string
  dataWarnings: string[]
  disclaimer: string
}

export interface RetailAgentView {
  title: string
  stance: string
  points: string[]
}

export interface StockRetailDecisionResponse {
  symbol: string
  generatedAt: string
  card: RetailTradeDecisionCardData
  agentViews: Record<string, RetailAgentView>
  professionalDetails: Record<string, any>
  disclaimer: string
}

export interface TomorrowRetailActionItem {
  symbol: string
  name: string
  action: RetailFinalAction
  actionLabel: string
  currentPrice: number | null
  suggestedBuyRange: RetailPriceRange | null
  doNotChaseAbove: number | null
  stopLossPrice: number | null
  takeProfitPrice1: number | null
  riskLevel: RetailRiskLevel
  riskLabel: string
  confidence: number
  oneSentenceReason: string
  plainConclusion: string
}

export interface TomorrowRetailActionsResponse {
  generatedAt: string
  source: string
  marketSummary: string
  tomorrowStrategy: string
  buyCandidates: TomorrowRetailActionItem[]
  watchCandidates: TomorrowRetailActionItem[]
  sellCandidates: TomorrowRetailActionItem[]
  avoidCandidates: TomorrowRetailActionItem[]
  dataHealth: {
    requestedCount: number
    returnedCount: number
    buyCount: number
    watchCount: number
    sellCount: number
    avoidCount: number
    warnings: string[]
  }
  disclaimer: string
}

async function jfetch<T>(path: string): Promise<T> {
  const res = await fetch(buildApiUrl(path), { cache: 'no-store' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchRetailDecision(symbol: string): Promise<StockRetailDecisionResponse> {
  return jfetch<StockRetailDecisionResponse>(API_ENDPOINTS.STOCKS.RETAIL_DECISION(symbol))
}

export async function fetchTomorrowRetailActions(limit = 12): Promise<TomorrowRetailActionsResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  return jfetch<TomorrowRetailActionsResponse>(`${API_ENDPOINTS.DASHBOARD.TOMORROW_RETAIL_ACTIONS}?${params.toString()}`)
}