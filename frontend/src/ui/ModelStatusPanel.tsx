import React from 'react'
import type { PredictionHistoryResponse, StockInsightResponse } from '../api/report'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../config/helpTips'

type ModelStatusPanelProps = {
  symbol?: string
  data: PredictionHistoryResponse | null
  insight: StockInsightResponse | null
  loading: boolean
  insightLoading: boolean
  running: boolean
  onRunDaily: () => void
  onOpenDiagnostics: () => void
}

function fmtPct(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(Number(value))) return '-'
  return `${Number(value).toFixed(digits)}%`
}

function toneColor(kind?: string | null) {
  if (kind === 'excellent' || kind === 'good' || kind === 'passed' || kind === 'available') return '#10b981'
  if (kind === 'watch' || kind === 'medium' || kind === 'pending' || kind === 'insufficient_samples') return '#f59e0b'
  if (kind === 'risk' || kind === 'high' || kind === 'failed' || kind === 'task_failed') return '#ef4444'
  return 'var(--text-muted)'
}

function qualityLabel(grade?: string | null) {
  switch (grade) {
    case 'excellent': return '优秀'
    case 'good': return '良好'
    case 'watch': return '观察'
    case 'risk': return '风险'
    default: return '待评估'
  }
}

function statusLabel(status?: string | null) {
  switch (status) {
    case 'available': return '可复盘'
    case 'insufficient_samples': return '样本不足'
    case 'pending_target_date': return '等待验证'
    case 'task_failed': return '任务失败'
    case 'missing_actual_price': return '缺少收盘价'
    case 'invalid_prediction_data': return '预测无效'
    case 'passed': return '已通过'
    case 'failed': return '未通过'
    case 'blocked': return '已阻断'
    case 'candidate_allowed': return '候选观察'
    case 'observation_only': return '受控观察'
    default: return '暂无状态'
  }
}

function signalLabel(signal?: string | null) {
  switch (signal) {
    case 'strong_buy': return '强买入'
    case 'buy': return '买入'
    case 'hold': return '观望'
    case 'sell': return '卖出'
    case 'strong_sell': return '强卖出'
    default: return '暂无结论'
  }
}

function riskLabel(level?: string | null) {
  switch (level) {
    case 'low': return '低风险'
    case 'medium': return '中风险'
    case 'high': return '高风险'
    case 'extreme': return '极高风险'
    default: return '待评估'
  }
}

function signedPct(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(Number(value))) return '-'
  const n = Number(value)
  const pct = Math.abs(n) <= 1 ? n * 100 : n
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(digits)}%`
}

function MiniStat({ label, value, color, tip }: { label: string; value: React.ReactNode; color?: string; tip?: HelpTipKey }) {
  return (
    <div style={{border:'1px solid var(--border)', borderRadius:8, padding:'8px 9px', background:'rgba(255,255,255,0.018)'}}>
      <div style={{fontSize:10, color:'var(--text-muted)', marginBottom:4, display:'flex', alignItems:'center', gap:5}}>
        {label}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </div>
      <div style={{fontSize:15, fontWeight:700, color:color || 'var(--text)', fontVariantNumeric:'tabular-nums'}}>{value}</div>
    </div>
  )
}

export default function ModelStatusPanel({ symbol, data, insight, loading, insightLoading, running, onRunDaily, onOpenDiagnostics }: ModelStatusPanelProps) {
  const availability = data?.availability
  const quality = data?.quality
  const stats = data?.stats
  const review = data?.agent_review
  const gateStatus = review?.gate_result?.status || review?.verification_status
  const pipelineStatus = availability?.pipeline_status || availability?.status
  const headline = quality?.headline || review?.headline || availability?.reason || '选择股票后可查看模型状态、复盘质量和 Agent 审核摘要。'
  const decision = insight?.trade_decision
  const action = decision?.signal || insight?.signal?.action
  const expectedReturn = decision?.expected_return ?? insight?.prediction?.predicted_return
  const riskLevel = decision?.risk_level
  const decisionConfidence = decision?.confidence ?? insight?.prediction?.confidence ?? null
  const qualityGrade = quality?.quality_grade
  const qualityIsWeak = qualityGrade === 'risk' || qualityGrade === 'watch' || availability?.status === 'insufficient_samples'
  const decisionIsDirectional = action === 'strong_buy' || action === 'buy' || action === 'sell' || action === 'strong_sell'
  const alignmentTone = !symbol || insightLoading ? 'var(--text-muted)'
    : !insight?.has_data ? 'var(--text-muted)'
    : qualityIsWeak && decisionIsDirectional ? '#f59e0b'
    : riskLevel === 'high' || riskLevel === 'extreme' ? '#ef4444'
    : '#10b981'
  const alignmentText = !symbol ? '选择标的后联动交易辅助结论'
    : insightLoading ? '交易辅助结论加载中'
    : !insight?.has_data ? '暂无交易辅助结论'
    : qualityIsWeak && decisionIsDirectional ? '模型质量需复核，交易结论仅作观察'
    : riskLevel === 'high' || riskLevel === 'extreme' ? '风险等级偏高，需优先复核风险项'
    : '模型状态与交易辅助结论可联合参考'

  return (
    <div style={{display:'flex', flexDirection:'column', gap:10}}>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:10}}>
        <div>
          <div style={{fontWeight:700, color:'var(--text)', fontSize:15, display:'flex', alignItems:'center', gap:6}}>
            模型状态
            <HelpTooltip {...helpTips.modelStatus}><HelpIcon /></HelpTooltip>
          </div>
          <div style={{fontSize:11, color:'var(--text-muted)', marginTop:3}}>{symbol ? `当前标的 ${symbol}` : '尚未选择标的'}</div>
        </div>
        <span style={{fontSize:10, color:toneColor(pipelineStatus), border:'1px solid var(--border)', borderRadius:4, padding:'2px 6px', whiteSpace:'nowrap'}}>
          {loading ? '加载中' : statusLabel(pipelineStatus)}
        </span>
      </div>

      <div style={{fontSize:12, color:'var(--text)', lineHeight:1.5, border:'1px solid var(--border)', borderRadius:8, padding:'8px 9px', background:'rgba(255,255,255,0.02)'}}>
        {headline}
      </div>

      <div style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap:8}}>
        <MiniStat label="质量等级" value={quality ? qualityLabel(quality.quality_grade) : '-'} color={toneColor(quality?.quality_grade)} tip="modelStatus" />
        <MiniStat label="质量分" value={quality?.quality_score != null ? quality.quality_score.toFixed(1) : '-'} color={toneColor(quality?.quality_grade)} tip="compositeScore" />
        <MiniStat label="MAPE" value={fmtPct(stats?.mape ?? quality?.mape, 2)} color={(stats?.mape ?? quality?.mape) != null && Number(stats?.mape ?? quality?.mape) <= 8 ? '#10b981' : '#f59e0b'} tip="mape" />
        <MiniStat label="方向准确" value={fmtPct(stats?.direction_accuracy ?? quality?.direction_accuracy, 1)} color={(stats?.direction_accuracy ?? quality?.direction_accuracy) != null && Number(stats?.direction_accuracy ?? quality?.direction_accuracy) >= 55 ? '#10b981' : '#f59e0b'} tip="directionAccuracy" />
      </div>

      <div style={{display:'grid', gap:6, fontSize:11, color:'var(--text-muted)'}}>
        <div style={{display:'flex', justifyContent:'space-between', gap:8}}>
          <span>最近预测</span>
          <span style={{color:'var(--text)'}}>{availability?.latest_prediction_date || '-'}</span>
        </div>
        <div style={{display:'flex', justifyContent:'space-between', gap:8}}>
          <span>目标验证日</span>
          <span style={{color:'var(--text)'}}>{availability?.latest_target_date || availability?.next_evaluable_date || '-'}</span>
        </div>
        <div style={{display:'flex', justifyContent:'space-between', gap:8}}>
          <span>Agent 门禁</span>
          <span style={{color:toneColor(gateStatus)}}>{statusLabel(gateStatus)}</span>
        </div>
      </div>

      <div style={{border:'1px solid var(--border)', borderRadius:8, padding:'8px 9px', background:'rgba(255,255,255,0.018)'}}>
        <div style={{display:'flex', justifyContent:'space-between', gap:8, alignItems:'center', marginBottom:6}}>
          <div style={{fontSize:11, fontWeight:700, color:'var(--text)'}}>交易辅助联动</div>
          <span style={{fontSize:10, color:alignmentTone}}>{alignmentText}</span>
        </div>
        <div style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap:6, fontSize:11}}>
          <div><span style={{color:'var(--text-muted)'}}>结论 </span><span style={{fontWeight:700, color:toneColor(action === 'buy' || action === 'strong_buy' ? 'good' : action === 'sell' || action === 'strong_sell' ? 'high' : 'watch')}}>{signalLabel(action)}</span></div>
          <div><span style={{color:'var(--text-muted)'}}>风险 </span><span style={{fontWeight:700, color:toneColor(riskLevel === 'low' ? 'good' : riskLevel === 'medium' ? 'watch' : riskLevel)}}>{riskLabel(riskLevel)}</span></div>
          <div><span style={{color:'var(--text-muted)'}}>预期收益 </span><span style={{fontWeight:700, color:Number(expectedReturn ?? 0) >= 0 ? '#10b981' : '#ef4444'}}>{signedPct(expectedReturn)}</span></div>
          <div><span style={{color:'var(--text-muted)'}}>置信度 </span><span style={{fontWeight:700}}>{decisionConfidence != null ? signedPct(decisionConfidence, 1).replace('+', '') : '-'}</span></div>
        </div>
      </div>

      <div style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap:8}}>
        <HelpTooltip {...helpTips.runTraining}>
          <span style={{display:'inline-flex'}}>
            <button
              type="button"
              onClick={onRunDaily}
              disabled={running}
              className="dark-btn dark-btn-secondary"
              style={{fontSize:12, padding:'7px 8px', opacity:running ? 0.65 : 1}}
            >
              {running ? '执行中...' : '运行训练'}
            </button>
          </span>
        </HelpTooltip>
        <HelpTooltip {...helpTips.dataPipelineDiagnosis}>
          <span style={{display:'inline-flex'}}>
            <button
              type="button"
              onClick={onOpenDiagnostics}
              disabled={!symbol}
              className="dark-btn dark-btn-secondary"
              style={{fontSize:12, padding:'7px 8px', opacity:symbol ? 1 : 0.55}}
            >
              诊断详情
            </button>
          </span>
        </HelpTooltip>
      </div>

      <div style={{fontSize:10, color:'var(--text-muted)', lineHeight:1.45}}>
        模型状态用于辅助研究和复核，不构成投资建议，也不代表自动交易指令。
      </div>
    </div>
  )
}