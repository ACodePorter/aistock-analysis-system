import React from 'react'
import FloatingModule from './FloatingModule'
import ForecastReview from './ForecastReview'
import WatchlistAnalysis from './WatchlistAnalysis'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips } from '../config/helpTips'

type TimeRange = '5d' | '1m' | '3m' | '6m' | '1y' | 'all'

type MergedPriceRow = {
  date: string
  type?: 'historical' | 'historical_anchor' | 'prediction' | string
  close?: number | null
  actual?: number | null
  forecastBasePrice?: number | null
  forecastMean?: number | null
  forecastMeanExpired?: number | null
  yhat?: number | null
  yhat_expired?: number | null
  forecastLower?: number | null
  forecastLowerExpired?: number | null
  yl?: number | null
  yl_expired?: number | null
  forecastUpper?: number | null
  forecastUpperExpired?: number | null
  yu?: number | null
  yu_expired?: number | null
  predictionStatus?: string
  error_pct?: number | null
  direction_ok?: boolean | null
}

type HomeReviewDetailsSectionProps = {
  timeRange: TimeRange
  merged: MergedPriceRow[]
}

const rangeLabel: Record<TimeRange, string> = {
  '5d': '最近5个工作日',
  '1m': '最近1个月',
  '3m': '最近3个月',
  '6m': '最近6个月',
  '1y': '最近1年',
  all: '全部数据',
}

function formatPrice(value?: number | null): string {
  return value != null ? Number(value).toFixed(2) : '-'
}

function forecastValue(row: MergedPriceRow): number | null | undefined {
  return row.forecastMean ?? row.forecastMeanExpired ?? row.yhat ?? row.yhat_expired
}

function forecastLow(row: MergedPriceRow): number | null | undefined {
  return row.forecastLower ?? row.forecastLowerExpired ?? row.yl ?? row.yl_expired
}

function forecastHigh(row: MergedPriceRow): number | null | undefined {
  return row.forecastUpper ?? row.forecastUpperExpired ?? row.yu ?? row.yu_expired
}

export default function HomeReviewDetailsSection({ timeRange, merged }: HomeReviewDetailsSectionProps) {
  const HeaderCell = ({ children, tip, align = 'left' }: { children: React.ReactNode; tip: keyof typeof helpTips; align?: 'left' | 'right' | 'center' }) => (
    <th style={{padding: '8px 12px', textAlign: align, borderBottom: '1px solid var(--border)', color:'var(--text-muted)'}}>
      <span style={{display:'inline-flex', alignItems:'center', gap:5, justifyContent: align === 'right' ? 'flex-end' : align === 'center' ? 'center' : 'flex-start', width:'100%'}}>
        {children}
        <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>
      </span>
    </th>
  )

  return (
    <>
      <FloatingModule style={{marginTop:12, padding:12, borderRadius:12}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12}}>
          <div style={{fontWeight:600, color:'var(--text)', display:'flex', alignItems:'center', gap:6}}>
            数据详情
            <HelpTooltip {...helpTips.dataDetails}><HelpIcon /></HelpTooltip>
          </div>
          <div style={{fontSize:12, color:'var(--text-muted)'}}>
            显示区间: {rangeLabel[timeRange]} + 未来预测
          </div>
        </div>

        {merged.length > 0 ? (
          <div style={{maxHeight: 300, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8}}>
            <table style={{width: '100%', borderCollapse: 'collapse', fontSize: 12}}>
              <thead style={{background: 'rgba(255,255,255,0.03)', position: 'sticky', top: 0}}>
                <tr>
                  <HeaderCell tip="actualClose">日期</HeaderCell>
                  <HeaderCell tip="actualClose" align="right">实际收盘</HeaderCell>
                  <HeaderCell tip="aiPredictionLine" align="right">预测主线</HeaderCell>
                  <HeaderCell tip="predictionLower" align="right">预测下界</HeaderCell>
                  <HeaderCell tip="predictionUpper" align="right">预测上界</HeaderCell>
                  <HeaderCell tip="mape" align="center">偏差</HeaderCell>
                  <HeaderCell tip="directionAccuracy" align="center">方向</HeaderCell>
                  <HeaderCell tip="historicalPrediction" align="center">类型</HeaderCell>
                </tr>
              </thead>
              <tbody>
                {merged.map((row, idx) => {
                  const isHistorical = row.type === 'historical'
                  const isAnchor = row.type === 'historical_anchor'
                  const isPrediction = row.type === 'prediction'
                  const isExpiredPred = isPrediction && row.predictionStatus === 'expired'
                  const predValue = forecastValue(row)
                  const predLow = forecastLow(row)
                  const predHigh = forecastHigh(row)
                  const hasError = row.error_pct != null
                  const hasDirection = row.direction_ok != null
                  const errorDisplay = hasError ? `${Number(row.error_pct).toFixed(2)}%` : '-'
                  const directionDisplay = hasDirection ? (row.direction_ok ? '✓' : '✗') : '-'
                  const directionColor = row.direction_ok === true ? '#10b981' : row.direction_ok === false ? '#ef4444' : 'var(--text-muted)'

                  return (
                    <tr
                      key={`${row.date}-${idx}`}
                      style={{
                        background: isHistorical
                          ? 'transparent'
                          : (isAnchor ? 'rgba(148, 163, 184, 0.05)' : (isExpiredPred ? 'rgba(156, 163, 175, 0.05)' : 'rgba(99, 102, 241, 0.05)')),
                      }}
                    >
                      <td style={{padding: '6px 12px', borderBottom: '1px solid var(--border)', color:'var(--text)'}}>{row.date}</td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid var(--border)', color:'var(--text)'}}>
                        {isHistorical ? formatPrice(row.close) : (isAnchor ? formatPrice(row.forecastBasePrice) : formatPrice(row.actual))}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid var(--border)', color: isExpiredPred ? '#9ca3af' : 'var(--text)'}}>
                        {(isPrediction || isAnchor) && predValue != null ? Number(predValue).toFixed(2) : '-'}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid var(--border)', color: isExpiredPred ? '#9ca3af' : 'var(--text)'}}>
                        {isPrediction && predLow != null ? Number(predLow).toFixed(2) : '-'}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid var(--border)', color: isExpiredPred ? '#9ca3af' : 'var(--text)'}}>
                        {isPrediction && predHigh != null ? Number(predHigh).toFixed(2) : '-'}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'center', borderBottom: '1px solid var(--border)', color: hasError ? (Number(row.error_pct) < 2 ? '#10b981' : Number(row.error_pct) < 5 ? '#f59e0b' : '#ef4444') : 'var(--text-muted)', fontWeight: hasError ? 600 : 400}}>
                        {errorDisplay}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'center', borderBottom: '1px solid var(--border)', color: directionColor, fontWeight: hasDirection ? 600 : 400, fontSize: hasDirection ? 13 : 12}}>
                        {directionDisplay}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'center', borderBottom: '1px solid var(--border)'}}>
                        <span style={{
                          padding: '2px 6px',
                          borderRadius: 4,
                          fontSize: 10,
                          background: isHistorical
                            ? 'rgba(255,255,255,0.1)'
                            : (isAnchor ? 'rgba(148, 163, 184, 0.15)' : (isExpiredPred ? 'rgba(156, 163, 175, 0.15)' : 'rgba(99, 102, 241, 0.15)')),
                          color: isHistorical
                            ? 'var(--text-muted)'
                            : (isAnchor ? '#cbd5e1' : (isExpiredPred ? '#9ca3af' : 'var(--primary)'))
                        }}>
                          {isHistorical ? '历史' : (isAnchor ? '预测起点' : (isExpiredPred ? '过期预测' : '未来预测'))}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{fontSize:12, color:'#6b7280', textAlign: 'center', padding: 20}}>
            暂无数据显示
          </div>
        )}
      </FloatingModule>

      <FloatingModule style={{marginTop:12, padding:12, borderRadius:12}}>
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8}}>
          <div style={{fontWeight:600, fontSize:14, display:'flex', alignItems:'center', gap:6}}>
            🎯 预测复盘
            <HelpTooltip {...helpTips.tradeReview}><HelpIcon /></HelpTooltip>
          </div>
          <div style={{fontSize:11, color:'var(--text-muted)'}}>预测 vs 实际收盘，含误差(MAPE)与方向准确率</div>
        </div>
        <ForecastReview />
      </FloatingModule>

      <div className="card-panel watchlist-analysis-card" style={{marginTop:12}}>
        <style>
          {`
            .watchlist-analysis-card > div {
              border: none !important;
              padding: 0 !important;
              border-radius: 0 !important;
            }
          `}
        </style>
        <WatchlistAnalysis />
      </div>

      <div style={{fontSize:12, color:'#6b7280', marginTop:12}}>
        仅供学习研究，不构成投资建议。
      </div>
    </>
  )
}