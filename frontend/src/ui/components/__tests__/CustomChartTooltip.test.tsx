import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CustomChartTooltip } from '../CustomChartTooltip'

// 构造 Recharts 把 tooltip payload 传进来时的形态：每个 series 的 .payload
// 都指向同一行（同一日期）的 merged row。
const mkPayload = (rows: any[]) => rows.map(r => ({ payload: r, value: r.close ?? r.yhat ?? null }))

describe('CustomChartTooltip', () => {
  it('renders nothing when inactive', () => {
    const { container } = render(<CustomChartTooltip active={false} payload={mkPayload([{ date: '2026-04-24', close: 100, type: 'historical' }])} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows only 实际收盘 on a pure historical date', () => {
    render(<CustomChartTooltip active payload={mkPayload([
      { date: '2026-04-23', close: 438.9, type: 'historical' },
    ])} />)
    expect(screen.getByText('2026-04-23')).toBeInTheDocument()
    expect(screen.getByText('实际收盘:')).toBeInTheDocument()
    expect(screen.getByText('¥438.90')).toBeInTheDocument()
    expect(screen.queryByText('预测主线:')).toBeNull()
    expect(screen.queryByText('区间:')).toBeNull()
  })

  it('regression: ignores historical_anchor row so 预测均值 != 收盘价 on last historical date', () => {
    // 这是 2026-04-24 截图上的真实场景：tooltip 同时给到 historical 和 anchor 两行，
    // 旧实现 payload[0].payload 取到 anchor，导致显示 "实际收盘 ¥444.90 / 预测均值 ¥444.90 / 区间(444.90~444.90)"。
    render(<CustomChartTooltip active payload={mkPayload([
      { date: '2026-04-24', close: 444.9, type: 'historical' },
      { date: '2026-04-24', yhat: 444.9, yl: 444.9, yu: 444.9, yhat_anchor: 444.9, type: 'historical_anchor' },
    ])} />)
    expect(screen.getByText('¥444.90')).toBeInTheDocument()
    // 关键回归：tooltip 不能再出现"预测主线 / 区间"任何一行，但应解释这是预测起点
    expect(screen.queryByText('预测主线:')).toBeNull()
    expect(screen.queryByText('区间:')).toBeNull()
    expect(screen.getByText(/预测起点/)).toBeInTheDocument()
    expect(screen.getByText(/不参与未来收益统计/)).toBeInTheDocument()
  })

  it('shows historical close + future prediction when both rows exist', () => {
    render(<CustomChartTooltip active payload={mkPayload([
      { date: '2026-04-27', close: null, type: 'historical' },
      { date: '2026-04-27', yhat: 447.84, yl: 423.96, yu: 473.07, type: 'prediction', predictionStatus: 'future' },
    ])} />)
    expect(screen.getByText('预测主线:')).toBeInTheDocument()
    expect(screen.getByText('¥447.84')).toBeInTheDocument()
    expect(screen.getByText(/区间:/)).toBeInTheDocument()
    expect(screen.getByText(/423\.96/)).toBeInTheDocument()
    expect(screen.getByText(/473\.07/)).toBeInTheDocument()
  })

  it('shows forecast return and direction on a future prediction date', () => {
    render(<CustomChartTooltip active payload={mkPayload([
      {
        date: '2026-04-28',
        forecastMean: 101,
        forecastLower: 98,
        forecastUpper: 104,
        forecastReturnPct: 1.55,
        forecastDirection: 'bullish',
        type: 'prediction',
        predictionStatus: 'future',
      },
    ])} />)
    expect(screen.getByText('预测主线:')).toBeInTheDocument()
    expect(screen.getByText(/相对预测起点:/)).toBeInTheDocument()
    expect(screen.getByText(/\+1\.55%/)).toBeInTheDocument()
    expect(screen.getByText(/方向倾向: 看涨/)).toBeInTheDocument()
    expect(screen.getByText(/类型: 未来预测/)).toBeInTheDocument()
  })

  it('shows expired prediction with 已过期 marker and reads yhat_expired', () => {
    render(<CustomChartTooltip active payload={mkPayload([
      { date: '2026-04-22', close: 436.35, type: 'historical' },
      { date: '2026-04-22', yhat_expired: 440, yl_expired: 430, yu_expired: 450, actual: 436.35, error_pct: 0.836, direction_ok: false, type: 'prediction', predictionStatus: 'expired' },
    ])} />)
    expect(screen.getByText('¥440.00')).toBeInTheDocument()
    expect(screen.getByText('已过期')).toBeInTheDocument()
    expect(screen.getByText('偏差:')).toBeInTheDocument()
    expect(screen.getByText('✗ 错误')).toBeInTheDocument()
  })

  it('shows historical D-1 and D-5 predictions on actual price dates', () => {
    render(<CustomChartTooltip active payload={mkPayload([
      {
        date: '2026-04-23',
        close: 438.9,
        type: 'historical',
        history_d1_yhat: 441.2,
        history_d1_error_pct: 0.52,
        history_d1_signed_error_pct: 0.52,
        history_d1_direction_ok: true,
        history_d1_interval_hit: true,
        history_d5_yhat: 435.4,
        history_d5_error_pct: 0.8,
        history_d5_signed_error_pct: -0.8,
        history_d5_direction_ok: false,
      },
    ])} />)
    expect(screen.getByText('历史预测D-1:')).toBeInTheDocument()
    expect(screen.getByText('¥441.20')).toBeInTheDocument()
    expect(screen.getByText('方向对')).toBeInTheDocument()
    expect(screen.getByText('命中区间')).toBeInTheDocument()
    expect(screen.getByText('历史预测D-5:')).toBeInTheDocument()
    expect(screen.getByText('¥435.40')).toBeInTheDocument()
    expect(screen.getByText(/-0\.80%/)).toBeInTheDocument()
    expect(screen.getByText('方向错')).toBeInTheDocument()
  })

  it('shows historical prediction evaluation status when actual is not available yet', () => {
    render(<CustomChartTooltip active payload={mkPayload([
      {
        date: '2026-04-27',
        close: 450,
        type: 'historical',
        history_d1_yhat: 452,
        history_d1_status: 'pending_target_date',
      },
    ])} />)
    expect(screen.getByText('历史预测D-1:')).toBeInTheDocument()
    expect(screen.getByText('等待验证')).toBeInTheDocument()
  })

  it('does not crash on empty payload', () => {
    const { container } = render(<CustomChartTooltip active payload={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('does not crash on payload entries with null payload', () => {
    const { container } = render(<CustomChartTooltip active payload={[{ payload: null }, { payload: undefined }]} />)
    expect(container.firstChild).toBeNull()
  })
})
