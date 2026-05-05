import { API_ENDPOINTS, buildApiUrl } from '../config/api'

export type TradeSide = 'buy' | 'sell'

export interface UserPosition {
  portfolio_id: string
  symbol: string
  name?: string | null
  industry?: string | null
  quantity: number
  avg_cost?: number | null
  total_cost?: number | null
  current_price?: number | null
  price_date?: string | null
  market_value?: number | null
  unrealized_pnl?: number | null
  unrealized_pnl_pct?: number | null
  realized_pnl?: number | null
  weight_pct?: number | null
  first_entry_date?: string | null
  last_trade_date?: string | null
  holding_days?: number | null
  source?: string | null
  updated_at?: string | null
}

export interface UserTrade {
  id: number
  portfolio_id: string
  symbol: string
  side: TradeSide
  trade_date: string
  price: number
  quantity: number
  fees: number
  tax: number
  source: string
  external_trade_id?: string | null
  notes?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface TradeInput {
  symbol: string
  side: TradeSide
  trade_date: string
  price: number
  quantity: number
  fees?: number
  tax?: number
  source?: string
  external_trade_id?: string | null
  notes?: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(buildApiUrl(path), { cache: 'no-store', ...init })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchUserPositions(portfolioId = 'default') {
  const params = new URLSearchParams({ portfolio_id: portfolioId })
  return request<{ portfolio_id: string; positions: UserPosition[]; count: number }>(`${API_ENDPOINTS.USER_PORTFOLIO.POSITIONS}?${params}`)
}

export async function fetchUserTrades(portfolioId = 'default', symbol?: string) {
  const params = new URLSearchParams({ portfolio_id: portfolioId })
  if (symbol) params.set('symbol', symbol)
  return request<{ portfolio_id: string; trades: UserTrade[]; count: number }>(`${API_ENDPOINTS.USER_PORTFOLIO.TRADES}?${params}`)
}

export async function createUserTrade(payload: TradeInput, portfolioId = 'default') {
  const params = new URLSearchParams({ portfolio_id: portfolioId })
  return request<{ ok: boolean; trade: UserTrade }>(`${API_ENDPOINTS.USER_PORTFOLIO.TRADES}?${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function updateUserTrade(id: number, payload: Partial<TradeInput>) {
  return request<{ ok: boolean; trade: UserTrade }>(API_ENDPOINTS.USER_PORTFOLIO.TRADE(id), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function deleteUserTrade(id: number) {
  return request<{ ok: boolean }>(API_ENDPOINTS.USER_PORTFOLIO.TRADE(id), { method: 'DELETE' })
}

export async function recomputeUserPortfolio(portfolioId = 'default') {
  const params = new URLSearchParams({ portfolio_id: portfolioId })
  return request<{ ok: boolean; portfolio_id: string; symbols_recomputed: number }>(`${API_ENDPOINTS.USER_PORTFOLIO.RECOMPUTE}?${params}`, { method: 'POST' })
}