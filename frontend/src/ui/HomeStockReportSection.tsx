import React from 'react'
import FloatingModule from './FloatingModule'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips } from '../config/helpTips'

type ReportPrediction = {
  predicted_price?: number | null
  lower_bound?: number | null
  upper_bound?: number | null
  signal_level?: 'strong_bullish' | 'weak_bullish' | 'neutral' | 'weak_bearish' | 'strong_bearish'
  direction_snr?: number | null
}

type ReportSignal = {
  ma_short?: number | null
  ma_long?: number | null
  rsi?: number | null
  macd?: number | null
  signal_score?: number | null
  action?: string | null
}

type StockReport = {
  latest?: {
    close?: number | null
    pct_chg?: number | null
    volume?: number | null
    date?: string | null
  } | null
  signal?: ReportSignal | null
  predictions?: ReportPrediction[]
  data_quality_score?: number | null
  prediction_confidence?: number | null
}

type SignalTag = { text: string; bg: string; fg: string }

const tagTone = {
  buy: { bg: 'var(--action-buy-bg)', fg: 'var(--action-buy-fg)' },
  sell: { bg: 'var(--action-sell-bg)', fg: 'var(--action-sell-fg)' },
  hold: { bg: 'var(--action-hold-bg)', fg: 'var(--action-hold-fg)' },
  info: { bg: 'rgba(59,130,246,0.14)', fg: '#93c5fd' },
  neutral: { bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-fg)' },
  purple: { bg: 'rgba(99,102,241,0.14)', fg: '#a5b4fc' },
}

type HomeStockReportSectionProps = {
  current?: string
  currentName?: string
  report: StockReport | null
}

function InfoTip({ text }: { text: string }) {
  return (
    <span style={{display:'inline-flex', alignItems:'center', marginLeft:3}}>
      <HelpTooltip content={text}><HelpIcon /></HelpTooltip>
    </span>
  )
}

function SignalRow({ label, desc, value, unit, color, bar, tag, tip }: {
  label: string
  desc: string
  value: React.ReactNode
  unit?: string
  color?: string
  bar?: { pct: number; zones?: { pct: number; color: string }[] }
  tag?: SignalTag
  tip?: string
}) {
  return (
    <div style={{padding:'8px 10px', borderBottom:'1px solid var(--border, #e5e7eb)'}}>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
        <div style={{display:'flex', alignItems:'center'}}>
          <span style={{fontSize:13, fontWeight:600, color:'var(--text, #1f2937)'}}>{label}</span>
          {tip && <InfoTip text={tip} />}
          <span style={{fontSize:11, color:'var(--text-muted, #9ca3af)', marginLeft:4}}>{desc}</span>
        </div>
        <div style={{display:'flex', alignItems:'center', gap:6}}>
          <span style={{fontSize:16, fontWeight:700, color: color || 'var(--text, #1f2937)', fontVariantNumeric:'tabular-nums'}}>{value}</span>
          {unit && <span style={{fontSize:11, color:'var(--text-muted, #9ca3af)'}}>{unit}</span>}
          {tag && <span style={{fontSize:10, fontWeight:600, padding:'2px 6px', borderRadius:4, background:tag.bg, color:tag.fg}}>{tag.text}</span>}
        </div>
      </div>
      {bar && (
        <div style={{marginTop:4, height:6, borderRadius:3, background:'var(--border, #e5e7eb)', overflow:'hidden', position:'relative'}}>
          {bar.zones ? bar.zones.map((z, i) => (
            <div key={i} style={{position:'absolute', left: i === 0 ? 0 : `${bar.zones!.slice(0, i).reduce((acc, zone) => acc + zone.pct, 0)}%`, width:`${z.pct}%`, height:'100%', background:z.color, opacity:0.25}} />
          )) : null}
          <div style={{position:'absolute', left:`${Math.min(Math.max(bar.pct, 0), 100)}%`, top:-1, width:3, height:8, borderRadius:1, background: color || '#3b82f6', transform:'translateX(-50%)'}} />
        </div>
      )}
    </div>
  )
}

export default function HomeStockReportSection({ current, currentName, report }: HomeStockReportSectionProps) {
  return (
    <FloatingModule style={{padding:12, borderRadius:12}}>
      <div style={{fontWeight:600, marginBottom:8, display:'flex', alignItems:'center', gap:6}}>
        个股数据报表
        <HelpTooltip {...helpTips.professionalData}><HelpIcon /></HelpTooltip>
        {current && (
          <span style={{fontSize:12, fontWeight:500, color:'var(--text-muted, #9ca3af)'}}>
            — {currentName || ''} ({current})
          </span>
        )}
      </div>
      {report?.latest ? <StockReportContent report={report} /> : <div style={{fontSize:12, color:'#6b7280'}}>尚无报告，请先添加并选择股票。</div>}
    </FloatingModule>
  )
}

function StockReportContent({ report }: { report: StockReport }) {
  const close = Number(report.latest?.close)
  const pct = Number(report.latest?.pct_chg)
  const vol = Number(report.latest?.volume)
  const sig = report.signal
  const pctColor = pct > 0 ? '#ef4444' : pct < 0 ? '#22c55e' : 'var(--text, #6b7280)'
  const pctSign = pct >= 0 ? '+' : ''
  const maShort = sig ? Number(sig.ma_short) : NaN
  const maLong = sig ? Number(sig.ma_long) : NaN
  const maCross = (!isNaN(maShort) && !isNaN(maLong))
    ? (maShort > maLong ? {text:'金叉 (短>长)', ...tagTone.buy} : {text:'死叉 (短<长)', ...tagTone.sell})
    : undefined
  const rsi = sig ? Number(sig.rsi) : NaN
  const rsiTag = !isNaN(rsi)
    ? (rsi >= 80 ? {text:'强超买', ...tagTone.sell}
      : rsi >= 70 ? {text:'超买', ...tagTone.hold}
      : rsi >= 50 ? {text:'偏强', ...tagTone.buy}
      : rsi >= 30 ? {text:'偏弱', ...tagTone.hold}
      : rsi >= 20 ? {text:'超卖', ...tagTone.info}
      : {text:'强超卖', ...tagTone.purple})
    : undefined
  const macd = sig ? Number(sig.macd) : NaN
  const macdTag = !isNaN(macd)
    ? (macd > 0 ? {text:'多头动能', ...tagTone.buy} : {text:'空头动能', ...tagTone.sell})
    : undefined
  const score = sig ? Number(sig.signal_score) : NaN
  const scoreTag = !isNaN(score)
    ? (score >= 80 ? {text:'强烈买入', ...tagTone.buy}
      : score >= 60 ? {text:'偏多', ...tagTone.buy}
      : score >= 40 ? {text:'中性', ...tagTone.neutral}
      : score >= 20 ? {text:'偏空', ...tagTone.hold}
      : {text:'强烈卖出', ...tagTone.sell})
    : undefined
  const actionMap: Record<string, SignalTag> = {
    BUY: {text:'📈 买入', ...tagTone.buy},
    SELL: {text:'📉 卖出', ...tagTone.sell},
    HOLD: {text:'⏸ 持有', ...tagTone.hold},
    STRONG_BUY: {text:'🔥 强烈买入', ...tagTone.buy},
    STRONG_SELL: {text:'⚠️ 强烈卖出', ...tagTone.sell},
  }
  const actionTag = sig?.action ? (actionMap[sig.action] || {text:sig.action, ...tagTone.neutral}) : undefined
  const pred = report.predictions?.[0]
  const signalLevel = pred?.signal_level
  const signalMap = {
    strong_bullish: {emoji: '🔥', text: '强看涨', ...tagTone.buy, confidence: '高'},
    weak_bullish: {emoji: '📈', text: '弱看涨', ...tagTone.buy, confidence: '中'},
    neutral: {emoji: '➜', text: '中性', ...tagTone.neutral, confidence: '低'},
    weak_bearish: {emoji: '📉', text: '弱看跌', ...tagTone.hold, confidence: '中'},
    strong_bearish: {emoji: '⚠️', text: '强看跌', ...tagTone.sell, confidence: '高'},
  }
  const signalTag = signalLevel ? signalMap[signalLevel] : signalMap.neutral
  const predDir = pred && close
    ? (signalLevel && signalLevel !== 'neutral' ? (signalLevel.includes('bullish') ? '↑' : '↓') : '—')
    : null
  const predColor = pred && close
    ? (signalLevel && signalLevel !== 'neutral' ? (signalLevel.includes('bullish') ? '#22c55e' : '#ef4444') : '#9ca3af')
    : undefined

  return (
    <div style={{display:'flex', flexDirection:'column', gap:0, border:'1px solid var(--border, #e5e7eb)', borderRadius:8, overflow:'hidden'}}>
      <div style={{padding:'8px 10px', background:'rgba(59,130,246,0.04)', borderBottom:'1px solid var(--border, #e5e7eb)'}}>
        <div style={{fontSize:11, fontWeight:600, color:'var(--text-muted, #9ca3af)', marginBottom:4, letterSpacing:0.5, display:'flex', alignItems:'center'}}>价格概览<InfoTip text={helpTips.priceOverview.content} /></div>
        <div style={{display:'flex', alignItems:'baseline', gap:8}}>
          <span style={{fontSize:22, fontWeight:700, color:'var(--text, #1f2937)'}}>¥{close.toFixed(2)}</span>
          <span style={{fontSize:14, fontWeight:600, color: pctColor}}>{pctSign}{pct.toFixed(2)}%</span>
          {vol > 0 && <span style={{fontSize:11, color:'var(--text-muted, #9ca3af)'}}>成交量 {vol >= 10000 ? `${(vol / 10000).toFixed(0)}万` : vol.toLocaleString()}</span>}
        </div>
        {report.latest?.date && <div style={{fontSize:10, color:'var(--text-muted, #9ca3af)', marginTop:2}}>数据日期: {report.latest.date}</div>}
      </div>

      <div style={{padding:'6px 10px 2px', borderBottom:'1px solid var(--border, #e5e7eb)'}}>
        <div style={{fontSize:11, fontWeight:600, color:'var(--text-muted, #9ca3af)', marginBottom:2, letterSpacing:0.5, display:'flex', alignItems:'center'}}>技术指标<InfoTip text={helpTips.professionalData.content} /></div>
      </div>
      <SignalRow label="均线" desc="短期MA vs 长期MA" unit="¥"
        value={!isNaN(maShort) ? `${maShort.toFixed(2)} / ${maLong.toFixed(2)}` : '-'}
        color={maCross ? (maShort > maLong ? '#16a34a' : '#dc2626') : undefined}
        tag={maCross}
        tip={helpTips.movingAverage.content}
      />
      <SignalRow label="RSI" desc="相对强弱指数 (0-100)"
        value={!isNaN(rsi) ? rsi.toFixed(1) : '-'}
        color={rsiTag?.fg}
        tag={rsiTag}
        bar={!isNaN(rsi) ? { pct: rsi, zones: [
          {pct:20, color:'#6366f1'},
          {pct:10, color:'#3b82f6'},
          {pct:20, color:'#22c55e'},
          {pct:20, color:'#22c55e'},
          {pct:10, color:'#f97316'},
          {pct:20, color:'#ef4444'},
        ] } : undefined}
        tip={helpTips.rsi.content}
      />
      <SignalRow label="MACD" desc="指数平滑移动平均线"
        value={!isNaN(macd) ? macd.toFixed(4) : '-'}
        color={macdTag?.fg}
        tag={macdTag}
        tip={helpTips.macd.content}
      />
      <SignalRow label="综合评分" desc="多指标加权 (0-100)"
        value={!isNaN(score) ? score.toFixed(1) : '-'}
        color={scoreTag?.fg}
        tag={scoreTag}
        bar={!isNaN(score) ? { pct: score, zones: [
          {pct:20, color:'#ef4444'},
          {pct:20, color:'#f97316'},
          {pct:20, color:'#6b7280'},
          {pct:20, color:'#22c55e'},
          {pct:20, color:'#16a34a'},
        ] } : undefined}
        tip={helpTips.compositeScore.content}
      />

      <div style={{padding:'8px 10px', borderTop:'1px solid var(--border, #e5e7eb)', display:'flex', justifyContent:'space-between', alignItems:'center', background:'rgba(59,130,246,0.02)'}}>
        <div style={{display:'flex', alignItems:'center'}}>
          <span style={{fontSize:12, fontWeight:600, color:'var(--text, #1f2937)'}}>操作建议</span>
          <InfoTip text={helpTips.technicalAction.content} />
          <span style={{fontSize:10, color:'var(--text-muted, #9ca3af)', marginLeft:4}}>基于技术面综合分析</span>
        </div>
        {actionTag && <span style={{fontSize:13, fontWeight:700, padding:'3px 10px', borderRadius:6, background:actionTag.bg, color:actionTag.fg}}>{actionTag.text}</span>}
      </div>

      {pred && (
        <div style={{padding:'8px 10px', borderTop:'1px solid var(--border, #e5e7eb)', background: signalTag.bg}}>
          <div style={{fontSize:11, fontWeight:600, color:'var(--text-muted, #9ca3af)', marginBottom:4, letterSpacing:0.5, display:'flex', alignItems:'center'}}>下一交易日预测信号<InfoTip text={helpTips.predictionSignal.content} /></div>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start'}}>
            <div>
              <div style={{fontSize:14, fontWeight:700, color: signalTag.fg, marginBottom:2}}>
                {signalTag.emoji} {signalTag.text}
              </div>
              <div style={{fontSize:11, color:'var(--text-muted, #9ca3af)'}}>
                置信度: <span style={{fontWeight:600, color: signalTag.fg}}>{signalTag.confidence}</span>
                {pred.direction_snr && <span style={{marginLeft:8}}>SNR: {Number(pred.direction_snr).toFixed(2)}</span>}
              </div>
            </div>
            <div style={{display:'flex', flexDirection:'column', alignItems:'flex-end'}}>
              <span style={{fontSize:16, fontWeight:700, color: predColor}}>¥{Number(pred.predicted_price).toFixed(2)}</span>
              <span style={{fontSize:13, color: predColor, marginTop:2}}>{predDir}</span>
              <span style={{fontSize:9, color:'var(--text-muted, #9ca3af)', marginTop:4}}>区间: ({Number(pred.lower_bound).toFixed(2)}~{Number(pred.upper_bound).toFixed(2)})</span>
            </div>
          </div>
        </div>
      )}

      {(report.data_quality_score != null || report.prediction_confidence != null) && (
        <div style={{padding:'4px 10px 6px', borderTop:'1px solid var(--border, #e5e7eb)', display:'flex', gap:12, fontSize:10, color:'var(--text-muted, #9ca3af)'}}>
          {report.data_quality_score != null && <span style={{display:'inline-flex', alignItems:'center', gap:4}}>数据质量: {(Number(report.data_quality_score) * 100).toFixed(0)}%<InfoTip text={helpTips.dataQuality.content} /></span>}
          {report.prediction_confidence != null && <span style={{display:'inline-flex', alignItems:'center', gap:4}}>预测置信度: {(Number(report.prediction_confidence) * 100).toFixed(0)}%<InfoTip text={helpTips.predictionConfidence.content} /></span>}
        </div>
      )}
    </div>
  )
}