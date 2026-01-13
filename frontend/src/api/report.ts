import { buildApiUrl } from '../config/api'

export interface FullReportResponse {
  symbol: string
  price_data: Array<{ date: string; open?: number; high?: number; low?: number; close?: number; volume?: number; type: string }>
  predictions: Array<{ date: string; predicted_price: number; upper_bound?: number; lower_bound?: number; type: string }>
  dates?: string[]
  predictions_mean?: number[]
  predictions_upper?: number[]
  predictions_lower?: number[]
  latest_price?: any
  latest?: any
  analysis_summary?: string
  stale?: boolean
  diagnostics?: Record<string, any>
}

async function jfetch<T>(url: string): Promise<T> {
  const r = await fetch(buildApiUrl(url))
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function fetchFullReport(symbol: string, timeRange: string = '5d', opts: { diagnostics?: boolean } = {}): Promise<FullReportResponse> {
  const params = new URLSearchParams({ timeRange })
  if (opts.diagnostics) params.set('showDiagnostics', '1')
  return jfetch<FullReportResponse>(`/api/report/${encodeURIComponent(symbol)}/full?${params.toString()}`)
}
