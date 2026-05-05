import { apiFetch } from './client'

export interface ModelCenterItem {
  symbol: string
  model_status: string
  task: string | null
  algo: string | null
  active_version: number | null
  review_status: string | null
  verification_status: string | null
  gate_status: string | null
  failure_severity: string | null
  high_deviation_count: number
  updated_at: string | null
}

export interface ModelCenterResponse {
  symbol: string | null
  migration_status: {
    schema_table: boolean
    applied_versions: string[]
    agent_iteration_ready: boolean
  }
  summary: {
    qe_model_count: number
    registry_model_count: number
    recent_lifecycle_count: number
    recent_review_count: number
    recent_failure_count: number
    feature_snapshot_count: number
  }
  items: ModelCenterItem[]
  recent_lifecycle_events: Array<{
    id: number
    symbol: string | null
    event_type: string
    trigger_reason: string
    model_name: string | null
    score_before: number | null
    score_after: number | null
    created_at: string | null
  }>
  recent_agent_reviews: Array<{
    review_id: string
    symbol: string
    status: string
    priority: string
    verification_status: string
    gate_status: string | null
    created_at: string | null
  }>
  disclaimer: string
}

export interface IterationRecordsResponse {
  symbol: string
  persistence_status: string
  missing_tables?: string[]
  feature_snapshots: any[]
  failure_analyses: any[]
  agent_reviews: any[]
}

export interface StrategyBacktestResponse {
  symbol: string
  strategy: string
  lookback_days: number
  parameters?: Record<string, any>
  sample_count: number
  trades: Array<Record<string, any>>
  metrics: {
    total_return_pct: number | null
    win_rate: number | null
    avg_trade_return_pct: number | null
    max_drawdown_pct: number | null
    trade_count: number
    evaluated_count?: number
  }
  gate_result: {
    status: string
    next_state: string
    checks: Array<{ name: string; status: string; message: string; value: any; threshold: any }>
    failed_checks: string[]
    warning_checks: string[]
    message: string
  }
  latest_agent_gate: Record<string, any> | null
  disclaimer: string
}

export function fetchModelCenter(symbol?: string, limit = 20): Promise<ModelCenterResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (symbol) params.set('symbol', symbol)
  return apiFetch<ModelCenterResponse>(`/api/models/center?${params.toString()}`)
}

export function fetchIterationRecords(symbol: string, limit = 10): Promise<IterationRecordsResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  return apiFetch<IterationRecordsResponse>(`/api/stocks/${encodeURIComponent(symbol)}/iteration-records?${params.toString()}`)
}

export function fetchStrategyBacktest(symbol: string, lookbackDays = 120): Promise<StrategyBacktestResponse> {
  const params = new URLSearchParams({ lookback_days: String(lookbackDays) })
  return apiFetch<StrategyBacktestResponse>(`/api/models/${encodeURIComponent(symbol)}/strategy-backtest?${params.toString()}`)
}