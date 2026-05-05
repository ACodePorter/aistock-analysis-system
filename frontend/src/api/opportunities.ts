import { API_ENDPOINTS, buildApiUrl } from '../config/api'

export interface OpportunityCandidate {
  id: number
  symbol: string
  name?: string | null
  source: string
  status: string
  opportunityScore?: number | null
  confidence?: number | null
  riskLevel?: string | null
  recommendedAction?: string | null
  rationale?: string | null
  evidence?: Record<string, any>
  autoPinned: boolean
  discoveredAt?: string | null
  expiresAt?: string | null
  reviewedAt?: string | null
  reviewNotes?: string | null
}

export interface DiscoverOpportunitiesInput {
  scan_limit?: number
  max_candidates?: number
  auto_pin?: boolean
  portfolio_id?: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(buildApiUrl(path), { cache: 'no-store', ...init })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchOpportunityCandidates(status?: string) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  const suffix = params.toString() ? `?${params}` : ''
  return request<{ candidates: OpportunityCandidate[] }>(`${API_ENDPOINTS.OPPORTUNITIES.LIST}${suffix}`)
}

export async function discoverOpportunities(payload: DiscoverOpportunitiesInput = {}) {
  return request<{
    ok: boolean
    scanned: number
    skipped: Record<string, number>
    autoPinnedCount: number
    pendingCount: number
    candidates: OpportunityCandidate[]
  }>(API_ENDPOINTS.OPPORTUNITIES.DISCOVER, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function approveOpportunityCandidate(symbol: string, notes?: string) {
  return request<{ ok: boolean; candidate: OpportunityCandidate }>(API_ENDPOINTS.OPPORTUNITIES.APPROVE(symbol), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ notes }),
  })
}