import { apiFetch } from './client'

export type PipelineStatus = 'success' | 'failed' | 'skipped' | 'running'

export interface PipelineRunSummary {
  id: number
  symbol: string
  run_type: string
  status: PipelineStatus
  run_at: string | null
  duration_ms: number | null
  message: string | null
  error_message: string | null
  trigger: string
}

export interface PipelineRunDetail extends PipelineRunSummary {
  log_excerpt: string | null
}

export interface PipelineStatusResponse {
  symbol: string
  overall: PipelineRunSummary | null
  latest_by_type: Record<string, PipelineRunSummary>
  latest_price_date: string | null
  latest_forecast_run_at: string | null
  latest_report_updated_at: string | null
}

export interface PipelineHistoryResponse {
  symbol: string
  count: number
  items: PipelineRunDetail[]
}

export interface PipelineRetryAck {
  symbol: string
  job_id: string
  status: 'queued' | 'running' | 'success' | 'failed'
}

export interface PipelineRetryJob {
  job_id: string
  symbol: string
  status: 'queued' | 'running' | 'success' | 'failed'
  queued_at?: string
  started_at?: string
  finished_at?: string
  message?: string | null
  error?: string | null
}

export function fetchPipelineStatus(symbol: string): Promise<PipelineStatusResponse> {
  return apiFetch<PipelineStatusResponse>(
    `/api/stocks/${encodeURIComponent(symbol)}/pipeline-status`,
  )
}

export function fetchPipelineHistory(
  symbol: string,
  limit = 20,
  runType?: string,
): Promise<PipelineHistoryResponse> {
  const qs = new URLSearchParams({ limit: String(limit) })
  if (runType) qs.set('run_type', runType)
  return apiFetch<PipelineHistoryResponse>(
    `/api/stocks/${encodeURIComponent(symbol)}/pipeline-history?${qs.toString()}`,
  )
}

export function triggerPipelineRetry(symbol: string): Promise<PipelineRetryAck> {
  return apiFetch<PipelineRetryAck>(
    `/api/stocks/${encodeURIComponent(symbol)}/pipeline/retry`,
    { method: 'POST' },
  )
}

export function fetchPipelineRetryStatus(
  symbol: string,
  jobId: string,
): Promise<PipelineRetryJob> {
  return apiFetch<PipelineRetryJob>(
    `/api/stocks/${encodeURIComponent(symbol)}/pipeline/retry/${encodeURIComponent(jobId)}`,
  )
}
