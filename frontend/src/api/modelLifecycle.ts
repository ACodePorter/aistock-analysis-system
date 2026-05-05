import { apiFetch } from './client'

export interface ModelLifecycleEventItem {
  id: number
  symbol: string | null
  event_type: string
  trigger_reason: string
  model_name: string | null
  score_before: number | null
  score_after: number | null
  created_at: string | null
  details: Record<string, unknown> | null
}

export interface ModelLifecycleSummary {
  latest_event_type: string | null
  latest_event_at: string | null
  latest_retrain_at: string | null
  latest_trigger_at: string | null
  latest_stagnation_at: string | null
  active_status: 'unknown' | 'needs_retrain' | 'optimized' | 'retained' | 'stagnated' | string
  active_reason: string
}

export interface ModelLifecycleResponse {
  symbol: string
  count: number
  summary: ModelLifecycleSummary
  items: ModelLifecycleEventItem[]
}

export function fetchModelLifecycle(symbol: string, limit = 20): Promise<ModelLifecycleResponse> {
  const qs = new URLSearchParams({ symbol, limit: String(limit) })
  return apiFetch<ModelLifecycleResponse>(`/api/models/lifecycle?${qs.toString()}`)
}