import React from 'react'
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import FloatingModule from './FloatingModule'
import PricePredictionStatus from './PricePredictionStatus'
import PredictionReviewPanel from './PredictionReviewPanel'
import { CustomChartTooltip } from './components/CustomChartTooltip'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import type { PredictionHistoryResponse } from '../api/report'
import type { TradePlaybook } from '../api/tradePlaybook'
import { helpTips, type HelpTipKey } from '../config/helpTips'

type TimeRange = '5d' | '1m' | '3m' | '6m' | '1y' | 'all'

type ChartSeriesFlags = {
  hasHistoryD1: boolean
  hasHistoryD1Band: boolean
  hasHistoryD5: boolean
  hasForecast: boolean
  hasForecastBand: boolean
  hasExpiredForecast: boolean
  hasExpiredForecastBand: boolean
}

type HomePriceChartSectionProps = {
  current?: string
  currentName?: string
  timeRange: TimeRange
  onTimeRangeChange: (range: TimeRange) => void
  predictionHistory: PredictionHistoryResponse | null
  predictionHistoryLoading: boolean
  loading: boolean
  merged: any[]
  chartSeries: ChartSeriesFlags
  onOpenDiagnostics: (symbol: string) => void
  tradePlaybook?: TradePlaybook | null
  professionalMode?: boolean
}

const TIME_RANGE_OPTIONS: Array<{ key: TimeRange; label: string }> = [
  {key: '5d', label: '5日'},
  {key: '1m', label: '1月'},
  {key: '3m', label: '3月'},
  {key: '6m', label: '6月'},
  {key: '1y', label: '1年'},
  {key: 'all', label: '全部'},
]

const LEGEND_TIPS: Array<{ label: string; tip: HelpTipKey; color: string }> = [
  { label: '历史价格', tip: 'historicalPrice', color: '#2563eb' },
  { label: 'AI预测主线', tip: 'aiPredictionLine', color: '#8884d8' },
  { label: '买入区间', tip: 'idealBuyRange', color: '#14b8a6' },
  { label: '突破买入线', tip: 'breakoutBuyAbove', color: '#60a5fa' },
  { label: '不追高线', tip: 'doNotChaseAbove', color: '#fbbf24' },
  { label: '止损线', tip: 'stopLossPrice', color: '#f87171' },
  { label: '第一目标价', tip: 'takeProfitPrice1', color: '#22c55e' },
  { label: '第二目标价', tip: 'takeProfitPrice2', color: '#16a34a' },
  { label: '预测上界', tip: 'predictionUpper', color: '#a78bfa' },
  { label: '预测下界', tip: 'predictionLower', color: '#a78bfa' },
  { label: '历史预测', tip: 'historicalPrediction', color: '#f59e0b' },
  { label: '实际收盘价', tip: 'actualClose', color: '#2563eb' },
]

export default function HomePriceChartSection({
  current,
  currentName,
  timeRange,
  onTimeRangeChange,
  predictionHistory,
  predictionHistoryLoading,
  loading,
  merged,
  chartSeries,
  onOpenDiagnostics,
  tradePlaybook,
  professionalMode = true,
}: HomePriceChartSectionProps) {
  const buyRange = tradePlaybook?.buyPlan?.idealBuyRange || null
  const stopLoss = tradePlaybook?.sellPlan?.stopLossPrice ?? null
  const takeProfit1 = tradePlaybook?.sellPlan?.takeProfitPrice1 ?? null
  const takeProfit2 = tradePlaybook?.sellPlan?.takeProfitPrice2 ?? null
  const doNotChase = tradePlaybook?.buyPlan?.doNotChaseAbove ?? null
  const breakout = tradePlaybook?.buyPlan?.breakoutBuyAbove ?? null

  return (
    <FloatingModule style={{marginTop:12, padding:12, borderRadius:12}}>
      {professionalMode && <PricePredictionStatus symbol={current} onOpenDrawer={onOpenDiagnostics} />}
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:12, marginBottom:12, flexWrap:'wrap'}}>
        <div style={{fontWeight:600, display:'flex', alignItems:'center', gap:6, flexWrap:'wrap'}}>
          {professionalMode ? '价格走势 & 预测区间' : '价格走势 & 交易计划线'}
          <HelpTooltip {...helpTips.predictionChart}><HelpIcon /></HelpTooltip>
          {current && <span style={{fontWeight:500, fontSize:13, color:'var(--primary, #6366f1)', marginLeft:8}}>— {currentName || ''} ({current})</span>}
        </div>

        <div style={{display:'flex', alignItems:'center', gap:8}}>
          <span style={{fontSize:12, color:'#6b7280', display:'inline-flex', alignItems:'center', gap:4}}>
            时间区间
            <HelpTooltip {...helpTips.timeRange}><HelpIcon /></HelpTooltip>
          </span>
          <div style={{display:'flex', gap:4, flexWrap:'wrap'}}>
            {TIME_RANGE_OPTIONS.map(option => (
              <button
                key={option.key}
                onClick={() => onTimeRangeChange(option.key)}
                style={{
                  padding: '4px 8px',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  background: timeRange === option.key ? 'var(--primary)' : 'var(--surface-dark)',
                  color: timeRange === option.key ? '#fff' : 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: timeRange === option.key ? '500' : '400'
                }}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {!professionalMode && tradePlaybook && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0,1fr))', gap: 8, marginBottom: 12 }}>
          <div style={{ border: '1px solid rgba(20,184,166,0.28)', borderRadius: 8, padding: 10, color: 'var(--text-muted)', fontSize: 12 }}>买入区 <HelpTooltip {...helpTips.idealBuyRange}><HelpIcon /></HelpTooltip>：{buyRange ? `${buyRange[0].toFixed(2)} - ${buyRange[1].toFixed(2)}` : '-'}</div>
          <div style={{ border: '1px solid rgba(96,165,250,0.28)', borderRadius: 8, padding: 10, color: 'var(--text-muted)', fontSize: 12 }}>突破 <HelpTooltip {...helpTips.breakoutBuyAbove}><HelpIcon /></HelpTooltip>：{breakout?.toFixed(2) || '-'}</div>
          <div style={{ border: '1px solid rgba(251,191,36,0.28)', borderRadius: 8, padding: 10, color: 'var(--text-muted)', fontSize: 12 }}>不追高 <HelpTooltip {...helpTips.doNotChaseAbove}><HelpIcon /></HelpTooltip>：{doNotChase?.toFixed(2) || '-'}</div>
          <div style={{ border: '1px solid rgba(248,113,113,0.28)', borderRadius: 8, padding: 10, color: 'var(--text-muted)', fontSize: 12 }}>止损 <HelpTooltip {...helpTips.stopLossPrice}><HelpIcon /></HelpTooltip>：{stopLoss?.toFixed(2) || '-'}</div>
          <div style={{ border: '1px solid rgba(34,197,94,0.28)', borderRadius: 8, padding: 10, color: 'var(--text-muted)', fontSize: 12 }}>目标 <HelpTooltip {...helpTips.takeProfitPrice1}><HelpIcon /></HelpTooltip>：{takeProfit1?.toFixed(2) || '-'}</div>
        </div>
      )}

      {professionalMode && <PredictionReviewPanel data={predictionHistory} loading={predictionHistoryLoading} />}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        {LEGEND_TIPS.map(item => (
          <HelpTooltip key={item.label} {...helpTips[item.tip]}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, border: '1px solid var(--border)', borderRadius: 999, padding: '3px 8px', color: 'var(--text-muted)', fontSize: 11, background: 'rgba(255,255,255,0.02)', cursor: 'help' }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: item.color }} />
              {item.label}
            </span>
          </HelpTooltip>
        ))}
      </div>

      {loading ? <div>加载中…</div> : (
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={merged} margin={{ top: 10, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={24} allowDuplicatedCategory={false} />
            <YAxis tick={{ fontSize: 12 }} domain={['auto','auto']} />
            <Tooltip content={<CustomChartTooltip />} />
            <Legend />
            <Line
              type="monotone"
              dataKey="close"
              name="收盘价"
              dot={false}
              strokeWidth={2.5}
              stroke="#2563eb"
              connectNulls={true}
            />
            {buyRange && <ReferenceArea y1={buyRange[0]} y2={buyRange[1]} fill="#14b8a6" fillOpacity={0.12} strokeOpacity={0} />}
            {breakout != null && <ReferenceLine y={breakout} stroke="#60a5fa" strokeDasharray="5 4" label={{ value: '突破确认', position: 'insideTopRight', fill: '#93c5fd', fontSize: 11 }} />}
            {doNotChase != null && <ReferenceLine y={doNotChase} stroke="#fbbf24" strokeDasharray="4 4" label={{ value: '不追高', position: 'insideTopRight', fill: '#fde68a', fontSize: 11 }} />}
            {stopLoss != null && <ReferenceLine y={stopLoss} stroke="#f87171" strokeDasharray="4 3" label={{ value: '止损', position: 'insideBottomRight', fill: '#fca5a5', fontSize: 11 }} />}
            {takeProfit1 != null && <ReferenceLine y={takeProfit1} stroke="#22c55e" strokeDasharray="6 3" label={{ value: '目标1', position: 'insideTopLeft', fill: '#86efac', fontSize: 11 }} />}
            {professionalMode && takeProfit2 != null && <ReferenceLine y={takeProfit2} stroke="#16a34a" strokeDasharray="2 4" label={{ value: '目标2', position: 'insideTopLeft', fill: '#bbf7d0', fontSize: 11 }} />}
            {professionalMode && chartSeries.hasHistoryD1Band && <Area
              type="monotone"
              dataKey="history_d1_yu"
              name="D-1区间上界"
              dot={false}
              strokeWidth={0.8}
              stroke="#f59e0b"
              fill="#f59e0b"
              fillOpacity={0.035}
              strokeOpacity={0.35}
              strokeDasharray="2 3"
              connectNulls={false}
            />}
            {professionalMode && chartSeries.hasHistoryD1Band && <Area
              type="monotone"
              dataKey="history_d1_yl"
              name="D-1区间下界"
              dot={false}
              strokeWidth={0.8}
              stroke="#f59e0b"
              fill="#f59e0b"
              fillOpacity={0.035}
              strokeOpacity={0.35}
              strokeDasharray="2 3"
              connectNulls={false}
            />}
            {professionalMode && chartSeries.hasHistoryD1 && <Line
              type="monotone"
              dataKey="history_d1_yhat"
              name="历史预测D-1"
              dot={false}
              strokeWidth={1.8}
              stroke="#f59e0b"
              strokeDasharray="4 3"
              connectNulls={false}
            />}
            {professionalMode && chartSeries.hasHistoryD5 && <Line
              type="monotone"
              dataKey="history_d5_yhat"
              name="历史预测D-5"
              dot={false}
              strokeWidth={1.8}
              stroke="#10b981"
              strokeDasharray="6 3"
              connectNulls={false}
            />}
            {chartSeries.hasForecast && <Line
              type="monotone"
              dataKey="forecastMean"
              name="预测主线"
              dot={false}
              strokeWidth={2}
              stroke="#8884d8"
              strokeDasharray="5 5"
              connectNulls={true}
            />}
            {professionalMode && chartSeries.hasForecastBand && <Area
              type="monotone"
              dataKey="forecastUpper"
              name="预测上界"
              dot={false}
              strokeWidth={1}
              fillOpacity={0.12}
              stroke="#8884d8"
              fill="#8884d8"
              strokeDasharray="3 3"
              connectNulls={true}
            />}
            {professionalMode && chartSeries.hasForecastBand && <Area
              type="monotone"
              dataKey="forecastLower"
              name="预测下界"
              dot={false}
              strokeWidth={1}
              fillOpacity={0.12}
              stroke="#8884d8"
              fill="#8884d8"
              strokeDasharray="3 3"
              connectNulls={true}
            />}
            {professionalMode && chartSeries.hasExpiredForecast && <Line
              type="monotone"
              dataKey="forecastMeanExpired"
              name="过期预测主线"
              dot={false}
              strokeWidth={1.5}
              stroke="#9ca3af"
              strokeDasharray="2 4"
              strokeOpacity={0.6}
              connectNulls={false}
            />}
            {professionalMode && chartSeries.hasExpiredForecastBand && <Area
              type="monotone"
              dataKey="forecastUpperExpired"
              name="过期预测上界"
              dot={false}
              strokeWidth={0.8}
              fillOpacity={0.04}
              stroke="#9ca3af"
              fill="#9ca3af"
              strokeDasharray="2 4"
              connectNulls={false}
            />}
            {professionalMode && chartSeries.hasExpiredForecastBand && <Area
              type="monotone"
              dataKey="forecastLowerExpired"
              name="过期预测下界"
              dot={false}
              strokeWidth={0.8}
              fillOpacity={0.04}
              stroke="#9ca3af"
              fill="#9ca3af"
              strokeDasharray="2 4"
              connectNulls={false}
            />}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </FloatingModule>
  )
}