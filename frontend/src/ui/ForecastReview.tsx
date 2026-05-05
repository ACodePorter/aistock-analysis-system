import React, { useEffect, useState } from 'react'
import { fetchModelLifecycle, type ModelLifecycleEventItem, type ModelLifecycleResponse } from '../api/modelLifecycle'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../config/helpTips'

interface ForecastRecord {
  date: string
  model: string
  predicted: number | null
  lower: number | null
  upper: number | null
  actual: number | null
  error_pct: number | null
  direction_ok: boolean | null
}

interface ForecastStats {
  total_forecasts: number
  matched: number
  unmatched: number
  avg_mape: number | null
  direction_accuracy: number | null
  direction_total: number
}

interface ForecastItem {
  symbol: string
  name: string
  records: ForecastRecord[]
  stats: ForecastStats
}

export default function ForecastReview() {
  const [items, setItems] = useState<ForecastItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'records' | 'lifecycle'>('records')
  const [lifecycleBySymbol, setLifecycleBySymbol] = useState<Record<string, ModelLifecycleResponse>>({})
  const [lifecycleLoading, setLifecycleLoading] = useState<Record<string, boolean>>({})
  const [lifecycleError, setLifecycleError] = useState<Record<string, string | undefined>>({})

  async function load() {
    try {
      setLoading(true); setError(undefined)
      const r = await fetch(buildApiUrl(API_ENDPOINTS.FORECAST_REVIEW + '?limit=30'))
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setItems(Array.isArray(data.items) ? data.items : [])
      // auto-expand first item
      if (data.items?.length && !expandedSymbol) setExpandedSymbol(data.items[0].symbol)
    } catch (e: any) { setError(String(e?.message || e)) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (!expandedSymbol || activeTab !== 'lifecycle' || lifecycleBySymbol[expandedSymbol] || lifecycleLoading[expandedSymbol]) return
    setLifecycleLoading(prev => ({ ...prev, [expandedSymbol]: true }))
    setLifecycleError(prev => ({ ...prev, [expandedSymbol]: undefined }))
    fetchModelLifecycle(expandedSymbol, 30)
      .then(data => setLifecycleBySymbol(prev => ({ ...prev, [expandedSymbol]: data })))
      .catch((e: any) => setLifecycleError(prev => ({ ...prev, [expandedSymbol]: String(e?.message || e) })))
      .finally(() => setLifecycleLoading(prev => ({ ...prev, [expandedSymbol]: false })))
  }, [activeTab, expandedSymbol, lifecycleBySymbol, lifecycleLoading])

  if (loading) return <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>加载中...</div>
  if (error) return <div style={{ fontSize: 12, color: 'var(--accent-red)', padding: 8 }}>错误：{error}</div>
  if (!items.length) return <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>暂无可复盘的预测数据（需置顶股票且有历史预测记录）</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map(item => {
        const isExpanded = expandedSymbol === item.symbol
        const s = item.stats
        return (
          <div key={item.symbol} style={{
            border: '1px solid var(--border)', borderRadius: 8,
            background: 'var(--surface-dark)', overflow: 'hidden',
          }}>
            {/* Header - clickable */}
            <div
              onClick={() => setExpandedSymbol(isExpanded ? null : item.symbol)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '6px 12px', cursor: 'pointer',
                background: 'rgba(255,255,255,0.02)',
                borderBottom: isExpanded ? '1px solid var(--border)' : 'none',
              }}
            >
              <span style={{ fontSize: 11, color: 'var(--text-muted)', userSelect: 'none' }}>
                {isExpanded ? '▼' : '▶'}
              </span>
              <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)' }}>
                {item.name}
                <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400, marginLeft: 4 }}>({item.symbol})</span>
              </span>

              {/* Stats pills */}
              <div style={{ display: 'flex', gap: 4, marginLeft: 'auto', flexWrap: 'wrap' }}>
                {s.avg_mape != null && (
                  <StatPill label="MAPE" value={`${s.avg_mape}%`} color={mapeColor(s.avg_mape)} />
                )}
                {s.direction_accuracy != null && (
                  <StatPill label="方向" value={`${s.direction_accuracy}%`} color={dirColor(s.direction_accuracy)} />
                )}
                <StatPill label="比对" value={`${s.matched}/${s.total_forecasts}`} />
              </div>
            </div>

            {/* Expanded: records table / lifecycle timeline */}
            {isExpanded && (
              <div>
                <div style={{ display: 'flex', gap: 6, padding: '8px 10px 0', alignItems: 'center' }}>
                  <TabButton active={activeTab === 'records'} onClick={() => setActiveTab('records')} tip="historicalPrediction">预测记录</TabButton>
                  <TabButton active={activeTab === 'lifecycle'} onClick={() => setActiveTab('lifecycle')} tip="modelStatus">模型生命周期</TabButton>
                </div>

                {activeTab === 'records' ? (
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{
                      width: '100%', borderCollapse: 'collapse', fontSize: 12,
                    }}>
                      <thead>
                        <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                          <Th tip="actualClose">日期</Th>
                          <Th align="right" tip="aiPredictionLine">预测</Th>
                          <Th align="right" tip="intervalHitRate">区间</Th>
                          <Th align="right" tip="actualClose">实际</Th>
                          <Th align="right" tip="mape">误差%</Th>
                          <Th align="center" tip="directionAccuracy">方向</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {item.records.map((rec, idx) => (
                          <tr key={idx} style={{
                            borderTop: '1px solid rgba(255,255,255,0.04)',
                            background: idx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                          }}>
                            <Td>{rec.date}</Td>
                            <Td align="right">{fmtNum(rec.predicted)}</Td>
                            <Td align="right" muted>{rec.lower != null && rec.upper != null ? `${fmtNum(rec.lower)}~${fmtNum(rec.upper)}` : '-'}</Td>
                            <Td align="right" bold>{fmtNum(rec.actual)}</Td>
                            <Td align="right" color={rec.error_pct != null ? mapeColor(rec.error_pct) : undefined}>
                              {rec.error_pct != null ? `${rec.error_pct}%` : '-'}
                            </Td>
                            <Td align="center">
                              {rec.direction_ok === true ? '✅' : rec.direction_ok === false ? '❌' : '-'}
                            </Td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <LifecycleTimeline
                    data={lifecycleBySymbol[item.symbol]}
                    loading={!!lifecycleLoading[item.symbol]}
                    error={lifecycleError[item.symbol]}
                  />
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ─── Sub-components ─── */
function StatPill({ label, value, color, tip }: { label: string; value: string; color?: string; tip?: HelpTipKey }) {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      padding: '1px 7px', borderRadius: 4,
      background: 'rgba(255,255,255,0.03)', fontSize: 11,
    }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: color || 'var(--text)' }}>{value}</span>
    </div>
  )
}

function TabButton({ active, onClick, children, tip }: { active: boolean; onClick: () => void; children: React.ReactNode; tip?: HelpTipKey }) {
  return (
    <HelpTooltip {...(tip ? helpTips[tip] : {})}>
      <button
        onClick={onClick}
        style={{
          border: `1px solid ${active ? 'rgba(96,165,250,0.55)' : 'var(--border)'}`,
          borderRadius: 6,
          background: active ? 'rgba(96,165,250,0.14)' : 'rgba(255,255,255,0.02)',
          color: active ? '#93c5fd' : 'var(--text-muted)',
          padding: '3px 9px',
          fontSize: 12,
          cursor: 'pointer',
        }}
      >
        {children}
      </button>
    </HelpTooltip>
  )
}

function LifecycleTimeline({ data, loading, error }: {
  data?: ModelLifecycleResponse
  loading: boolean
  error?: string
}) {
  if (loading) return <div style={{ padding: 12, fontSize: 12, color: 'var(--text-muted)' }}>加载模型生命周期...</div>
  if (error) return <div style={{ padding: 12, fontSize: 12, color: '#f87171' }}>生命周期加载失败：{error}</div>
  if (!data || !data.items.length) return <div style={{ padding: 12, fontSize: 12, color: 'var(--text-muted)' }}>暂无模型生命周期记录</div>

  return (
    <div style={{ padding: '8px 12px 12px', fontSize: 12 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <StatPill label="当前" value={modelStatusLabel(data.summary.active_status)} color={modelStatusColor(data.summary.active_status)} tip="modelStatus" />
        <span style={{ color: 'var(--text-muted)' }}>{data.summary.active_reason}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {data.items.map(event => (
          <LifecycleEvent key={event.id} event={event} />
        ))}
      </div>
    </div>
  )
}

function LifecycleEvent({ event }: { event: ModelLifecycleEventItem }) {
  const color = eventColor(event.event_type)
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '118px 1fr',
      gap: 10,
      padding: '7px 0',
      borderTop: '1px solid rgba(255,255,255,0.05)',
    }}>
      <div style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{formatDateTime(event.created_at)}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color, fontWeight: 600 }}>{eventTypeLabel(event.event_type)}</span>
          {event.model_name && <span style={{ color: 'var(--text-muted)' }}>{event.model_name}</span>}
          {event.score_before != null && event.score_after != null && (
            <span style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
              {event.score_before.toFixed(3)} → {event.score_after.toFixed(3)}
            </span>
          )}
        </div>
        {event.trigger_reason && (
          <div style={{ marginTop: 2, color: 'var(--text-muted)', lineHeight: 1.45 }}>{event.trigger_reason}</div>
        )}
      </div>
    </div>
  )
}

function Th({ children, align = 'left', tip }: { children: React.ReactNode; align?: string; tip?: HelpTipKey }) {
  return (
    <th style={{
      padding: '5px 8px', textAlign: align as any,
      fontSize: 11, fontWeight: 500, color: 'var(--text-muted)',
      whiteSpace: 'nowrap',
    }}>
      <span style={{display:'inline-flex', alignItems:'center', gap:5, justifyContent: align === 'right' ? 'flex-end' : align === 'center' ? 'center' : 'flex-start', width:'100%'}}>
        {children}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </span>
    </th>
  )
}

function Td({ children, align = 'left', muted, bold, color }: {
  children: React.ReactNode; align?: string; muted?: boolean; bold?: boolean; color?: string
}) {
  return (
    <td style={{
      padding: '4px 8px', textAlign: align as any,
      fontVariantNumeric: 'tabular-nums',
      color: color || (muted ? 'var(--text-muted)' : 'var(--text)'),
      fontWeight: bold ? 600 : 400,
      whiteSpace: 'nowrap',
    }}>{children}</td>
  )
}

/* ─── Helpers ─── */
function fmtNum(v: number | null | undefined): string {
  if (v == null) return '-'
  return v.toFixed(2)
}

function mapeColor(mape: number): string {
  if (mape <= 3) return '#34d399'    // green - excellent
  if (mape <= 5) return '#60a5fa'    // blue - good
  if (mape <= 10) return '#fbbf24'   // yellow - fair
  return '#f87171'                    // red - poor
}

function dirColor(acc: number): string {
  if (acc >= 70) return '#34d399'
  if (acc >= 50) return '#fbbf24'
  return '#f87171'
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

function eventTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    failure_detected: '偏差告警',
    retrain_triggered: '触发重训',
    retrain_completed: '重训完成',
    retrain_stagnated: '优化停滞',
    feature_check: '特征检查',
    ab_test: 'A/B 对比',
  }
  return labels[type] || type
}

function eventColor(type: string): string {
  if (type === 'retrain_completed') return '#34d399'
  if (type === 'retrain_stagnated' || type === 'failure_detected') return '#f87171'
  if (type === 'retrain_triggered') return '#818cf8'
  return '#fbbf24'
}

function modelStatusLabel(status: string | null | undefined): string {
  const labels: Record<string, string> = {
    optimized: '已优化',
    retained: '保留旧模型',
    needs_retrain: '待训练',
    stagnated: '优化停滞',
    unknown: '无记录',
  }
  return labels[status || 'unknown'] || String(status)
}

function modelStatusColor(status: string | null | undefined): string {
  if (status === 'optimized') return '#34d399'
  if (status === 'stagnated') return '#f87171'
  if (status === 'needs_retrain') return '#818cf8'
  if (status === 'retained') return '#fbbf24'
  return 'var(--text-muted)'
}
