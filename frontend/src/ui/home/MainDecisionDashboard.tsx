import React from 'react'
import {
  fetchDecisionSummary,
  type DecisionDashboardSummary,
  type DecisionRecommendation,
  type DecisionSummaryOptimizationItem,
} from '../../api/report'
import TomorrowPlaybookBoard from '../trade-playbook/TomorrowPlaybookBoard'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../../config/helpTips'

type MainDecisionDashboardProps = {
  current?: string
  onSelectSymbol: (symbol: string) => void
  onOpenDiagnostics?: (symbol: string) => void
}

const signalTone: Record<string, { bg: string; fg: string; border: string }> = {
  strong_buy: { bg: 'rgba(34,197,94,0.14)', fg: '#86efac', border: 'rgba(34,197,94,0.34)' },
  buy: { bg: 'rgba(20,184,166,0.14)', fg: '#5eead4', border: 'rgba(20,184,166,0.34)' },
  hold: { bg: 'rgba(148,163,184,0.12)', fg: '#cbd5e1', border: 'rgba(148,163,184,0.28)' },
  sell: { bg: 'rgba(251,146,60,0.13)', fg: '#fdba74', border: 'rgba(251,146,60,0.34)' },
  strong_sell: { bg: 'rgba(248,113,113,0.14)', fg: '#fca5a5', border: 'rgba(248,113,113,0.36)' },
}

function formatPercent(value: number | null | undefined, digits = 1, showSign = true) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  const normalized = Math.abs(value) <= 1 ? value * 100 : value
  return `${showSign && normalized > 0 ? '+' : ''}${normalized.toFixed(digits)}%`
}

function formatNumber(value: number | null | undefined, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return value.toFixed(digits)
}

function riskLabel(value: string | null | undefined) {
  const labels: Record<string, string> = { low: '低', medium: '中', high: '高', extreme: '极高' }
  return value ? labels[value] || value : '-'
}

function gateLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    candidate_allowed: '可进入观察',
    observation_only: '仅观察',
    blocked: '已阻断',
    waiting_for_samples: '等待样本',
    unknown: '未知',
  }
  return value ? labels[value] || value : '未知'
}

function verificationLabel(value: string | null | undefined) {
  const labels: Record<string, string> = { passed: '通过', warning: '需观察', failed: '未通过', pending: '等待中', unknown: '未知' }
  return value ? labels[value] || value : '未知'
}

function priorityLabel(value: string | null | undefined) {
  const labels: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return value ? labels[value] || value : '低'
}

function badgeStyle(signal?: string | null): React.CSSProperties {
  const tone = signalTone[signal || 'hold'] || signalTone.hold
  return {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '4px 10px',
    borderRadius: 999,
    border: `1px solid ${tone.border}`,
    background: tone.bg,
    color: tone.fg,
    fontSize: 12,
    fontWeight: 700,
    whiteSpace: 'nowrap',
  }
}

function metric(label: string, value: React.ReactNode, detail?: string, tip?: HelpTipKey) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        {label}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </div>
      <div style={{ color: 'var(--text)', fontSize: 18, fontWeight: 750, lineHeight: 1.1 }}>{value}</div>
      {detail && <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 5 }}>{detail}</div>}
    </div>
  )
}

function RecommendationRow({ item, active, onSelect }: { item: DecisionRecommendation; active: boolean; onSelect: (symbol: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item.symbol)}
      style={{
        width: '100%',
        display: 'grid',
        gridTemplateColumns: '36px minmax(120px,1fr) 96px 86px 86px',
        gap: 10,
        alignItems: 'center',
        border: active ? '1px solid rgba(99,102,241,0.65)' : '1px solid var(--border)',
        background: active ? 'rgba(99,102,241,0.14)' : 'rgba(255,255,255,0.025)',
        color: 'var(--text)',
        borderRadius: 8,
        padding: '10px 12px',
        cursor: 'pointer',
        textAlign: 'left',
      }}
    >
      <span style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 700 }}>#{item.rank}</span>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', fontWeight: 750, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name || item.symbol}</span>
        <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>{item.symbol}{item.sector ? ` / ${item.sector}` : ''}</span>
      </span>
      <span style={badgeStyle(item.decision_signal)}>{item.dashboard_label || item.decision_label || '观察'}</span>
      <span style={{ color: (item.expected_return ?? 0) >= 0 ? '#86efac' : '#fca5a5', fontWeight: 750 }}>{formatPercent(item.expected_return)}</span>
      <span style={{ color: 'var(--text-muted)', fontWeight: 650 }}>{formatNumber(item.composite_score, 0)}</span>
    </button>
  )
}

function OptimizationItem({ item }: { item: DecisionSummaryOptimizationItem }) {
  const color = item.priority === 'high' ? '#fca5a5' : item.priority === 'medium' ? '#fbbf24' : '#93c5fd'
  return (
    <div style={{ border: '1px solid var(--border)', background: 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
        <div style={{ color: 'var(--text)', fontWeight: 700, fontSize: 13 }}>{item.title}</div>
        <div style={{ color, fontSize: 11, fontWeight: 800 }}>{priorityLabel(item.priority)}</div>
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 6, lineHeight: 1.5 }}>{item.detail}</div>
    </div>
  )
}

export default function MainDecisionDashboard({ current, onSelectSymbol, onOpenDiagnostics }: MainDecisionDashboardProps) {
  const [summary, setSummary] = React.useState<DecisionDashboardSummary | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchDecisionSummary({ symbol: current, limit: 8, lookbackDays: 60, pinnedOnly: true, refresh: false })
      setSummary(data)
    } catch (err: any) {
      setError(err?.message || '决策摘要加载失败')
    } finally {
      setLoading(false)
    }
  }, [current])

  React.useEffect(() => {
    load()
  }, [load])

  const selected = summary?.selected_stock
  const selectedDecision = selected?.trade_decision
  const recommendations = summary?.recommendations || []
  const headline = selectedDecision
    ? `${selected?.name || selected?.symbol} 当前为${selectedDecision.signal_label}辅助判断`
    : recommendations.length > 0
      ? `今日优先关注 ${recommendations[0].name || recommendations[0].symbol}`
      : '暂无可展示的决策摘要'
  const primaryReason = selectedDecision?.reasons?.[0]?.evidence || summary?.model_review_summary?.headline || '等待更多预测、新闻和市场证据。'

  return (
    <>
    <TomorrowPlaybookBoard current={current} onSelectSymbol={onSelectSymbol} />
    <section style={{ padding: 12 }}>
      <div
        style={{
          border: '1px solid var(--border)',
          background: 'linear-gradient(135deg, rgba(17,24,39,0.96), rgba(15,23,42,0.88))',
          borderRadius: 8,
          boxShadow: '0 18px 50px -34px rgba(0,0,0,0.85)',
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.35fr) minmax(300px,0.95fr)', gap: 0 }}>
          <div style={{ padding: 18, borderRight: '1px solid var(--border)', minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', marginBottom: 14 }}>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 700, letterSpacing: 0.4, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  一屏式决策摘要
                  <HelpTooltip {...helpTips.decisionSummary}><HelpIcon /></HelpTooltip>
                </div>
                <h2 style={{ margin: '6px 0 0', color: 'var(--text)', fontSize: 24, lineHeight: 1.22, fontWeight: 850 }}>{headline}</h2>
              </div>
              <HelpTooltip {...helpTips.refreshSummary}>
                <span style={{ display: 'inline-flex' }}>
                  <button type="button" onClick={load} className="dark-btn dark-btn-secondary" disabled={loading} style={{ opacity: loading ? 0.65 : 1 }}>
                    {loading ? '更新中' : '刷新摘要'}
                  </button>
                </span>
              </HelpTooltip>
            </div>

            {error ? (
              <div style={{ border: '1px solid rgba(248,113,113,0.35)', background: 'rgba(248,113,113,0.08)', color: '#fecaca', borderRadius: 8, padding: 12, fontSize: 13 }}>
                新决策摘要暂不可用，旧首页模块仍可继续使用。{error.slice(0, 160)}
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
                  <span style={badgeStyle(selectedDecision?.signal)}>{selectedDecision?.signal_label || '观察'}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>{primaryReason}</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0,1fr))', gap: 14 }}>
                  {metric('置信度', selectedDecision ? formatPercent(selectedDecision.confidence, 0, false) : '-', summary?.prediction_quality_summary ? `平均质量 ${formatNumber(summary.prediction_quality_summary.average_quality_score, 1)}` : undefined, 'confidence')}
                  {metric('预期收益', selectedDecision ? formatPercent(selectedDecision.expected_return) : '-', selectedDecision?.applicable_horizon ? `周期 ${selectedDecision.applicable_horizon}` : undefined, 'forecastReturn')}
                  {metric('风险', riskLabel(selectedDecision?.risk_level), selectedDecision?.risk_score != null ? `评分 ${formatNumber(selectedDecision.risk_score, 0)}` : undefined, 'riskScore')}
                  {metric('数据健康', summary ? `${summary.data_health.with_signal}/${summary.data_health.returned_count}` : '-', summary?.data_health.warnings?.[0], 'dataHealth')}
                </div>
              </>
            )}
          </div>

          <div style={{ padding: 18, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div>
                <div style={{ color: 'var(--text)', fontSize: 15, fontWeight: 800, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  推荐队列
                  <HelpTooltip {...helpTips.recommendationQueue}><HelpIcon /></HelpTooltip>
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 3 }}>由后端聚合排序，质量不足会降级为观察</div>
              </div>
              {selected?.symbol && onOpenDiagnostics && (
                <HelpTooltip {...helpTips.diagnosticButton}>
                  <button type="button" className="dark-btn dark-btn-secondary" onClick={() => onOpenDiagnostics(selected.symbol)}>
                    诊断
                  </button>
                </HelpTooltip>
              )}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {recommendations.slice(0, 5).map(item => (
                <RecommendationRow key={item.symbol} item={item} active={item.symbol === selected?.symbol || item.symbol === current} onSelect={onSelectSymbol} />
              ))}
              {!loading && recommendations.length === 0 && (
                <div style={{ color: 'var(--text-muted)', border: '1px dashed var(--border)', borderRadius: 8, padding: 14, fontSize: 13 }}>
                  还没有可排序的置顶股票。可以先在自选管理里置顶股票，旧模块仍会显示已有数据。
                </div>
              )}
            </div>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)', padding: 14, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 12 }}>
          <div>
            <div style={{ color: 'var(--text)', fontWeight: 800, fontSize: 14, marginBottom: 8, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              模型复盘
              <HelpTooltip {...helpTips.modelReviewSummary}><HelpIcon /></HelpTooltip>
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.55 }}>
              {summary?.model_review_summary?.headline || '等待预测复盘样本生成模型状态摘要。'}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
              <HelpTooltip {...helpTips.dataGate}><span style={badgeStyle('hold')}>门禁 {gateLabel(summary?.model_review_summary?.gate_status)}</span></HelpTooltip>
              <HelpTooltip {...helpTips.verificationStatus}><span style={badgeStyle('hold')}>核实 {verificationLabel(summary?.model_review_summary?.verification_status)}</span></HelpTooltip>
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text)', fontWeight: 800, fontSize: 14, marginBottom: 8, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              下一步优化
              <HelpTooltip {...helpTips.nextOptimization}><HelpIcon /></HelpTooltip>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 8 }}>
              {(summary?.optimization_plan || []).slice(0, 2).map((item, index) => <OptimizationItem key={`${item.type}-${index}`} item={item} />)}
              {!summary?.optimization_plan?.length && <OptimizationItem item={{ type: 'loading', priority: 'low', title: '等待摘要', detail: '决策摘要加载后会展示模型和数据侧的下一步。' }} />}
            </div>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)', padding: '10px 14px', color: 'var(--text-muted)', fontSize: 11, lineHeight: 1.5 }}>
          {summary?.disclaimer || '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。'}
        </div>
      </div>
    </section>
    </>
  )
}