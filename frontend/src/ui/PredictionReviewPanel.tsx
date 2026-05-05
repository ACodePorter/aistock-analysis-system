import React from 'react'
import type {
  AgentReview,
  FailureAnalysis,
  PredictionDeviationCase,
  PredictionHistoryResponse,
} from '../api/report'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../config/helpTips'

function metricColor(value: number | null | undefined, kind: 'mape' | 'rate') {
  if (value == null) return 'var(--text-muted)'
  if (kind === 'mape') {
    if (value <= 3) return '#10b981'
    if (value <= 8) return '#f59e0b'
    return '#ef4444'
  }
  if (value >= 65) return '#10b981'
  if (value >= 50) return '#f59e0b'
  return '#ef4444'
}

function fmtNum(value: number | null | undefined) {
  return value == null || !Number.isFinite(Number(value)) ? '-' : Number(value).toFixed(2)
}

function availabilityTone(status?: string) {
  if (status === 'available') return { color: '#10b981', bg: 'rgba(16,185,129,0.08)', border: 'rgba(16,185,129,0.25)' }
  if (status === 'insufficient_samples' || status === 'pending_target_date') return { color: '#f59e0b', bg: 'rgba(245,158,11,0.08)', border: 'rgba(245,158,11,0.25)' }
  if (status === 'task_failed' || status === 'missing_actual_price' || status === 'invalid_prediction_data') return { color: '#ef4444', bg: 'rgba(239,68,68,0.08)', border: 'rgba(239,68,68,0.25)' }
  return { color: 'var(--text-muted)', bg: 'rgba(255,255,255,0.025)', border: 'var(--border)' }
}

function availabilityLabel(status?: string) {
  switch (status) {
    case 'available': return '可复盘'
    case 'insufficient_samples': return '样本不足'
    case 'pending_target_date': return '等待验证'
    case 'missing_actual_price': return '缺少收盘价'
    case 'no_prediction_snapshot': return '无预测快照'
    case 'invalid_prediction_data': return '预测无效'
    case 'task_failed': return '任务失败'
    case 'unsupported_horizon': return '跨度未展示'
    default: return '暂无状态'
  }
}

function deviationLevelLabel(level?: string) {
  switch (level) {
    case 'critical': return '严重'
    case 'high': return '偏高'
    case 'medium': return '中等'
    case 'low': return '轻微'
    case 'pending': return '待评估'
    default: return '-'
  }
}

function deviationLevelColor(level?: string) {
  switch (level) {
    case 'critical': return '#ef4444'
    case 'high': return '#f97316'
    case 'medium': return '#f59e0b'
    case 'low': return '#10b981'
    default: return 'var(--text-muted)'
  }
}

function Pill({ label, value, color, tip }: { label: string; value: React.ReactNode; color?: string; tip?: HelpTipKey }) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      padding: '3px 8px',
      borderRadius: 4,
      border: '1px solid var(--border)',
      background: 'rgba(255,255,255,0.025)',
      fontSize: 11,
      whiteSpace: 'nowrap',
    }}>
      <span style={{color: 'var(--text-muted)'}}>{label}</span>
      {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      <span style={{fontWeight: 600, color: color || 'var(--text)', fontVariantNumeric: 'tabular-nums'}}>{value}</span>
    </span>
  )
}

function PredictionQualityBadges({ data, loading }: { data: PredictionHistoryResponse | null; loading: boolean }) {
  const stats = data?.stats
  const availability = data?.availability
  const quality = data?.quality
  const qualityColor: Record<string, string> = {
    excellent: '#10b981',
    good: '#22c55e',
    watch: '#f59e0b',
    risk: '#ef4444',
    unknown: 'var(--text-muted)',
  }

  if (loading) {
    return <div style={{display:'flex', gap:6, flexWrap:'wrap'}}><Pill label="历史预测" value="加载中" tip="historicalPrediction" /></div>
  }
  if (!stats || stats.evaluated_records === 0) {
    const tone = availabilityTone(availability?.status)
    return <div style={{display:'flex', gap:6, flexWrap:'wrap'}}>
      <Pill label="历史预测" value={availabilityLabel(availability?.status)} color={tone.color} tip="historicalPrediction" />
      {quality && <Pill label="质量等级" value={quality.quality_label} color={qualityColor[quality.quality_grade]} />}
    </div>
  }
  return (
    <div style={{display:'flex', gap:6, flexWrap:'wrap'}}>
      {quality && <Pill label="质量等级" value={`${quality.quality_label}${quality.quality_score != null ? ` ${quality.quality_score.toFixed(1)}` : ''}`} color={qualityColor[quality.quality_grade]} />}
      {availability && availability.status !== 'available' && <Pill label="状态" value={availabilityLabel(availability.status)} color={availabilityTone(availability.status).color} />}
      <Pill label="30d MAPE" value={stats.mape != null ? `${stats.mape.toFixed(2)}%` : '-'} color={metricColor(stats.mape, 'mape')} tip="mape" />
      <Pill label="方向准确" value={stats.direction_accuracy != null ? `${stats.direction_accuracy.toFixed(1)}%` : '-'} color={metricColor(stats.direction_accuracy, 'rate')} tip="directionAccuracy" />
      <Pill label="区间命中" value={stats.interval_hit_rate != null ? `${stats.interval_hit_rate.toFixed(1)}%` : '-'} color={metricColor(stats.interval_hit_rate, 'rate')} tip="intervalHitRate" />
      <Pill label="D-1/D-5" value={`${stats.d1_count}/${stats.d5_count}`} tip="historicalPrediction" />
    </div>
  )
}

function PredictionEvaluationStatusCard({ data, loading }: { data: PredictionHistoryResponse | null; loading: boolean }) {
  if (loading || !data?.availability) return null
  const availability = data.availability
  const quality = data.quality
  const tone = availabilityTone(availability.status)
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'minmax(130px, 0.7fr) minmax(220px, 1.6fr) minmax(180px, 1fr)',
      gap: 10,
      alignItems: 'stretch',
    }}>
      <div style={{border: `1px solid ${tone.border}`, background: tone.bg, borderRadius: 8, padding: '8px 10px'}}>
        <div style={{fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, display:'flex', alignItems:'center', gap:5}}>评估状态 <HelpTooltip {...helpTips.planValid}><HelpIcon /></HelpTooltip></div>
        <div style={{fontSize: 16, fontWeight: 700, color: tone.color}}>{availabilityLabel(availability.status)}</div>
        <div style={{fontSize: 11, color: 'var(--text-muted)', marginTop: 3}}>样本 {availability.evaluated_records}/{Math.max(availability.min_samples, availability.evaluation_records || 0)}</div>
      </div>
      <div style={{border: '1px solid var(--border)', background: 'rgba(255,255,255,0.02)', borderRadius: 8, padding: '8px 10px'}}>
        <div style={{fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, display:'flex', alignItems:'center', gap:5}}>{quality ? '质量判断' : '原因'} <HelpTooltip {...helpTips.failureReason}><HelpIcon /></HelpTooltip></div>
        <div style={{fontSize: 13, color: 'var(--text)', lineHeight: 1.5}}>{quality?.headline || availability.reason}</div>
        <div style={{fontSize: 12, color: 'var(--text-muted)', marginTop: 4}}>{quality?.next_action || availability.next_action}</div>
        {!!quality?.warnings?.length && (
          <div style={{fontSize: 11, color: '#f59e0b', marginTop: 4, lineHeight: 1.45}}>{quality.warnings[0]}</div>
        )}
      </div>
      <div style={{border: '1px solid var(--border)', background: 'rgba(255,255,255,0.02)', borderRadius: 8, padding: '8px 10px', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6}}>
        <div>最新预测：<span style={{color:'var(--text)'}}>{availability.latest_prediction_date || '-'}</span></div>
        <div>目标日：<span style={{color:'var(--text)'}}>{availability.latest_target_date || '-'}</span></div>
        <div>最新收盘：<span style={{color:'var(--text)'}}>{availability.latest_actual_date || '-'}</span></div>
        {availability.pipeline_status && <div>流水线：<span style={{color: availability.pipeline_status === 'failed' ? '#ef4444' : 'var(--text)'}}>{availability.pipeline_status}</span></div>}
      </div>
    </div>
  )
}

function FailureAnalysisPanel({ analysis }: { analysis?: FailureAnalysis | null }) {
  if (!analysis || analysis.severity === 'unknown') return null
  const tone = analysis.severity === 'high' ? '#ef4444' : analysis.severity === 'medium' ? '#f59e0b' : '#10b981'
  return (
    <div style={{border: `1px solid ${tone}`, borderRadius: 8, padding: '8px 10px', background: 'rgba(255,255,255,0.018)'}}>
      <div style={{display:'flex', justifyContent:'space-between', gap: 10, alignItems:'center', marginBottom: 6}}>
        <div style={{fontWeight: 600, fontSize: 13, color: 'var(--text)', display:'flex', alignItems:'center', gap:6}}>失败归因 <HelpTooltip {...helpTips.failureReason}><HelpIcon /></HelpTooltip></div>
        <div style={{fontSize: 11, color: tone}}>样本 {analysis.sample_count} · 高偏差 {analysis.high_deviation_count}</div>
      </div>
      <div style={{fontSize: 12, color: 'var(--text)', lineHeight: 1.5}}>{analysis.headline}</div>
      {!!analysis.root_causes.length && (
        <div style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap: 8, marginTop: 8}}>
          {analysis.root_causes.slice(0, 2).map(cause => (
            <div key={cause.code} style={{border:'1px solid var(--border)', borderRadius: 6, padding: '7px 8px', background:'rgba(255,255,255,0.02)'}}>
              <div style={{fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 3}}>{cause.label}</div>
              <div style={{fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.45}}>{cause.evidence}</div>
            </div>
          ))}
        </div>
      )}
      {analysis.next_actions[0] && <div style={{fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.45, marginTop: 7, display:'flex', alignItems:'center', gap:5}}>下一步：{analysis.next_actions[0]} <HelpTooltip {...helpTips.nextOptimization}><HelpIcon /></HelpTooltip></div>}
      {analysis.coverage_notes[0] && <div style={{fontSize: 11, color: '#f59e0b', lineHeight: 1.45, marginTop: 5}}>{analysis.coverage_notes[0]}</div>}
      <div style={{fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.45, marginTop: 5}}>{analysis.disclaimer}</div>
    </div>
  )
}

function AgentReviewPanel({ review }: { review?: AgentReview | null }) {
  if (!review || review.status === 'waiting_for_samples') return null
  const tone = review.priority === 'high' ? '#ef4444' : review.priority === 'medium' ? '#f59e0b' : '#10b981'
  const gateTone = review.verification_status === 'passed' ? '#10b981' : review.verification_status === 'failed' ? '#ef4444' : '#f59e0b'
  const gateLabel = review.gate_result?.status === 'candidate_allowed' ? '可进入候选观察'
    : review.gate_result?.status === 'observation_only' ? '仅允许受控观察'
    : review.gate_result?.status === 'blocked' ? '已阻断'
    : '等待核实'
  return (
    <div style={{border:'1px solid var(--border)', borderRadius: 8, padding: '8px 10px', background:'rgba(59,130,246,0.035)'}}>
      <div style={{display:'flex', justifyContent:'space-between', gap: 10, alignItems:'center', marginBottom: 6}}>
        <div style={{fontWeight: 600, fontSize: 13, color:'var(--text)', display:'flex', alignItems:'center', gap:6}}>Agent 受控迭代建议 <HelpTooltip {...helpTips.agentReason}><HelpIcon /></HelpTooltip></div>
        <div style={{fontSize: 11, color: tone}}>{review.priority === 'high' ? '高优先级' : review.priority === 'medium' ? '中优先级' : '低优先级'}</div>
      </div>
      <div style={{fontSize: 12, color:'var(--text)', lineHeight: 1.5}}>{review.headline}</div>
      <div style={{display:'flex', flexWrap:'wrap', gap: 6, marginTop: 7}}>
        <span style={{fontSize: 10, borderRadius: 4, padding:'2px 6px', background:'rgba(255,255,255,0.05)', color: gateTone}}>自动核实：{review.verification_status || 'pending'}</span>
        <span style={{fontSize: 10, borderRadius: 4, padding:'2px 6px', background:'rgba(255,255,255,0.05)', color: gateTone}}>门禁：{gateLabel}</span>
      </div>
      {!!review.proposed_actions.length && (
        <div style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap: 8, marginTop: 8}}>
          {review.proposed_actions.slice(0, 2).map(action => (
            <div key={`${action.type}-${action.label}`} style={{border:'1px solid var(--border)', borderRadius: 6, padding:'7px 8px', background:'rgba(255,255,255,0.02)'}}>
              <div style={{fontSize: 12, fontWeight: 600, color:'var(--text)', marginBottom: 3}}>{action.label}</div>
              <div style={{fontSize: 11, color:'var(--text-muted)', lineHeight: 1.45}}>{action.rationale}</div>
              <div style={{fontSize: 10, color:'#f59e0b', lineHeight: 1.45, marginTop: 4}}>护栏：{action.guardrail}</div>
            </div>
          ))}
        </div>
      )}
      {!!review.verification_checks?.length && (
        <div style={{marginTop: 7, display:'flex', flexDirection:'column', gap: 3}}>
          {review.verification_checks.slice(0, 3).map(check => (
            <div key={check.check_id} style={{fontSize: 10, color: check.status === 'failed' ? '#ef4444' : check.status === 'warning' ? '#f59e0b' : '#10b981', lineHeight: 1.35}}>
              {check.check_type}: {check.message}
            </div>
          ))}
        </div>
      )}
      <div style={{fontSize: 10, color:'var(--text-muted)', lineHeight: 1.45, marginTop: 6}}>{review.disclaimer}</div>
    </div>
  )
}

function PredictionDeviationTable({ cases }: { cases?: PredictionDeviationCase[] }) {
  const items = (cases || []).filter(item => item.error_pct != null).slice(0, 5)
  if (!items.length) return null
  return (
    <div style={{border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: 'rgba(255,255,255,0.015)'}}>
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', padding:'7px 10px', borderBottom:'1px solid var(--border)'}}>
        <div style={{fontWeight: 600, fontSize: 13, color: 'var(--text)', display:'flex', alignItems:'center', gap:6}}>偏差复盘 <HelpTooltip {...helpTips.tradeReview}><HelpIcon /></HelpTooltip></div>
        <div style={{fontSize: 11, color: 'var(--text-muted)'}}>按偏差和方向/区间命中排序</div>
      </div>
      <div style={{overflowX:'auto'}}>
        <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
          <thead style={{background:'rgba(255,255,255,0.025)'}}>
            <tr>
              <th style={{padding:'6px 10px', textAlign:'left', color:'var(--text-muted)'}}>目标日</th>
              <th style={{padding:'6px 10px', textAlign:'right', color:'var(--text-muted)'}}>预测/实际</th>
              <th style={{padding:'6px 10px', textAlign:'right', color:'var(--text-muted)'}}>偏差</th>
              <th style={{padding:'6px 10px', textAlign:'center', color:'var(--text-muted)'}}>方向</th>
              <th style={{padding:'6px 10px', textAlign:'left', color:'var(--text-muted)'}}>说明</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <tr key={`${item.prediction_date}-${item.target_date}-${idx}`} style={{borderTop:'1px solid rgba(255,255,255,0.04)'}}>
                <td style={{padding:'6px 10px', color:'var(--text)'}}>{item.target_date || '-'}</td>
                <td style={{padding:'6px 10px', textAlign:'right', color:'var(--text)', fontVariantNumeric:'tabular-nums'}}>{fmtNum(item.predicted_price)} / {fmtNum(item.actual_price)}</td>
                <td style={{padding:'6px 10px', textAlign:'right', color: deviationLevelColor(item.deviation_level), fontWeight:600}}>
                  {item.signed_error_pct != null ? `${item.signed_error_pct >= 0 ? '+' : ''}${item.signed_error_pct.toFixed(2)}%` : '-'}
                  <span style={{marginLeft: 6, fontSize: 11}}>({deviationLevelLabel(item.deviation_level)})</span>
                </td>
                <td style={{padding:'6px 10px', textAlign:'center', color: item.direction_correct === false ? '#ef4444' : item.direction_correct === true ? '#10b981' : 'var(--text-muted)'}}>{item.direction_correct === true ? '命中' : item.direction_correct === false ? '未命中' : '-'}</td>
                <td style={{padding:'6px 10px', color:'var(--text-muted)', minWidth: 180}}>{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ReviewHeadline({ data }: { data: PredictionHistoryResponse | null }) {
  const failure = data?.failure_analysis
  const review = data?.agent_review
  const availability = data?.availability
  const quality = data?.quality
  if (failure && failure.severity !== 'unknown') return <>{failure.headline}</>
  if (review && review.status !== 'waiting_for_samples') return <>{review.headline}</>
  if (quality?.headline) return <>{quality.headline}</>
  if (availability?.reason) return <>{availability.reason}</>
  return <>暂无可展开的复盘结论，等待更多预测样本沉淀。</>
}

export default function PredictionReviewPanel({ data, loading }: { data: PredictionHistoryResponse | null; loading: boolean }) {
  const hasDetails = !!(
    data?.failure_analysis
    || (data?.agent_review && data.agent_review.status !== 'waiting_for_samples')
    || data?.deviation_cases?.some(item => item.error_pct != null)
  )
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div style={{display:'flex', flexDirection:'column', gap:10, marginBottom:12}}>
      <PredictionQualityBadges data={data} loading={loading} />
      <PredictionEvaluationStatusCard data={data} loading={loading} />

      {hasDetails && (
        <div style={{border:'1px solid var(--border)', borderRadius:8, background:'rgba(255,255,255,0.018)', overflow:'hidden'}}>
          <button
            type="button"
            onClick={() => setExpanded(prev => !prev)}
            style={{
              width:'100%',
              border:'none',
              background:'transparent',
              color:'var(--text)',
              cursor:'pointer',
              padding:'8px 10px',
              display:'flex',
              justifyContent:'space-between',
              gap:12,
              alignItems:'center',
              textAlign:'left',
            }}
          >
            <span style={{display:'flex', flexDirection:'column', gap:3, minWidth:0}}>
              <span style={{fontSize:13, fontWeight:700, display:'inline-flex', alignItems:'center', gap:6}}>复盘与可信度 <HelpTooltip {...helpTips.tradeReview}><HelpIcon /></HelpTooltip></span>
              <span style={{fontSize:11, color:'var(--text-muted)', lineHeight:1.45, overflow:'hidden', textOverflow:'ellipsis'}}>
                <ReviewHeadline data={data} />
              </span>
            </span>
            <span style={{fontSize:11, color:'var(--text-muted)', whiteSpace:'nowrap'}}>{expanded ? '收起' : '展开'}</span>
          </button>

          {expanded && (
            <div style={{display:'flex', flexDirection:'column', gap:10, padding:10, borderTop:'1px solid var(--border)'}}>
              <FailureAnalysisPanel analysis={data?.failure_analysis} />
              <AgentReviewPanel review={data?.agent_review} />
              <PredictionDeviationTable cases={data?.deviation_cases} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}