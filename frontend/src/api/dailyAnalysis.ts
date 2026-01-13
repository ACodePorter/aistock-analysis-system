import { buildApiUrl, API_ENDPOINTS } from '../config/api'

// Types
export interface AgentLatestReport {
  generated_at: string
  trade_date?: string
  top_symbols?: string[]
  top_stocks?: Array<{ symbol: string; name?: string | null }>
  top_metrics?: Record<string, any>
  summary_markdown?: string
  summary_json?: any
  stock_reports?: Array<{ symbol: string; name?: string | null; news_count?: number }>
  diagnostics?: {
    token_count?: number
    truncated?: boolean
    parse_mode?: string
  }
  // internal / fallback fields
  status?: string
  created_at?: string
  finished_at?: string
  job_id?: string
  fallback?: string
  message?: string
  _path?: string | null
}

export interface StockPoolItem {
  symbol: string
  first_seen: string
  last_seen: string
  exit_date?: string | null
  industry?: string | null
  days_active?: number
  in_pool?: boolean
}

export interface StockPoolPage {
  page: number
  page_size: number
  total: number
  items: StockPoolItem[]
}

export interface ModelPredictionRequest {
  symbols: string[]
  horizons?: number[] // e.g. [1,5,10]
}

export interface ModelPredictionResponse {
  generated_at: string
  model: string
  predictions: Array<{
    symbol: string
    horizon: number
    yhat: number
    prob_up?: number
    features_used?: string[]
  }>
  metadata?: Record<string, any>
}

async function jfetch<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(endpoint), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) }
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json() as Promise<T>
}

export async function fetchLatestAgentReport(opts?: { forceFilesystem?: boolean }): Promise<AgentLatestReport | null> {
  try {
    // Prefer persisted daily endpoint
    let raw: any | null = null
    try {
      const preferFS = opts?.forceFilesystem ? '&prefer_filesystem=true' : ''
      raw = await jfetch<any>(`${API_ENDPOINTS.AGENT.DAILY_LATEST}?with_markdown=true${preferFS}`)
    } catch (e) {
      // Fallback to legacy file-scan endpoint
      raw = await jfetch<any>(API_ENDPOINTS.AGENT.LATEST)
    }

    // If persisted shape
    if (raw && typeof raw === 'object' && 'report_date' in raw) {
      const stockReports = Array.isArray(raw.stock_reports) ? raw.stock_reports : []
      const topStocks = stockReports
        .map((s: any) => ({ symbol: typeof s?.symbol === 'string' ? s.symbol : '', name: s?.name ?? undefined }))
        .filter((s: any) => !!s.symbol)
      const topSymbols = topStocks.map((s: any) => s.symbol)
      const mapped: AgentLatestReport = {
        generated_at: raw.generated_at || new Date().toISOString(),
        trade_date: raw.report_date,
        top_symbols: topSymbols as string[],
        top_stocks: topStocks as Array<{ symbol: string; name?: string | null }>,
        summary_markdown: typeof raw.markdown === 'string' ? raw.markdown : undefined,
        summary_json: raw.macro || raw.analytics || undefined,
        stock_reports: stockReports as Array<{ symbol: string; name?: string | null; news_count?: number }>,
        diagnostics: raw.diagnostics || undefined,
        job_id: raw.job_id,
      }
      return mapped
    }

    // Legacy shapes
    let report: any = raw
    if (raw && typeof raw === 'object' && 'report' in raw && raw.report) {
      report = { ...raw.report, _path: raw.path ?? null }
    }
    if (!report || typeof report !== 'object') return null
    if (report.fallback === 'empty' || report.message === 'no reports yet') return null
    if (!report.generated_at) report.generated_at = report.finished_at || report.created_at || new Date().toISOString()
    return report as AgentLatestReport
  } catch (e) {
    console.warn('fetchLatestAgentReport failed', e)
    return null
  }
}

// Trigger a new agent run
export interface RunAgentResponse { job_id: string; status: string; queue_position?: number; concurrency_limit?: number }
export async function runAgent(strict_json: boolean = false): Promise<RunAgentResponse> {
  return jfetch<RunAgentResponse>(`${API_ENDPOINTS.AGENT.RUN}?strict_json=${strict_json ? 'true' : 'false'}`, { method: 'POST' })
}

// Agent status polling
export interface AgentStatusResponse {
  status: string
  job_id: string
  strict?: boolean
  created_at?: string
  started_at?: string
  finished_at?: string
  duration_sec?: number
  error?: string
  stdout_tail?: string[]
  stderr_tail?: string[]
  reports_detected?: any[]
}
export async function fetchAgentStatus(jobId: string): Promise<AgentStatusResponse> {
  return jfetch<AgentStatusResponse>(`/api/agent/status/${jobId}`)
}

export async function fetchStockPoolPage(params: { page?: number; page_size?: number; industry?: string; sort?: string; order?: 'asc' | 'desc' } = {}): Promise<StockPoolPage> {
  const { page = 1, page_size = 50, industry, sort = 'days_active', order = 'desc' } = params
  return jfetch<StockPoolPage>(API_ENDPOINTS.STOCK_POOL.LIST(page, page_size, industry, sort, order))
}

export async function fetchModelPrediction(req: ModelPredictionRequest): Promise<ModelPredictionResponse> {
  return jfetch<ModelPredictionResponse>(API_ENDPOINTS.MODELS.PREDICT, { method: 'POST', body: JSON.stringify(req) })
}

// Ensure batch live news counts (UI can use this to avoid stale zeros)
export interface EnsureCountsItem { symbol: string; total_count: number; below_min: boolean }
export interface EnsureCountsResponse { ensure_min: number; results: EnsureCountsItem[] }
export async function ensureNewsCounts(params: { symbols: string[]; ensure_min?: number; wait_seconds?: number }): Promise<EnsureCountsResponse> {
  const payload = {
    symbols: params.symbols,
    ensure_min: params.ensure_min ?? 5,
    wait_seconds: params.wait_seconds ?? 2,
    trigger_topup: true,
    allow_placeholder: true,
  }
  return jfetch<EnsureCountsResponse>(API_ENDPOINTS.NEWS.ENSURE_COUNTS, { method: 'POST', body: JSON.stringify(payload) })
}
