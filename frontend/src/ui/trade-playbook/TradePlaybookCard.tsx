import React from 'react'
import type { TradePlaybook, PlaybookAgentView, StockTradePlaybookResponse } from '../../api/tradePlaybook'
import { explainMetricForRetailUser } from '../retail/MetricTranslator'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../../config/helpTips'

export const playbookTone: Record<string, { bg: string; fg: string; border: string }> = {
  executable_now: { bg: 'rgba(34,197,94,0.14)', fg: '#86efac', border: 'rgba(34,197,94,0.38)' },
  wait_for_pullback: { bg: 'rgba(20,184,166,0.12)', fg: '#5eead4', border: 'rgba(20,184,166,0.34)' },
  wait_for_breakout: { bg: 'rgba(96,165,250,0.13)', fg: '#93c5fd', border: 'rgba(96,165,250,0.34)' },
  hold_watch: { bg: 'rgba(148,163,184,0.12)', fg: '#cbd5e1', border: 'rgba(148,163,184,0.30)' },
  reduce: { bg: 'rgba(251,146,60,0.14)', fg: '#fdba74', border: 'rgba(251,146,60,0.36)' },
  sell: { bg: 'rgba(248,113,113,0.15)', fg: '#fca5a5', border: 'rgba(248,113,113,0.40)' },
  avoid: { bg: 'rgba(248,113,113,0.12)', fg: '#fecaca', border: 'rgba(248,113,113,0.32)' },
}

export function toneForPlaybook(action?: string) {
  return playbookTone[action || 'hold_watch'] || playbookTone.hold_watch
}

export function money(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return value.toFixed(2)
}

export function rangeText(range: [number, number] | null | undefined) {
  if (!range) return '等待价位'
  return `${money(range[0])} - ${money(range[1])}`
}

function percentRangeText(range: [number, number] | null | undefined) {
  if (!range) return '-'
  return `${range[0].toFixed(1)}% - ${range[1].toFixed(1)}%`
}

function confidenceLabel(value: string | null | undefined) {
  const labels: Record<string, string> = { high: '较高', medium: '中等', low: '偏低' }
  return value ? labels[value] || value : '-'
}

function riskLabel(value: string | null | undefined) {
  const labels: Record<string, string> = { low: '偏低', medium: '中等', high: '偏高', extreme: '很高' }
  return value ? labels[value] || value : '-'
}

function stanceLabel(stance?: string) {
  const key = String(stance || 'neutral').toLowerCase()
  return {
    support: '偏支持',
    neutral: '中性',
    risk: '偏风险',
    high: '风险偏高',
    medium: '风险中等',
    low: '风险偏低',
    extreme: '风险很高',
    strong_buy: '强买信号',
    buy: '买入信号',
    hold: '观察信号',
    sell: '卖出信号',
    strong_sell: '强卖信号',
    positive: '偏积极',
    negative: '偏消极',
  }[key] || '中性'
}

function MiniMetric({ label, value, detail, tip }: { label: string; value: React.ReactNode; detail?: string; tip?: HelpTipKey }) {
  return (
    <div style={{ border: '1px solid var(--border)', background: 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 12, minWidth: 0 }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 5 }}>
        {label}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </div>
      <div style={{ color: 'var(--text)', fontSize: 18, fontWeight: 850, lineHeight: 1.18, overflowWrap: 'anywhere' }}>{value}</div>
      {detail && <div style={{ color: 'var(--text-muted)', fontSize: 11, lineHeight: 1.45, marginTop: 6 }}>{detail}</div>}
    </div>
  )
}

function TextList({ title, items, tip }: { title: string; items: string[]; tip?: HelpTipKey }) {
  return (
    <div style={{ border: '1px solid var(--border)', background: 'rgba(15,23,42,0.42)', borderRadius: 8, padding: 12, minWidth: 0 }}>
      <div style={{ color: 'var(--text)', fontSize: 13, fontWeight: 850, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
        {title}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
        {items.slice(0, 4).map((item, index) => (
          <div key={`${title}-${index}`} style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5 }}>{item}</div>
        ))}
      </div>
    </div>
  )
}

function ScenarioGrid({ playbook }: { playbook: TradePlaybook }) {
  const entries = [
    { label: '高开', text: playbook.scenarioPlan.ifGapUp, tip: 'scenarioGapUp' as HelpTipKey },
    { label: '低开', text: playbook.scenarioPlan.ifGapDown, tip: 'scenarioGapDown' as HelpTipKey },
    { label: '回调', text: playbook.scenarioPlan.ifPullback, tip: 'scenarioPullback' as HelpTipKey },
    { label: '突破', text: playbook.scenarioPlan.ifBreakout, tip: 'scenarioBreakout' as HelpTipKey },
    { label: '跌破', text: playbook.scenarioPlan.ifBreakdown, tip: 'scenarioBreakdown' as HelpTipKey },
    { label: '横盘', text: playbook.scenarioPlan.ifSideways, tip: 'scenarioSideways' as HelpTipKey },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 10 }}>
      {entries.map(entry => <TextList key={entry.label} title={entry.label} items={[entry.text]} tip={entry.tip} />)}
    </div>
  )
}

function AgentViewGrid({ views }: { views: Record<string, PlaybookAgentView | null> }) {
  const ordered = ['priceForecast', 'technicalTiming', 'capitalFlow', 'newsSentiment', 'macroPolicy', 'companyFundamental', 'riskControl']
  const tipByKey: Record<string, HelpTipKey> = {
    priceForecast: 'agentPriceForecast',
    technicalTiming: 'agentTechnicalTiming',
    capitalFlow: 'agentCapitalFlow',
    newsSentiment: 'agentNewsSentiment',
    macroPolicy: 'agentMacroPolicy',
    companyFundamental: 'agentCompanyFundamental',
    riskControl: 'agentRiskControl',
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
      {ordered.map(key => {
        const view = views[key]
        if (!view) return null
        return (
          <div key={key} style={{ border: '1px solid var(--border)', background: 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 12, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ color: 'var(--text)', fontSize: 13, fontWeight: 850, display: 'flex', alignItems: 'center', gap: 6 }}>
                {view.title}
                <HelpTooltip {...helpTips[tipByKey[key] || 'agentPlainExplain']}><HelpIcon /></HelpTooltip>
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>{stanceLabel(view.stance)}</div>
            </div>
            {(view.points || []).slice(0, 3).map((point, index) => (
              <div key={`${key}-${index}`} style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5, marginTop: index ? 6 : 0 }}>{point}</div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

export function TradePlaybookSummaryCard({ playbook, active, onSelect }: { playbook: TradePlaybook; active?: boolean; onSelect?: (symbol: string) => void }) {
  const tone = toneForPlaybook(playbook.actionCategory)
  const body = (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start', marginBottom: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: 'var(--text)', fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{playbook.stockName || playbook.stockCode}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>{playbook.stockCode} / {playbook.targetHorizon}</div>
        </div>
        <span style={{ display: 'inline-flex', alignItems: 'center', padding: '4px 9px', borderRadius: 999, border: `1px solid ${tone.border}`, background: tone.bg, color: tone.fg, fontSize: 11, fontWeight: 850, whiteSpace: 'nowrap' }}>
          {playbook.actionLabel}
        </span>
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.45, minHeight: 34 }}>{playbook.plainSummary}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
        <MiniMetric label="买入区" value={rangeText(playbook.buyPlan.idealBuyRange)} tip="idealBuyRange" />
        <MiniMetric label="止损" value={money(playbook.sellPlan.stopLossPrice)} tip="stopLossPrice" />
      </div>
    </>
  )
  if (onSelect) {
    return (
      <button
        type="button"
        onClick={() => onSelect(playbook.stockCode)}
        style={{ width: '100%', textAlign: 'left', border: active ? '1px solid rgba(99,102,241,0.65)' : `1px solid ${tone.border}`, background: active ? 'rgba(99,102,241,0.14)' : 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 12, cursor: 'pointer', color: 'var(--text)' }}
      >
        {body}
      </button>
    )
  }
  return <div style={{ border: `1px solid ${tone.border}`, background: 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 12 }}>{body}</div>
}

export function TradePlaybookCard({ response, onRefresh, loading }: { response: StockTradePlaybookResponse; onRefresh?: () => void; loading?: boolean }) {
  const playbook = response.playbook
  const tone = toneForPlaybook(playbook.actionCategory)
  const trackRecord = playbook.modelTrackRecord
  const directionAccuracy = trackRecord.directionAccuracy
  const directionAccuracyValue = trackRecord.sampleCount && directionAccuracy != null ? `${directionAccuracy.toFixed(1)}%` : '样本不足'
  const directionAccuracyDetail = directionAccuracy != null
    ? explainMetricForRetailUser('direction_accuracy', directionAccuracy)
    : trackRecord.plainSummary
  return (
    <div style={{ border: `1px solid ${tone.border}`, background: 'linear-gradient(135deg, rgba(15,23,42,0.98), rgba(17,24,39,0.92))', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: 18, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 850, letterSpacing: 0.3, display: 'flex', alignItems: 'center', gap: 6 }}>
            个股交易剧本
            <HelpTooltip {...helpTips.currentPlaybook}><HelpIcon /></HelpTooltip>
          </div>
          <h2 style={{ margin: '8px 0 0', color: 'var(--text)', fontSize: 26, lineHeight: 1.18, fontWeight: 900 }}>{playbook.stockName}：{playbook.actionLabel}</h2>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5, marginTop: 8 }}>{playbook.plainSummary}</div>
        </div>
        {onRefresh && (
          <HelpTooltip {...helpTips.refreshPlaybook}>
            <span style={{ display: 'inline-flex' }}>
              <button type="button" onClick={onRefresh} className="dark-btn dark-btn-secondary" disabled={loading} style={{ opacity: loading ? 0.65 : 1 }}>
                {loading ? '更新中' : '刷新剧本'}
              </button>
            </span>
          </HelpTooltip>
        )}
      </div>

      <div style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0,1fr))', gap: 10 }}>
          <MiniMetric label="当前价" value={money(playbook.currentPrice)} detail={playbook.asOfDate} tip="currentPrice" />
          <MiniMetric label="买入区" value={rangeText(playbook.buyPlan.idealBuyRange)} detail="只在计划内考虑" tip="idealBuyRange" />
          <MiniMetric label="突破价" value={money(playbook.buyPlan.breakoutBuyAbove)} detail="放量确认再看" tip="breakoutBuyAbove" />
          <MiniMetric label="不追高" value={money(playbook.buyPlan.doNotChaseAbove)} detail="超过则等待" tip="doNotChaseAbove" />
          <MiniMetric label="止损" value={money(playbook.sellPlan.stopLossPrice)} detail="跌破计划失效" tip="stopLossPrice" />
          <MiniMetric label="目标1" value={money(playbook.sellPlan.takeProfitPrice1)} detail="先看分批止盈" tip="takeProfitPrice1" />
          <MiniMetric label="目标2" value={money(playbook.sellPlan.takeProfitPrice2)} detail="强势延续再看" tip="takeProfitPrice2" />
          <MiniMetric label="仓位上限" value={`${playbook.buyPlan.maxPositionPct}%`} detail="模型辅助上限" tip="suggestedPosition" />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
          <TextList title="买入条件" items={playbook.buyPlan.buyConditions} tip="buyConditions" />
          <TextList title="取消买入" items={playbook.buyPlan.cancelBuyConditions} tip="cancelBuyConditions" />
          <TextList title="卖出/止盈/止损" items={playbook.sellPlan.sellConditions} tip="sellConditions" />
          <TextList title="风险控制" items={playbook.riskControl} tip="riskControlRules" />
        </div>

        <div>
          <div style={{ color: 'var(--text)', fontWeight: 850, fontSize: 15, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
            不同走势怎么做
            <HelpTooltip {...helpTips.scenarioOverview}><HelpIcon /></HelpTooltip>
          </div>
          <ScenarioGrid playbook={playbook} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
          <TextList title="未持有" items={[playbook.holdingPlan.ifNotHolding]} tip="ifNotHolding" />
          <TextList title="已持有" items={[playbook.holdingPlan.ifAlreadyHolding]} tip="ifAlreadyHolding" />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0,1fr))', gap: 10 }}>
          <MiniMetric label="信心" value={confidenceLabel(playbook.confidence)} detail={`${playbook.confidenceScore.toFixed(0)}/100`} tip="confidence" />
          <MiniMetric label="风险" value={riskLabel(playbook.riskLevel)} detail={playbook.riskSummary} tip="riskLevel" />
          <MiniMetric label="周期" value={playbook.targetHorizon} detail={`目标日 ${playbook.targetTradeDate}`} tip="targetHorizon" />
          <MiniMetric label="风险收益比" value={playbook.riskRewardRatio != null ? playbook.riskRewardRatio.toFixed(2) : '-'} detail={percentRangeText(playbook.expectedReturnRange)} tip="riskRewardRatio" />
          <MiniMetric label="历史表现" value={directionAccuracyValue} detail={directionAccuracyDetail} tip="directionAccuracy" />
        </div>

        <TextList title="计划失效条件" items={playbook.invalidationConditions} tip="planInvalidation" />

        {playbook.dataWarnings.length > 0 && (
          <div style={{ border: '1px solid rgba(251,191,36,0.30)', background: 'rgba(251,191,36,0.08)', borderRadius: 8, padding: 12, color: '#fde68a', fontSize: 12, lineHeight: 1.55 }}>
            {playbook.dataWarnings.join(' ')}
          </div>
        )}

        <details style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.018)', overflow: 'hidden' }}>
          <summary style={{ padding: '12px 14px', cursor: 'pointer', color: 'var(--text)', fontWeight: 850, display: 'flex', alignItems: 'center', gap: 6 }}>
            专业模式 / 查看 Agent 理由
            <HelpTooltip {...helpTips.agentReason}><HelpIcon /></HelpTooltip>
          </summary>
          <div style={{ padding: 12 }}>
            <AgentViewGrid views={response.agentViews || {}} />
          </div>
        </details>

        <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5, borderTop: '1px solid var(--border)', paddingTop: 12 }}>{playbook.disclaimer}</div>
      </div>
    </div>
  )
}