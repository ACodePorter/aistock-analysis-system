import { API_ENDPOINTS, buildApiUrl } from '../config/api'

export interface FullReportResponse {
  symbol: string
  price_data: Array<{ date: string; open?: number; high?: number; low?: number; close?: number; volume?: number; type: string }>
  predictions: Array<{
    date: string
    predicted_price: number
    upper_bound?: number
    lower_bound?: number
    type: string
    /** future=未来交易日, today=今日, today_evaluated=已有实际收盘, expired=已过期未来但尚未更新 */
    status?: 'future' | 'today' | 'today_evaluated' | 'expired'
  }>
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

export interface PredictionHistoryRow {
  date: string
  actual: number | null
  d1_prediction_date?: string
  d1_model?: string
  d1_predicted?: number | null
  d1_lower?: number | null
  d1_upper?: number | null
  d1_error_pct?: number | null
  d1_signed_error_pct?: number | null
  d1_direction_ok?: boolean | null
  d1_interval_hit?: boolean | null
  d1_status?: PredictionEvaluationRowStatus
  d1_deviation_level?: PredictionDeviationLevel
  d5_prediction_date?: string
  d5_model?: string
  d5_predicted?: number | null
  d5_lower?: number | null
  d5_upper?: number | null
  d5_error_pct?: number | null
  d5_signed_error_pct?: number | null
  d5_direction_ok?: boolean | null
  d5_interval_hit?: boolean | null
  d5_status?: PredictionEvaluationRowStatus
  d5_deviation_level?: PredictionDeviationLevel
}

export type PredictionEvaluationRowStatus = 'evaluated' | 'pending_target_date' | 'missing_actual_price' | 'invalid_prediction_data'
export type PredictionAvailabilityStatus = 'available' | 'no_prediction_snapshot' | 'pending_target_date' | 'missing_actual_price' | 'insufficient_samples' | 'invalid_prediction_data' | 'task_failed' | 'unsupported_horizon'
export type PredictionDeviationLevel = 'pending' | 'low' | 'medium' | 'high' | 'critical'

export interface PredictionHistoryStats {
  total_records: number
  evaluated_records: number
  mape: number | null
  direction_accuracy: number | null
  interval_hit_rate: number | null
  d1_mape: number | null
  d5_mape: number | null
  d1_count: number
  d5_count: number
}

export interface PredictionEvaluationSummary {
  total_records: number
  evaluated_records: number
  pending_records: number
  mape: number | null
  signed_bias_pct: number | null
  direction_accuracy: number | null
  interval_hit_rate: number | null
  high_deviation_count: number
  latest_evaluated_at: string | null
}

export interface PredictionEvaluationAvailability {
  symbol: string
  available: boolean
  status: PredictionAvailabilityStatus
  reason: string
  next_action: string
  min_samples: number
  forecast_records: number
  evaluation_records: number
  evaluated_records: number
  supported_records?: number | null
  pending_records: number
  missing_actual_records: number
  latest_prediction_date: string | null
  latest_target_date: string | null
  latest_actual_date: string | null
  next_evaluable_date: string | null
  pipeline_status?: string | null
  pipeline_run_type?: string | null
  pipeline_message?: string | null
}

export interface PredictionDeviationCase {
  target_date: string | null
  prediction_date: string | null
  model: string
  horizon_days: number | null
  predicted_price: number | null
  actual_price: number | null
  lower: number | null
  upper: number | null
  error_pct: number | null
  signed_error_pct: number | null
  direction_correct: boolean | null
  interval_hit: boolean | null
  deviation_level: PredictionDeviationLevel
  reason: string
}

export interface PredictionHistoryResponse {
  symbol: string
  lookback_days: number
  rows: PredictionHistoryRow[]
  stats: PredictionHistoryStats
  summary?: PredictionEvaluationSummary
  availability?: PredictionEvaluationAvailability
  quality?: PredictionQuality | null
  failure_analysis?: FailureAnalysis | null
  agent_review?: AgentReview | null
  deviation_cases?: PredictionDeviationCase[]
  diagnostics?: Record<string, any>
  refresh?: Record<string, any> | null
}

export type PredictionQualityGrade = 'excellent' | 'good' | 'watch' | 'risk' | 'unknown'
export type PredictionQualityConfidence = 'high' | 'medium' | 'low' | 'unknown'

export interface PredictionQuality {
  symbol: string
  quality_score: number | null
  quality_grade: PredictionQualityGrade
  quality_label: string
  confidence_level: PredictionQualityConfidence
  sample_count: number
  min_samples: number
  mape: number | null
  signed_bias_pct: number | null
  direction_accuracy: number | null
  interval_hit_rate: number | null
  high_deviation_count: number
  latest_evaluated_at: string | null
  availability_status: PredictionAvailabilityStatus
  headline: string
  next_action: string
  warnings: string[]
  top_deviation_cases: PredictionDeviationCase[]
  lookback_days?: number
  availability?: PredictionEvaluationAvailability
  summary?: PredictionEvaluationSummary
  diagnostics?: Record<string, any>
}

export type FailureAnalysisSeverity = 'low' | 'medium' | 'high' | 'unknown'

export interface FailureRootCause {
  code: string
  label: string
  severity: FailureAnalysisSeverity
  evidence: string
  recommendation: string
  sample_count: number
}

export interface FailureAnalysis {
  symbol: string
  generated_at: string
  severity: FailureAnalysisSeverity
  headline: string
  sample_count: number
  high_deviation_count: number
  direction_miss_count: number
  interval_miss_count: number
  avg_error_pct: number | null
  avg_signed_bias_pct: number | null
  root_causes: FailureRootCause[]
  coverage_notes: string[]
  next_actions: string[]
  quality_snapshot: {
    quality_grade: PredictionQualityGrade | null
    quality_score: number | null
    confidence_level: PredictionQualityConfidence | null
  }
  disclaimer: string
  lookback_days?: number
  availability?: PredictionEvaluationAvailability
  feature_snapshot?: FeatureSnapshot
}

export interface AgentReviewAction {
  type: string
  label: string
  priority: 'none' | FailureAnalysisSeverity
  rationale: string
  guardrail: string
  requires_approval: boolean
  requires_gate_pass?: boolean
}

export interface AgentVerificationCheck {
  check_id: string
  review_id: string
  check_type: string
  status: 'passed' | 'warning' | 'failed' | string
  message: string
  evidence: Record<string, any>
}

export interface AgentGateResult {
  status: 'candidate_allowed' | 'observation_only' | 'blocked' | 'waiting_for_samples' | string
  next_state: string
  failed_checks: string[]
  warning_checks: string[]
  blocked_actions: string[]
  message: string
}

export interface AgentReview {
  review_id: string
  symbol: string
  generated_at: string
  status: 'pending_gate' | 'waiting_for_samples' | string
  priority: 'none' | FailureAnalysisSeverity
  headline: string
  evidence: string[]
  proposed_actions: AgentReviewAction[]
  blocked_actions: string[]
  requires_human_review: boolean
  requires_gate_pass?: boolean
  verification_status?: 'passed' | 'warning' | 'failed' | 'pending' | string
  verification_checks?: AgentVerificationCheck[]
  gate_result?: AgentGateResult
  source: string
  disclaimer: string
  lookback_days?: number
  availability?: PredictionEvaluationAvailability
}

export async function fetchPredictionHistory(
  symbol: string,
  opts: { lookbackDays?: number; refresh?: boolean } = {},
): Promise<PredictionHistoryResponse> {
  const params = new URLSearchParams({ symbol, lookback_days: String(opts.lookbackDays ?? 60) })
  if (opts.refresh === false) params.set('refresh', '0')
  return jfetch<PredictionHistoryResponse>(`/api/predictions/history?${params.toString()}`)
}

export async function fetchPredictionQuality(
  symbol: string,
  opts: { lookbackDays?: number; refresh?: boolean } = {},
): Promise<PredictionQuality> {
  const params = new URLSearchParams({ lookback_days: String(opts.lookbackDays ?? 60) })
  if (opts.refresh === false) params.set('refresh', '0')
  return jfetch<PredictionQuality>(`/api/stocks/${encodeURIComponent(symbol)}/prediction-quality?${params.toString()}`)
}

export async function fetchFailureAnalysis(
  symbol: string,
  opts: { lookbackDays?: number; refresh?: boolean } = {},
): Promise<FailureAnalysis> {
  const params = new URLSearchParams({ lookback_days: String(opts.lookbackDays ?? 60) })
  if (opts.refresh === false) params.set('refresh', '0')
  return jfetch<FailureAnalysis>(`/api/stocks/${encodeURIComponent(symbol)}/failure-analysis?${params.toString()}`)
}

export async function fetchAgentReview(
  symbol: string,
  opts: { lookbackDays?: number; refresh?: boolean } = {},
): Promise<AgentReview> {
  const params = new URLSearchParams({ lookback_days: String(opts.lookbackDays ?? 60) })
  if (opts.refresh === false) params.set('refresh', '0')
  return jfetch<AgentReview>(`/api/stocks/${encodeURIComponent(symbol)}/agent-review?${params.toString()}`)
}

/** AI 量化引擎洞察数据 */
export interface StockInsightResponse {
  symbol: string
  has_data: boolean
  prediction: {
    direction_prob_up: number | null
    direction_prob_down: number | null
    predicted_return: number | null
    confidence: number | null
    predict_date: string | null
    target_date: string | null
    horizon: string | null
  } | null
  signal: {
    action: string | null
    score: number | null
    risk_score: number | null
    signal_date: string | null
  } | null
  factors: Record<string, number>
  feature_importance: Array<{ feature: string; importance: number }>
  model_accuracy: number | null
  model_metrics: Record<string, any>
  explanations: string[]
  factor_context?: FactorContext | null
  feature_snapshot?: FeatureSnapshot | null
  trade_decision?: TradeDecision | null
}

export interface FactorContextNewsHeadline {
  title: string
  published_at: string | null
  sentiment_type: string | null
  sentiment_score: number | null
  category: string | null
}

export interface FactorContext {
  symbol: string
  generated_at: string
  news: {
    symbol: string
    window_days: number
    article_count: number
    avg_sentiment: number | null
    sentiment_label: string
    positive_count: number
    negative_count: number
    neutral_count: number
    latest_published_at: string | null
    top_categories: Array<{ category: string; count: number }>
    top_keywords: Array<{ keyword: string; count: number }>
    headlines: FactorContextNewsHeadline[]
  }
  macro: {
    trade_date: string | null
    breadth_label: string
    breadth_ratio: number | null
    avg_pct_chg: number | null
    up_count: number
    down_count: number
    flat_count: number
    total: number
  }
  quant_factors: Array<{
    key: string
    label: string
    value: number
    normalized: number
    impact: string
  }>
  summary: string[]
  warnings: string[]
  disclaimer: string
}

export interface FeatureSnapshotCoverageItem {
  label: string
  available: boolean
  detail: string
}

export interface FeatureSnapshot {
  snapshot_id: string
  symbol: string
  generated_at: string
  as_of_date: string | null
  source: string
  prediction: {
    predict_date: string | null
    target_date: string | null
    horizon: string | null
    direction_prob_up: number | null
    predicted_return: number | null
    confidence: number | null
  } | null
  signal: {
    signal_date: string | null
    action: string | null
    score: number | null
    risk_score: number | null
    rank: number | null
  } | null
  price: {
    trade_date: string | null
    close: number | null
    pct_chg: number | null
    vol: number | null
    amount: number | null
  } | null
  factor_context: FactorContext | null
  factor_counts: {
    news_articles: number
    market_breadth_total: number
    quant_factors: number
  }
  model_metrics: Record<string, any>
  coverage: FeatureSnapshotCoverageItem[]
  completeness_score: number
  lineage: Record<string, string | null>
  warnings: string[]
  disclaimer: string
}

export type TradeSignal = 'strong_buy' | 'buy' | 'hold' | 'sell' | 'strong_sell'
export type TradeRiskLevel = 'low' | 'medium' | 'high' | 'extreme'

export interface TradeDecisionReason {
  type: 'price_prediction' | 'technical' | 'news_sentiment' | 'macro' | 'sector' | 'risk' | 'model_history' | string
  label: string
  evidence: string
  weight: number
}

export interface TradeDecision {
  stock_code: string
  signal: TradeSignal
  signal_label: string
  confidence: number
  risk_level: TradeRiskLevel
  risk_score: number | null
  expected_return: number | null
  expected_downside: number | null
  risk_reward_ratio: number | null
  suggested_position_pct: {
    min: number
    max: number
    label: string
  }
  stop_loss_price: number | null
  take_profit_price: number | null
  invalidation_condition: string
  applicable_horizon: string
  reasons: TradeDecisionReason[]
  source: string
  generated_at: string
  disclaimer: string
}

export async function fetchStockInsight(symbol: string): Promise<StockInsightResponse> {
  return jfetch<StockInsightResponse>(`/api/report/${encodeURIComponent(symbol)}/insight`)
}

export async function fetchTradeDecision(symbol: string): Promise<TradeDecision> {
  return jfetch<TradeDecision>(`/api/stocks/${encodeURIComponent(symbol)}/trade-decision`)
}

export async function fetchFeatureSnapshot(symbol: string): Promise<FeatureSnapshot> {
  return jfetch<FeatureSnapshot>(`/api/stocks/${encodeURIComponent(symbol)}/feature-snapshot`)
}

export interface DecisionRecommendation {
  rank: number
  symbol: string
  name: string
  sector: string | null
  market: string | null
  decision_signal: TradeSignal | string | null
  decision_label: string | null
  dashboard_label: string
  confidence: number | null
  composite_score: number
  expected_return: number | null
  risk_level: TradeRiskLevel | string | null
  risk_score: number | null
  latest_price: number | null
  price_change_pct: number | null
  price_date: string | null
  signal_date: string | null
  prediction_target_date: string | null
  quality_grade: PredictionQualityGrade | null
  quality_label: string | null
  quality_score: number | null
  sample_count: number | null
  data_completeness: number | null
  news_article_count: number
  macro_breadth_label: string | null
  reasons: TradeDecisionReason[]
  warnings: string[]
  trade_decision: TradeDecision
  diagnostics?: Record<string, any>
}

export interface DecisionSummarySelectedStock {
  symbol: string
  name: string
  sector: string | null
  market: string | null
  latest_price: number | null
  price_change_pct: number | null
  price_date: string | null
  trade_decision: TradeDecision
  prediction_quality: PredictionQuality | null
  prediction_summary: PredictionEvaluationSummary | null
  prediction_availability: PredictionEvaluationAvailability | null
  deviation_cases: PredictionDeviationCase[]
  failure_analysis: FailureAnalysis
  agent_review: AgentReview
  feature_snapshot: FeatureSnapshot | null
  factor_context: FactorContext | null
}

export interface DecisionSummaryQualitySummary {
  average_quality_score: number | null
  usable_count: number
  watch_count: number
  risk_count: number
  unknown_count: number
}

export interface DecisionSummaryModelReview {
  headline: string | null
  severity?: FailureAnalysisSeverity | string | null
  gate_status: string
  verification_status: string
  next_actions: string[]
  blocked_actions: string[]
}

export interface DecisionSummaryOptimizationItem {
  type: string
  priority: 'low' | 'medium' | 'high' | string
  title: string
  detail: string
}

export interface DecisionSummaryDataHealth {
  source: string
  requested_count: number
  returned_count: number
  with_signal: number
  with_prediction: number
  with_price: number
  missing_news_count: number
  weak_quality_count: number
  warnings: string[]
}

export interface DecisionDashboardSummary {
  generated_at: string
  scope: {
    symbol: string | null
    limit: number
    lookback_days: number
    pinned_only: boolean
    refresh: boolean
  }
  recommendations: DecisionRecommendation[]
  selected_stock: DecisionSummarySelectedStock | null
  prediction_quality_summary: DecisionSummaryQualitySummary
  model_review_summary: DecisionSummaryModelReview
  optimization_plan: DecisionSummaryOptimizationItem[]
  data_health: DecisionSummaryDataHealth
  disclaimer: string
}

export async function fetchDecisionSummary(opts: {
  symbol?: string
  limit?: number
  lookbackDays?: number
  pinnedOnly?: boolean
  refresh?: boolean
} = {}): Promise<DecisionDashboardSummary> {
  const params = new URLSearchParams()
  if (opts.symbol) params.set('symbol', opts.symbol)
  if (opts.limit != null) params.set('limit', String(opts.limit))
  if (opts.lookbackDays != null) params.set('lookback_days', String(opts.lookbackDays))
  if (opts.pinnedOnly != null) params.set('pinned_only', String(opts.pinnedOnly))
  if (opts.refresh != null) params.set('refresh', String(opts.refresh))
  const query = params.toString()
  return jfetch<DecisionDashboardSummary>(`${API_ENDPOINTS.DASHBOARD.DECISION_SUMMARY}${query ? `?${query}` : ''}`)
}
