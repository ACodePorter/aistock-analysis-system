import React, { useState } from 'react'
import type { FactorContext, FeatureSnapshot, StockInsightResponse, TradeDecision } from '../api/report'
import HelpTooltip, { HelpIcon } from './components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../config/helpTips'

interface Props {
  insight: StockInsightResponse | null
  loading?: boolean
}

const ACTION_MAP: Record<string, { text: string; emoji: string; bg: string; fg: string; border: string }> = {
  strong_buy:  { text: '强买入', emoji: '🔥', bg: 'var(--action-buy-bg)', fg: 'var(--action-buy-fg)', border: 'var(--action-buy-border)' },
  buy:         { text: '买入',     emoji: '📈', bg: 'var(--action-buy-bg)', fg: 'var(--action-buy-fg)', border: 'var(--action-buy-border)' },
  hold:        { text: '观望',     emoji: '⏸',  bg: 'var(--action-hold-bg)', fg: 'var(--action-hold-fg)', border: 'var(--action-hold-border)' },
  sell:        { text: '卖出',     emoji: '📉', bg: 'var(--action-sell-bg)', fg: 'var(--action-sell-fg)', border: 'var(--action-sell-border)' },
  strong_sell: { text: '强卖出', emoji: '⚠️', bg: 'var(--action-sell-bg)', fg: 'var(--action-sell-fg)', border: 'var(--action-sell-border)' },
}

const RISK_MAP: Record<string, { text: string; color: string }> = {
  low: { text: '低', color: 'var(--risk-low)' },
  medium: { text: '中', color: 'var(--risk-medium)' },
  high: { text: '高', color: 'var(--risk-high)' },
  extreme: { text: '极高', color: 'var(--action-sell-fg)' },
}

function formatPercent(value?: number | null, digits = 1) {
  if (value == null || Number.isNaN(value)) return '-'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function formatPrice(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return value.toFixed(2)
}

function formatRatio(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return value.toFixed(2)
}

function ConfidenceBadge({ confidence, accuracy }: { confidence?: number | null; accuracy?: number | null }) {
  const val = confidence ?? accuracy
  if (val == null) return null
  const pct = val > 1 ? val : val * 100
  const level = pct >= 70 ? { text: '高', bg: 'var(--action-buy-bg)', fg: 'var(--action-buy-fg)' }
    : pct >= 50 ? { text: '中', bg: 'var(--action-hold-bg)', fg: 'var(--action-hold-fg)' }
    : { text: '低', bg: 'var(--action-sell-bg)', fg: 'var(--action-sell-fg)' }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: level.bg, color: level.fg,
    }}>
      置信度: {level.text} ({pct.toFixed(0)}%)
    </span>
  )
}

function ProbBar({ prob }: { prob: number }) {
  const pct = prob * 100
  const color = pct >= 60 ? 'var(--positive)' : pct >= 45 ? 'var(--warning)' : 'var(--risk-high)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 3, background: color, transition: 'width 0.5s ease' }} />
      </div>
      <span style={{ fontSize: 13, fontWeight: 700, color, minWidth: 48, textAlign: 'right' }}>
        {pct.toFixed(1)}%
      </span>
    </div>
  )
}

function FactorBar({ label, value, maxVal = 1 }: { label: string; value: number; maxVal?: number }) {
  const normalizedValue = maxVal === 1 && value > 1 ? value / 100 : value
  const pct = Math.min(100, Math.max(0, (normalizedValue / maxVal) * 100))
  const color = pct >= 60 ? 'var(--positive)' : pct >= 40 ? 'var(--warning)' : 'var(--risk-high)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
      <span style={{ minWidth: 48, color: 'var(--text-muted, #6b7280)' }}>{label}</span>
      <div style={{ flex: 1, height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 2, background: color, transition: 'width 0.4s ease' }} />
      </div>
      <span style={{ minWidth: 32, textAlign: 'right', color, fontWeight: 600 }}>{pct.toFixed(0)}</span>
    </div>
  )
}

function DecisionMetric({ label, value, tone, tip }: { label: string; value: React.ReactNode; tone?: string; tip?: HelpTipKey }) {
  return (
    <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--border)', minWidth: 0 }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted, #9ca3af)', marginBottom: 3, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        {label}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </div>
      <div style={{ fontSize: 14, fontWeight: 700, color: tone || 'var(--text, #1f2937)', overflowWrap: 'anywhere' }}>{value}</div>
    </div>
  )
}

function TradeDecisionPanel({ decision }: { decision: TradeDecision }) {
  const risk = RISK_MAP[decision.risk_level] || RISK_MAP.medium
  const returnTone = (decision.expected_return ?? 0) >= 0 ? '#16a34a' : '#dc2626'
  return (
    <div style={{ padding: '0 12px 10px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        <DecisionMetric label="适用周期" value={decision.applicable_horizon || '-'} tip="targetHorizon" />
        <DecisionMetric label="风险等级" value={risk.text} tone={risk.color} tip="riskLevel" />
        <DecisionMetric label="建议仓位" value={decision.suggested_position_pct?.label || '-'} tip="suggestedPosition" />
        <DecisionMetric label="预期下行" value={formatPercent(decision.expected_downside, 1)} tone="#dc2626" tip="downsideRisk" />
        <DecisionMetric label="收益风险比" value={formatRatio(decision.risk_reward_ratio)} tip="riskRewardRatio" />
        <DecisionMetric label="失效条件" value={decision.invalidation_condition || '-'} tip="planInvalidation" />
        <DecisionMetric label="止损位" value={formatPrice(decision.stop_loss_price)} tone="#dc2626" tip="stopLossPrice" />
        <DecisionMetric label="止盈位" value={formatPrice(decision.take_profit_price)} tone="#16a34a" tip="takeProfitPrice1" />
        <DecisionMetric label="预期收益" value={formatPercent(decision.expected_return, 2)} tone={returnTone} tip="forecastReturn" />
      </div>
      {decision.reasons.length > 0 && (
        <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border, #e5e7eb)' }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted, #9ca3af)', marginBottom: 6 }}>决策理由</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {decision.reasons.map((reason, index) => (
              <div key={`${reason.type}-${index}`} style={{ display: 'grid', gridTemplateColumns: '72px 1fr 42px', gap: 8, alignItems: 'center', fontSize: 11, lineHeight: 1.45 }}>
                <span style={{ color: 'var(--text, #374151)', fontWeight: 600 }}>{reason.label}</span>
                <span style={{ color: 'var(--text-muted, #6b7280)' }}>{reason.evidence}</span>
                <span style={{ textAlign: 'right', color: 'var(--text-muted, #9ca3af)' }}>{(reason.weight * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div style={{ marginTop: 8, padding: '7px 8px', borderRadius: 6, background: 'rgba(245,158,11,0.1)', color: 'var(--warning)', fontSize: 10, lineHeight: 1.5 }}>
        {decision.disclaimer}
      </div>
    </div>
  )
}

function FactorContextPanel({ context }: { context: FactorContext }) {
  const sentimentColor = context.news.avg_sentiment == null ? 'var(--text-muted, #9ca3af)'
    : context.news.avg_sentiment >= 0.25 ? '#16a34a'
    : context.news.avg_sentiment <= -0.25 ? '#dc2626'
    : '#d97706'
  const breadthColor = context.macro.breadth_ratio == null ? 'var(--text-muted, #9ca3af)'
    : context.macro.breadth_ratio >= 0.58 ? '#16a34a'
    : context.macro.breadth_ratio <= 0.42 ? '#dc2626'
    : '#d97706'
  return (
    <div style={{ padding: '0 12px 10px' }}>
      <div style={{ borderTop: '1px solid var(--border, #e5e7eb)', paddingTop: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted, #9ca3af)', marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}>因子上下文 <HelpTooltip {...helpTips.factorContext}><HelpIcon /></HelpTooltip></div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
          <DecisionMetric label={`近${context.news.window_days}日新闻`} value={`${context.news.article_count} 条`} tip="newsCount" />
          <DecisionMetric label="新闻情绪" value={context.news.sentiment_label} tone={sentimentColor} tip="agentNewsSentiment" />
          <DecisionMetric label="市场广度" value={context.macro.breadth_label} tone={breadthColor} tip="marketBreadth" />
        </div>
        {context.summary.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {context.summary.map((item, index) => (
              <div key={index} style={{ fontSize: 11, lineHeight: 1.45, color: 'var(--text, #374151)' }}>• {item}</div>
            ))}
          </div>
        )}
        {context.quant_factors.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {context.quant_factors.slice(0, 5).map(factor => (
              <span key={factor.key} style={{ fontSize: 10, border: '1px solid var(--border, #e5e7eb)', borderRadius: 4, padding: '2px 6px', color: 'var(--text-muted, #6b7280)' }}>
                {factor.label}: <strong style={{ color: 'var(--text, #374151)' }}>{factor.impact}</strong>
              </span>
            ))}
          </div>
        )}
        {context.news.headlines.length > 0 && (
          <div style={{ marginTop: 8, color: 'var(--text-muted, #6b7280)', fontSize: 10, lineHeight: 1.45 }}>
            最新新闻：{context.news.headlines[0].title}
          </div>
        )}
        {!!context.warnings.length && (
          <div style={{ marginTop: 6, color: '#d97706', fontSize: 10, lineHeight: 1.45 }}>{context.warnings[0]}</div>
        )}
      </div>
    </div>
  )
}

function FeatureSnapshotPanel({ snapshot }: { snapshot: FeatureSnapshot }) {
  const score = snapshot.completeness_score ?? 0
  const scoreTone = score >= 80 ? '#16a34a' : score >= 60 ? '#d97706' : '#dc2626'
  const available = snapshot.coverage.filter(item => item.available)
  const missing = snapshot.coverage.filter(item => !item.available)
  return (
    <div style={{ padding: '0 12px 10px' }}>
      <div style={{ borderTop: '1px solid var(--border, #e5e7eb)', paddingTop: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted, #9ca3af)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>复盘快照 <HelpTooltip {...helpTips.featureSnapshot}><HelpIcon /></HelpTooltip></div>
          <div style={{ fontSize: 10, color: 'var(--text-muted, #9ca3af)', overflowWrap: 'anywhere' }}>{snapshot.snapshot_id}</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
          <DecisionMetric label="快照日期" value={snapshot.as_of_date || '-'} tip="featureSnapshot" />
          <DecisionMetric label="输入覆盖率" value={`${score.toFixed(1)}%`} tone={scoreTone} tip="inputCoverage" />
          <DecisionMetric label="目标日期" value={snapshot.prediction?.target_date || '-'} tip="historicalPrediction" />
        </div>
        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {available.map(item => (
            <span key={item.label} style={{ fontSize: 10, borderRadius: 4, padding: '2px 6px', background: 'var(--action-buy-bg)', color: 'var(--action-buy-fg)' }}>
              {item.label}
            </span>
          ))}
          {missing.map(item => (
            <span key={item.label} style={{ fontSize: 10, borderRadius: 4, padding: '2px 6px', background: 'var(--action-sell-bg)', color: 'var(--action-sell-fg)' }}>
              缺{item.label}
            </span>
          ))}
        </div>
        {snapshot.warnings[0] && (
          <div style={{ marginTop: 6, fontSize: 10, lineHeight: 1.45, color: '#d97706' }}>{snapshot.warnings[0]}</div>
        )}
        <div style={{ marginTop: 5, fontSize: 10, lineHeight: 1.45, color: 'var(--text-muted, #6b7280)' }}>{snapshot.disclaimer}</div>
      </div>
    </div>
  )
}

export default function PredictionInsightCard({ insight, loading }: Props) {
  const [expanded, setExpanded] = useState(false)

  if (loading) {
    return (
      <div style={{ padding: 16, borderRadius: 12, border: '1px solid var(--border)', background: 'var(--bg-card)' }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted, #9ca3af)', textAlign: 'center' }}>
          AI 洞察加载中...
        </div>
      </div>
    )
  }

  if (!insight || !insight.has_data) {
    return (
      <div style={{ padding: 12, borderRadius: 12, border: '1px dashed var(--border)', background: 'var(--bg-card)' }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted, #9ca3af)', textAlign: 'center' }}>
          🤖 暂无 AI 量化洞察数据，请先训练模型并生成信号
        </div>
      </div>
    )
  }

  const decision = insight.trade_decision
  const actionKey = decision?.signal || insight.signal?.action
  const action = actionKey ? ACTION_MAP[actionKey] || { text: actionKey, emoji: '❓', bg: 'var(--badge-neutral-bg)', fg: 'var(--badge-neutral-fg)', border: 'var(--badge-neutral-border)' } : null
  const prob = insight.prediction?.direction_prob_up
  const ret = decision?.expected_return ?? insight.prediction?.predicted_return
  const score = insight.signal?.score
  const risk = decision?.risk_score ?? insight.signal?.risk_score
  const signalDate = insight.signal?.signal_date || decision?.generated_at?.slice(0, 10)

  // Factor labels mapping
  const factorLabels: Record<string, string> = {
    direction_prob_score: '方向概率',
    expected_return_score: '预期收益',
    risk_penalty_score: '风险惩罚',
    momentum_score: '动量',
    fund_flow_score: '资金流',
    sentiment_score: '情绪面',
    technical_score: '技术面',
  }

  const factorEntries = Object.entries(insight.factors || {})
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => ({ key: k, label: factorLabels[k] || k, value: v as number }))

  return (
    <div style={{
      borderRadius: 12,
      border: `1px solid ${action?.border || 'var(--border, #e5e7eb)'}`,
      background: 'var(--bg-card)',
      overflow: 'hidden',
    }}>
      {/* 头部：操作建议 */}
      <div style={{
        padding: '10px 12px',
        background: action?.bg || 'rgba(59,130,246,0.04)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        borderBottom: '1px solid var(--border, #e5e7eb)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 14 }}>🤖</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text, #1f2937)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            AI 交易辅助建议
            <HelpTooltip {...helpTips.aiTradeInsight}><HelpIcon /></HelpTooltip>
          </span>
          {signalDate && (
            <span style={{ fontSize: 10, color: 'var(--text-muted, #9ca3af)' }}>{signalDate}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ConfidenceBadge confidence={decision?.confidence ?? insight.prediction?.confidence} accuracy={insight.model_accuracy} />
          {action && (
            <span style={{
              fontSize: 14, fontWeight: 700, padding: '4px 12px', borderRadius: 6,
              background: action.bg, color: action.fg,
            }}>
              {action.emoji} {action.text}
            </span>
          )}
        </div>
      </div>

      {/* 核指标区域 */}
      <div style={{ padding: '10px 12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {/* 上涨概率 */}
        <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted, #9ca3af)', marginBottom: 2, display: 'inline-flex', alignItems: 'center', gap: 5 }}>📊 上涨概率 <HelpTooltip {...helpTips.upsideProbability}><HelpIcon /></HelpTooltip></div>
          {prob != null ? <ProbBar prob={prob} /> : <span style={{ fontSize: 12, color: '#9ca3af' }}>-</span>}
        </div>
        {/* 预期收益 */}
        <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted, #9ca3af)', marginBottom: 2, display: 'inline-flex', alignItems: 'center', gap: 5 }}>💰 预期收益率 <HelpTooltip {...helpTips.forecastReturn}><HelpIcon /></HelpTooltip></div>
          {ret != null ? (
            <span style={{ fontSize: 15, fontWeight: 700, color: ret >= 0 ? '#16a34a' : '#dc2626' }}>
              {ret >= 0 ? '+' : ''}{(ret * 100).toFixed(2)}%
            </span>
          ) : <span style={{ fontSize: 12, color: '#9ca3af' }}>-</span>}
        </div>
        {/* 综合评分 */}
        <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted, #9ca3af)', marginBottom: 2, display: 'inline-flex', alignItems: 'center', gap: 5 }}>🎯 综合评分 <HelpTooltip {...helpTips.compositeScore}><HelpIcon /></HelpTooltip></div>
          {score != null ? (
            <span style={{ fontSize: 15, fontWeight: 700, color: score >= 62 ? '#16a34a' : score >= 45 ? '#d97706' : '#dc2626' }}>
              {score.toFixed(1)}
            </span>
          ) : <span style={{ fontSize: 12, color: '#9ca3af' }}>-</span>}
        </div>
        {/* 风险评分 */}
        <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(255,255,255,0.025)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted, #9ca3af)', marginBottom: 2, display: 'inline-flex', alignItems: 'center', gap: 5 }}>⚡ 风险评分 <HelpTooltip {...helpTips.riskScore}><HelpIcon /></HelpTooltip></div>
          {risk != null ? (
            <span style={{ fontSize: 15, fontWeight: 700, color: risk <= 30 ? '#16a34a' : risk <= 60 ? '#d97706' : '#dc2626' }}>
              {risk.toFixed(1)}
              <span style={{ fontSize: 10, fontWeight: 400, marginLeft: 4, color: 'var(--text-muted, #9ca3af)' }}>
                {risk <= 30 ? '低风险' : risk <= 60 ? '中等风险' : '高风险'}
              </span>
            </span>
          ) : <span style={{ fontSize: 12, color: '#9ca3af' }}>-</span>}
        </div>
      </div>

      {decision && <TradeDecisionPanel decision={decision} />}
      {insight.feature_snapshot && <FeatureSnapshotPanel snapshot={insight.feature_snapshot} />}
      {insight.factor_context && <FactorContextPanel context={insight.factor_context} />}

      {/* AI 解释 */}
      {insight.explanations.length > 0 && (
        <div style={{ padding: '6px 12px 10px', borderTop: '1px solid var(--border, #e5e7eb)' }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted, #9ca3af)', marginBottom: 4 }}>💡 AI 分析要点</div>
          {insight.explanations.map((exp, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text, #374151)', padding: '2px 0', lineHeight: 1.5 }}>
              • {exp}
            </div>
          ))}
        </div>
      )}

      {/* 展开：因子分解 + 特征重要性 */}
      {(factorEntries.length > 0 || insight.feature_importance.length > 0) && (
        <>
          <div
            style={{
              padding: '6px 12px', borderTop: '1px solid var(--border, #e5e7eb)',
              cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              fontSize: 11, color: 'var(--text-muted, #6b7280)', userSelect: 'none',
            }}
            onClick={() => setExpanded(!expanded)}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>🔍 可解释性详情 <HelpTooltip {...helpTips.explainabilityDetails}><HelpIcon /></HelpTooltip></span>
            <span style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>▼</span>
          </div>
          {expanded && (
            <div style={{ padding: '8px 12px 12px' }}>
              {/* 因子评分 */}
              {factorEntries.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted, #9ca3af)', marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}>多维因子评分 <HelpTooltip {...helpTips.factorScores}><HelpIcon /></HelpTooltip></div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {factorEntries.map(f => (
                      <FactorBar key={f.key} label={f.label} value={f.value} />
                    ))}
                  </div>
                </div>
              )}
              {/* 特征重要性 */}
              {insight.feature_importance.length > 0 && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted, #9ca3af)', marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}>特征贡献度 Top {insight.feature_importance.length} <HelpTooltip {...helpTips.featureImportance}><HelpIcon /></HelpTooltip></div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {insight.feature_importance.map((fi, i) => {
                      const maxImp = insight.feature_importance[0]?.importance || 1
                      return (
                        <FactorBar key={i} label={fi.feature} value={fi.importance} maxVal={maxImp} />
                      )
                    })}
                  </div>
                </div>
              )}
              {/* 模型评估 */}
              {insight.model_accuracy != null && (
                <div style={{ marginTop: 8, padding: '6px 8px', borderRadius: 6, background: 'rgba(59,130,246,0.04)', fontSize: 10, color: 'var(--text-muted, #6b7280)' }}>
                  📊 模型方向准确率: <strong style={{ color: 'var(--text, #1f2937)' }}>{insight.model_accuracy}%</strong>
                  （最近 30 次预测）
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
