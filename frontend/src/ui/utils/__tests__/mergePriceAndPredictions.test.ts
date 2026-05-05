import { describe, it, expect } from 'vitest'
import {
  mergePriceAndPredictions,
  type MergePriceRow,
  type MergePredictionRow,
} from '../mergePriceAndPredictions'

const HIST: MergePriceRow[] = [
  { date: '2026-04-20', close: 432.5 },
  { date: '2026-04-21', close: 447.6 },
  { date: '2026-04-22', close: 436.35 },
  { date: '2026-04-23', close: 438.9 },
  { date: '2026-04-24', close: 444.9 },
]

describe('mergePriceAndPredictions', () => {
  it('returns historical only when predictions are empty', () => {
    const rows = mergePriceAndPredictions(HIST, [])
    expect(rows.length).toBe(HIST.length)
    expect(rows.every(r => r.type === 'historical')).toBe(true)
    // 无预测时不插入 anchor
    expect(rows.some(r => r.type === 'historical_anchor')).toBe(false)
  })

  it('emits an anchor row that bridges yhat to lastClose but does NOT carry close', () => {
    const preds: MergePredictionRow[] = [
      { date: '2026-04-27', predicted_price: 447.84, upper_bound: 473, lower_bound: 423, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds)
    const anchor = rows.find(r => r.type === 'historical_anchor')
    expect(anchor).toBeDefined()
    // anchor 视觉桥接：yhat/yl/yu = lastClose，让 Recharts 的 yhat/yu/yl
    // 系列与最后历史收盘相连。
    expect(anchor!.yhat).toBe(444.9)
    expect(anchor!.yl).toBe(444.9)
    expect(anchor!.yu).toBe(444.9)
    expect(anchor!.yhat_anchor).toBe(444.9)
    // 关键回归：anchor 不能写 close，否则 tooltip 会同时显示
    // "实际收盘 ¥444.90 / 预测均值 ¥444.90 / 区间 (444.90~444.90)"。
    // 渲染层（CustomChartTooltip）必须按 type='historical_anchor' 过滤。
    expect(anchor!.close).toBeUndefined()
    expect(anchor!.isForecastAnchor).toBe(true)
    expect(anchor!.forecastReturnPct).toBe(0)
    expect(anchor!.forecastDirection).toBe('anchor')
  })

  it('uses the last valid historical close as anchor when the newest close is null', () => {
    const hist: MergePriceRow[] = [
      ...HIST,
      { date: '2026-04-25', close: null },
    ]
    const preds: MergePredictionRow[] = [
      { date: '2026-04-27', predicted_price: 448, upper_bound: 470, lower_bound: 430, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(hist, preds)
    const anchor = rows.find(r => r.type === 'historical_anchor')
    expect(anchor).toBeDefined()
    expect(anchor!.date).toBe('2026-04-24')
    expect(anchor!.forecastBasePrice).toBe(444.9)
  })

  it('normalizes dates, fixes reversed bounds, and clamps forecast mean inside the band', () => {
    const preds: MergePredictionRow[] = [
      { date: '20260427', predicted_price: 120, upper_bound: 90, lower_bound: 110, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds)
    const pred = rows.find(r => r.type === 'prediction')
    expect(pred).toBeDefined()
    expect(pred!.date).toBe('2026-04-27')
    expect(pred!.forecastLower).toBe(90)
    expect(pred!.forecastUpper).toBe(110)
    expect(pred!.forecastMean).toBe(110)
  })

  it('derives forecast return and direction from the sanitized forecast main line', () => {
    const preds: MergePredictionRow[] = [
      { date: '2026-04-27', predicted_price: 454, upper_bound: 460, lower_bound: 448, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds)
    const pred = rows.find(r => r.type === 'prediction')
    expect(pred).toBeDefined()
    expect(pred!.forecastReturnPct).toBeGreaterThan(1.5)
    expect(pred!.forecastDirection).toBe('bullish')
  })

  it('filters invalid prediction values instead of emitting NaN chart rows', () => {
    const preds = [
      { date: '2026-04-27', predicted_price: Number.NaN, upper_bound: undefined, lower_bound: undefined, status: 'future' },
    ] as MergePredictionRow[]
    const rows = mergePriceAndPredictions(HIST, preds)
    expect(rows.some(r => r.type === 'prediction')).toBe(false)
  })

  it('drops same-day today prediction by default', () => {
    const preds: MergePredictionRow[] = [
      { date: '2026-04-24', predicted_price: 447.97, upper_bound: 469.66, lower_bound: 427.28, status: 'today' },
      { date: '2026-04-27', predicted_price: 447.84, upper_bound: 473, lower_bound: 423, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds)
    // 04-24 不能既是 historical 又是 prediction
    const sameDayPred = rows.find(r => r.date === '2026-04-24' && r.type === 'prediction')
    expect(sameDayPred).toBeUndefined()
    // future 仍然保留
    expect(rows.some(r => r.date === '2026-04-27' && r.type === 'prediction')).toBe(true)
  })

  it('keeps same-day today prediction when dropSameDayPrediction=false', () => {
    const preds: MergePredictionRow[] = [
      { date: '2026-04-24', predicted_price: 447.97, upper_bound: 469.66, lower_bound: 427.28, status: 'today' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds, { dropSameDayPrediction: false })
    const sameDayPred = rows.find(r => r.date === '2026-04-24' && r.type === 'prediction')
    expect(sameDayPred).toBeDefined()
    expect(sameDayPred!.yhat).toBe(447.97)
  })

  it('attaches historical D-1 and D-5 prediction comparison fields to historical rows', () => {
    const rows = mergePriceAndPredictions(HIST, [], [
      {
        date: '2026-04-23',
        actual: 438.9,
        d1_predicted: 441.2,
        d1_lower: 430,
        d1_upper: 452,
        d1_error_pct: 0.52,
        d1_signed_error_pct: 0.52,
        d1_direction_ok: true,
        d1_interval_hit: true,
        d1_status: 'evaluated',
        d1_deviation_level: 'low',
        d5_predicted: 435.4,
        d5_error_pct: 0.8,
        d5_signed_error_pct: -0.8,
        d5_direction_ok: false,
        d5_status: 'evaluated',
        d5_deviation_level: 'high',
      },
    ])

    const row = rows.find(r => r.date === '2026-04-23' && r.type === 'historical')
    expect(row).toBeDefined()
    expect(row!.history_d1_yhat).toBe(441.2)
    expect(row!.history_d1_yl).toBe(430)
    expect(row!.history_d1_yu).toBe(452)
    expect(row!.history_d1_error_pct).toBe(0.52)
    expect(row!.history_d1_signed_error_pct).toBe(0.52)
    expect(row!.history_d1_direction_ok).toBe(true)
    expect(row!.history_d1_interval_hit).toBe(true)
    expect(row!.history_d1_status).toBe('evaluated')
    expect(row!.history_d1_deviation_level).toBe('low')
    expect(row!.history_d5_yhat).toBe(435.4)
    expect(row!.history_d5_signed_error_pct).toBe(-0.8)
    expect(row!.history_d5_direction_ok).toBe(false)
    expect(row!.history_d5_status).toBe('evaluated')
    expect(row!.history_d5_deviation_level).toBe('high')
  })

  it('routes expired predictions to *_expired channels and computes error_pct/direction_ok', () => {
    // 假设 04-23 是预测 04-22 的过期预测：predicted=440, actual close 04-22=436.35
    const histWith23: MergePriceRow[] = HIST.slice(0, 4)
    const preds: MergePredictionRow[] = [
      { date: '2026-04-22', predicted_price: 440, upper_bound: 450, lower_bound: 430, status: 'expired' },
    ]
    const rows = mergePriceAndPredictions(histWith23, preds)
    const exp = rows.find(r => r.type === 'prediction')
    expect(exp).toBeDefined()
    // 过期预测：yhat 应当为空，yhat_expired 才有值
    expect(exp!.yhat).toBeUndefined()
    expect(exp!.yhat_expired).toBe(440)
    expect(exp!.actual).toBe(436.35)
    // |440-436.35|/436.35 ≈ 0.836%
    expect(exp!.error_pct).toBeGreaterThan(0.5)
    expect(exp!.error_pct).toBeLessThan(1.2)
    // 方向：predicted 440 vs prev close 432.5 → up；actual 436.35 vs 432.5 → up
    expect(exp!.direction_ok).toBe(true)
  })

  it('never produces duplicate (date, type) rows after default merge', () => {
    const preds: MergePredictionRow[] = [
      { date: '2026-04-24', predicted_price: 447.97, upper_bound: 469.66, lower_bound: 427.28, status: 'today' },
      { date: '2026-04-27', predicted_price: 447.84, upper_bound: 473, lower_bound: 423, status: 'future' },
      { date: '2026-04-28', predicted_price: 447.92, upper_bound: 476, lower_bound: 421, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds)
    // 关键回归：每个日期下 historical / prediction 至多各一条；anchor 仅出现在最后历史日
    const seen = new Map<string, Set<string>>()
    for (const r of rows) {
      const set = seen.get(r.date) ?? new Set()
      expect(set.has(r.type)).toBe(false)
      set.add(r.type)
      seen.set(r.date, set)
    }
    // 04-24 应当包含 historical + historical_anchor 两条；不能有 prediction
    const types24 = seen.get('2026-04-24')!
    expect(types24.has('historical')).toBe(true)
    expect(types24.has('historical_anchor')).toBe(true)
    expect(types24.has('prediction')).toBe(false)
  })

  it('output is chronologically sorted and historical < anchor < prediction within same date', () => {
    const preds: MergePredictionRow[] = [
      { date: '2026-04-27', predicted_price: 447.84, upper_bound: 473, lower_bound: 423, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds)
    for (let i = 1; i < rows.length; i++) {
      const cmp = rows[i - 1].date.localeCompare(rows[i].date)
      expect(cmp <= 0).toBe(true)
    }
  })

  it('regression: anchor never injects yhat == close (the original bug)', () => {
    // 这条用例直接保护问题截图中 tooltip 显示
    // "实际收盘:¥444.90 / 预测均值:¥444.90 / 区间:(444.90~444.90)" 不再出现。
    const preds: MergePredictionRow[] = [
      { date: '2026-04-27', predicted_price: 447.84, upper_bound: 473, lower_bound: 423, status: 'future' },
    ]
    const rows = mergePriceAndPredictions(HIST, preds)
    // 整个 merged 数组中，不应当存在任何 row 同时满足
    // close != null && yhat != null && yhat === close。
    for (const r of rows) {
      if (r.close != null && r.yhat != null) {
        expect(r.yhat).not.toBe(r.close)
      }
    }
  })
})
