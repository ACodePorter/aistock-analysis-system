/**
 * mergePriceAndPredictions
 *
 * 把后端 /api/report/{sym}/full 返回的 price_data 与 predictions 合并成
 * 主图 ComposedChart 直接消费的 row 数组，并保证：
 *
 *   1. 同一交易日在结果数组中只出现一次（除了 anchor 行，见下）。
 *   2. "桥接 / anchor" 行只承载视觉连接职责（yhat_anchor），不写 close /
 *      yhat / yl / yu，避免污染收盘曲线、预测线与区间带，避免 tooltip /
 *      legend 把 anchor 当成真实预测。
 *   3. predictions 列表中如果包含与最后历史交易日同日的 today 点（盘后
 *      重复样本），由调用方默认丢弃；保留 future / expired。
 *   4. 输出按日期升序排序。
 *
 * 该函数为纯函数（无副作用、不读外部状态），便于单测覆盖前端图表的核心
 * 数据契约，避免再次出现 "预测均值 == 收盘" 的视觉错觉。
 */

export type MergeRowType = 'historical' | 'historical_anchor' | 'prediction'
export type ForecastDirection = 'bullish' | 'bearish' | 'sideways' | 'anchor'

export interface MergePriceRow {
  date: string
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
  volume?: number
  pct_change?: number
  type?: 'historical'
}

export interface MergePredictionRow {
  date: string
  predicted_price?: number | null
  predictedMean?: number | null
  predictedClose?: number | null
  forecastMean?: number | null
  forecastPrice?: number | null
  mean?: number | null
  avg?: number | null
  upper_bound?: number | null
  lower_bound?: number | null
  predictedUpper?: number | null
  predictedLower?: number | null
  forecastUpper?: number | null
  forecastLower?: number | null
  upper?: number | null
  lower?: number | null
  status?: string
  direction_snr?: number
  direction_grade?: string
  signal_level?: string
}

export interface HistoricalPredictionRow {
  date: string
  actual?: number | null
  d1_predicted?: number | null
  d1_lower?: number | null
  d1_upper?: number | null
  d1_error_pct?: number | null
  d1_signed_error_pct?: number | null
  d1_direction_ok?: boolean | null
  d1_interval_hit?: boolean | null
  d1_status?: string | null
  d1_deviation_level?: string | null
  d5_predicted?: number | null
  d5_lower?: number | null
  d5_upper?: number | null
  d5_error_pct?: number | null
  d5_signed_error_pct?: number | null
  d5_direction_ok?: boolean | null
  d5_interval_hit?: boolean | null
  d5_status?: string | null
  d5_deviation_level?: string | null
}

export interface MergedRow {
  date: string
  type: MergeRowType
  // 历史
  close?: number | null
  // 预测（有效）
  yhat?: number | null
  yl?: number | null
  yu?: number | null
  forecastMean?: number | null
  forecastLower?: number | null
  forecastUpper?: number | null
  // 预测（已过期）
  yhat_expired?: number | null
  yl_expired?: number | null
  yu_expired?: number | null
  forecastMeanExpired?: number | null
  forecastLowerExpired?: number | null
  forecastUpperExpired?: number | null
  // 视觉锚点：只用于让收盘线与预测线在最后历史日视觉相连，
  // 不进入 tooltip / legend 的"预测均值"语义
  yhat_anchor?: number | null
  isForecastAnchor?: boolean
  forecastBasePrice?: number | null
  forecastReturnPct?: number | null
  forecastDirection?: ForecastDirection
  // 评估辅助
  actual?: number | null
  error_pct?: number
  direction_ok?: boolean
  status?: string
  predictionStatus?: string
  direction_grade?: string
  direction_snr?: number
  signal_level?: string
  // 历史预测复盘线（同一个 target_date 上的实际收盘 vs 旧预测）
  history_d1_yhat?: number | null
  history_d1_yl?: number | null
  history_d1_yu?: number | null
  history_d1_error_pct?: number | null
  history_d1_signed_error_pct?: number | null
  history_d1_direction_ok?: boolean | null
  history_d1_interval_hit?: boolean | null
  history_d1_status?: string | null
  history_d1_deviation_level?: string | null
  history_d5_yhat?: number | null
  history_d5_yl?: number | null
  history_d5_yu?: number | null
  history_d5_error_pct?: number | null
  history_d5_signed_error_pct?: number | null
  history_d5_direction_ok?: boolean | null
  history_d5_interval_hit?: boolean | null
  history_d5_status?: string | null
  history_d5_deviation_level?: string | null
}

export interface MergeOptions {
  /**
   * 是否插入一个 anchor 行，让前端把"收盘线最后一点"和"预测线第一点"
   * 在视觉上连起来。默认 true。
   * Anchor 行只写 yhat_anchor，不写 yhat/yl/yu/close。
   */
  includeAnchor?: boolean
  /**
   * 是否过滤掉与最后历史日同日的 today 预测点。默认 true。
   * 这避免了"同一日期既画 historical close 又画 today prediction"导致
   * tooltip / legend 出现 "预测均值 == 收盘价" 的错觉。
   */
  dropSameDayPrediction?: boolean
}

const DEFAULT_OPTIONS: Required<MergeOptions> = {
  includeAnchor: true,
  dropSameDayPrediction: true,
}

const BULLISH_THRESHOLD = 0.015
const BEARISH_THRESHOLD = 0.015

function dirOf(a: number, b: number): 1 | -1 {
  return a >= b ? 1 : -1
}

function normalizeDate(value: unknown): string | null {
  if (value == null) return null
  if (value instanceof Date && Number.isFinite(value.getTime())) return value.toISOString().slice(0, 10)
  const raw = String(value).trim()
  const m = raw.match(/^(\d{4})[-/]?(\d{2})[-/]?(\d{2})/)
  if (!m) return null
  return `${m[1]}-${m[2]}-${m[3]}`
}

function toFiniteNumber(value: unknown): number | null {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function firstFinite(...values: unknown[]): number | null {
  for (const value of values) {
    const n = toFiniteNumber(value)
    if (n != null) return n
  }
  return null
}

function clamp(value: number, lower: number, upper: number): number {
  return Math.min(Math.max(value, lower), upper)
}

function estimateVolatility(hist: MergePriceRow[]): number {
  const closes = hist
    .map(p => toFiniteNumber(p.close))
    .filter((v): v is number => v != null && v > 0)
  const returns: number[] = []
  for (let i = 1; i < closes.length; i++) {
    returns.push((closes[i] - closes[i - 1]) / closes[i - 1])
  }
  const sample = returns.slice(-20)
  if (sample.length < 2) return 0.015
  const mean = sample.reduce((sum, v) => sum + v, 0) / sample.length
  const variance = sample.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / (sample.length - 1)
  return clamp(Math.sqrt(variance), 0.005, 0.08)
}

function directionFromReturn(ret: number | null): ForecastDirection | undefined {
  if (ret == null) return undefined
  if (ret > BULLISH_THRESHOLD) return 'bullish'
  if (ret < -BEARISH_THRESHOLD) return 'bearish'
  return 'sideways'
}

function sanitizeForecast(pred: MergePredictionRow, fallbackVolatility: number, stepIndex: number) {
  const meanRaw = firstFinite(
    pred.predicted_price,
    pred.predictedMean,
    pred.predictedClose,
    pred.forecastMean,
    pred.forecastPrice,
    pred.mean,
    pred.avg,
  )
  let lower = firstFinite(pred.lower_bound, pred.predictedLower, pred.forecastLower, pred.lower)
  let upper = firstFinite(pred.upper_bound, pred.predictedUpper, pred.forecastUpper, pred.upper)

  let mean = meanRaw
  if (mean == null && lower != null && upper != null) mean = (lower + upper) / 2
  if (mean == null || mean <= 0) return null

  if (lower == null && upper == null) {
    const bandPct = clamp(1.28 * fallbackVolatility * Math.sqrt(stepIndex + 1), 0.008, 0.18)
    lower = mean * (1 - bandPct)
    upper = mean * (1 + bandPct)
  } else if (lower == null && upper != null) {
    lower = Math.max(0, mean - Math.abs(upper - mean))
  } else if (upper == null && lower != null) {
    upper = mean + Math.abs(mean - lower)
  }

  if (lower == null || upper == null) return null
  if (upper < lower) [lower, upper] = [upper, lower]
  if (upper === lower && upper !== mean) {
    lower = mean
    upper = mean
  }
  mean = clamp(mean, lower, upper)
  return { mean, lower, upper }
}

/**
 * 把 priceData / predictions 合并成图表 row 数组。
 *
 * @param priceData    历史价格数组（来自 ReportResp.price_data，已按 timeRange 切片）
 * @param predictions  预测数组（来自 ReportResp.predictions）
 * @param options      合并选项
 */
export function mergePriceAndPredictions(
  priceData: MergePriceRow[] | undefined,
  predictions: MergePredictionRow[] | undefined,
  historicalPredictionsOrOptions: HistoricalPredictionRow[] | MergeOptions | undefined = undefined,
  options: MergeOptions = {},
): MergedRow[] {
  const historicalPredictions = Array.isArray(historicalPredictionsOrOptions)
    ? historicalPredictionsOrOptions
    : undefined
  const mergeOptions = Array.isArray(historicalPredictionsOrOptions)
    ? options
    : (historicalPredictionsOrOptions ?? options)
  const opts: Required<MergeOptions> = { ...DEFAULT_OPTIONS, ...mergeOptions }

  const out: MergedRow[] = []
  const rawHist = Array.isArray(priceData) ? priceData : []
  const preds = Array.isArray(predictions) ? predictions : []
  const histByDate = new Map<string, MergePriceRow>()
  for (const p of rawHist) {
    const date = normalizeDate(p.date)
    if (!date) continue
    histByDate.set(date, { ...p, date, close: toFiniteNumber(p.close) })
  }
  const hist = Array.from(histByDate.values()).sort((a, b) => a.date.localeCompare(b.date))
  const historyByDate = new Map<string, HistoricalPredictionRow>()
  for (const row of Array.isArray(historicalPredictions) ? historicalPredictions : []) {
    const date = normalizeDate(row.date)
    if (date) historyByDate.set(date, { ...row, date })
  }

  // 历史价格 → close 系列
  for (const p of hist) {
    const history = historyByDate.get(p.date)
    out.push({
      date: p.date,
      close: p.close ?? null,
      type: 'historical',
      history_d1_yhat: history?.d1_predicted ?? undefined,
      history_d1_yl: history?.d1_lower ?? undefined,
      history_d1_yu: history?.d1_upper ?? undefined,
      history_d1_error_pct: history?.d1_error_pct ?? undefined,
      history_d1_signed_error_pct: history?.d1_signed_error_pct ?? undefined,
      history_d1_direction_ok: history?.d1_direction_ok ?? undefined,
      history_d1_interval_hit: history?.d1_interval_hit ?? undefined,
      history_d1_status: history?.d1_status ?? undefined,
      history_d1_deviation_level: history?.d1_deviation_level ?? undefined,
      history_d5_yhat: history?.d5_predicted ?? undefined,
      history_d5_yl: history?.d5_lower ?? undefined,
      history_d5_yu: history?.d5_upper ?? undefined,
      history_d5_error_pct: history?.d5_error_pct ?? undefined,
      history_d5_signed_error_pct: history?.d5_signed_error_pct ?? undefined,
      history_d5_direction_ok: history?.d5_direction_ok ?? undefined,
      history_d5_interval_hit: history?.d5_interval_hit ?? undefined,
      history_d5_status: history?.d5_status ?? undefined,
      history_d5_deviation_level: history?.d5_deviation_level ?? undefined,
    })
  }

  if (hist.length === 0 || preds.length === 0) {
    return out.sort((a, b) => a.date.localeCompare(b.date))
  }

  const lastHistorical = hist.slice().reverse().find(p => toFiniteNumber(p.close) != null)
  if (!lastHistorical) {
    return out.sort((a, b) => a.date.localeCompare(b.date))
  }
  const lastDate = lastHistorical.date
  const lastClose = toFiniteNumber(lastHistorical.close)
  const fallbackVolatility = estimateVolatility(hist)

  // 价格查找表：用于计算过期预测点的 actual / error_pct / direction_ok
  const priceMap = new Map<string, number>()
  // 已排序的 (date, close) 列表，用于二分查找"前一交易日收盘"
  const histDates: string[] = []
  const histCloses: number[] = []
  const sortedHist = hist
    .filter(p => p.close != null)
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date))
  for (const p of sortedHist) {
    priceMap.set(p.date, Number(p.close))
    histDates.push(p.date)
    histCloses.push(Number(p.close))
  }

  /** 找到严格小于 targetDate 的最后一个历史收盘（前一交易日基准）。 */
  const closeBefore = (targetDate: string): number | undefined => {
    let lo = 0
    let hi = histDates.length - 1
    let ans = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (histDates[mid] < targetDate) {
        ans = mid
        lo = mid + 1
      } else {
        hi = mid - 1
      }
    }
    return ans >= 0 ? histCloses[ans] : undefined
  }

  // 视觉 anchor：写入 yhat/yl/yu = lastClose，让"预测均值"系列与收盘线
  // 在最后历史日视觉相连。anchor 行不写 close，并通过 type='historical_anchor'
  // 让 tooltip 严格过滤这一行；这样 legend 不变，tooltip 也不会出现
  // "实际收盘 / 预测均值 / 区间 数值都相同" 的视觉错觉。
  if (opts.includeAnchor && lastClose != null) {
    out.push({
      date: lastDate,
      type: 'historical_anchor',
      yhat: lastClose,
      yl: lastClose,
      yu: lastClose,
      forecastMean: lastClose,
      forecastLower: lastClose,
      forecastUpper: lastClose,
      yhat_anchor: lastClose,
      isForecastAnchor: true,
      forecastBasePrice: lastClose,
      forecastReturnPct: 0,
      forecastDirection: 'anchor',
    })
  }

  // 预测点
  let forecastStep = 0
  for (const rawPred of preds) {
    const date = normalizeDate(rawPred.date)
    if (!date) continue
    const pred = { ...rawPred, date }
    const status = pred.status
    const isExpired = status === 'expired'

    // 同日 today 预测：默认丢弃（避免与 historical close 在同一 X 轴位置叠加）。
    // today_evaluated 是后端 Phase 1 修复后给同日预测打的新状态，前端同样丢弃。
    if (
      opts.dropSameDayPrediction &&
      pred.date === lastDate &&
      (status === 'today' || status === 'today_evaluated')
    ) {
      continue
    }

    const actualClose = priceMap.get(pred.date)
    let errorPct: number | undefined = undefined
    let directionOk: boolean | undefined = undefined
    const prevClose = closeBefore(pred.date)
    const sanitized = sanitizeForecast(pred, fallbackVolatility, forecastStep)
    if (!sanitized) continue
    const { mean, lower, upper } = sanitized
    const forecastReturnPct = lastClose != null && lastClose > 0 ? ((mean - lastClose) / lastClose) * 100 : null
    const forecastDirection = directionFromReturn(forecastReturnPct != null ? forecastReturnPct / 100 : null)

    if (
      isExpired &&
      actualClose !== undefined &&
      prevClose != null
    ) {
      errorPct = (Math.abs(mean - actualClose) / actualClose) * 100
      directionOk = dirOf(mean, prevClose) === dirOf(actualClose, prevClose)
    }

    out.push({
      date: pred.date,
      type: 'prediction',
      yhat: isExpired ? undefined : mean,
      yl: isExpired ? undefined : lower,
      yu: isExpired ? undefined : upper,
      forecastMean: isExpired ? undefined : mean,
      forecastLower: isExpired ? undefined : lower,
      forecastUpper: isExpired ? undefined : upper,
      yhat_expired: isExpired ? mean : undefined,
      yl_expired: isExpired ? lower : undefined,
      yu_expired: isExpired ? upper : undefined,
      forecastMeanExpired: isExpired ? mean : undefined,
      forecastLowerExpired: isExpired ? lower : undefined,
      forecastUpperExpired: isExpired ? upper : undefined,
      actual: actualClose,
      error_pct: errorPct,
      direction_ok: directionOk,
      status: status ?? 'future',
      predictionStatus: status ?? 'future',
      direction_grade: pred.direction_grade,
      direction_snr: pred.direction_snr,
      signal_level: pred.signal_level,
      forecastBasePrice: lastClose,
      forecastReturnPct,
      forecastDirection,
    })
    forecastStep += 1
  }

  return out.sort((a, b) => {
    if (a.date === b.date) {
      // 同日内 anchor 排在 historical 之后、prediction 之前，便于调试
      const order: Record<MergeRowType, number> = {
        historical: 0,
        historical_anchor: 1,
        prediction: 2,
      }
      return order[a.type] - order[b.type]
    }
    return a.date.localeCompare(b.date)
  })
}
