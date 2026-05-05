import React from 'react'
import { ReloadOutlined } from '@ant-design/icons'
import type { ActionableStockPlan, ActionableTradingDashboard } from './actionability'
import { formatAbsPct } from './actionability'

type Props = {
  dashboard: ActionableTradingDashboard
  loading: boolean
  error?: string | null
  onRefresh: () => void
  onSelectSymbol: (symbol: string) => void
}

const sectionMeta: Record<string, { title: string; empty: string; tone: string }> = {
  executableBuys: { title: '立即可买', empty: '当前没有满足立即买入条件的股票。', tone: 'buy' },
  nearBuyCandidates: { title: '接近买点', empty: '暂无接近低吸区的候选。', tone: 'wait' },
  breakoutWatch: { title: '突破待确认', empty: '暂无接近突破确认的候选。', tone: 'info' },
  holdingActions: { title: '已持有应处理', empty: '暂无持有处理提示。', tone: 'neutral' },
  sellOrReduce: { title: '建议卖出/减仓', empty: '暂无卖出或减仓提示。', tone: 'sell' },
  avoidList: { title: '建议规避', empty: '暂无规避候选。', tone: 'avoid' },
}

function toneStyle(tone: string): React.CSSProperties {
  const styles: Record<string, React.CSSProperties> = {
    buy: { borderColor: 'var(--action-buy-border)', background: 'var(--action-buy-bg)', color: 'var(--action-buy-fg)' },
    sell: { borderColor: 'var(--action-sell-border)', background: 'var(--action-sell-bg)', color: 'var(--action-sell-fg)' },
    wait: { borderColor: 'var(--action-hold-border)', background: 'var(--action-hold-bg)', color: 'var(--action-hold-fg)' },
    avoid: { borderColor: 'rgba(168,113,255,0.34)', background: 'rgba(168,113,255,0.12)', color: 'var(--avoid)' },
    info: { borderColor: 'var(--primary-border)', background: 'var(--primary-light)', color: 'var(--primary)' },
    neutral: { borderColor: 'var(--badge-neutral-border)', background: 'var(--badge-neutral-bg)', color: 'var(--badge-neutral-fg)' },
  }
  return styles[tone] || styles.neutral
}

function money(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '-'
  return value.toFixed(2)
}

function triggerText(plan: ActionableStockPlan) {
  if (plan.triggerRange) return `${money(plan.triggerRange[0])}-${money(plan.triggerRange[1])}`
  if (plan.triggerPrice != null) return money(plan.triggerPrice)
  return '-'
}

function Metric({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', padding: 12 }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 6 }}>{label}</div>
      <div style={{ color: tone || 'var(--text)', fontSize: 22, fontWeight: 900, lineHeight: 1 }}>{value}</div>
    </div>
  )
}

function PlanRow({ plan, activeTone, onSelectSymbol }: { plan: ActionableStockPlan; activeTone: string; onSelectSymbol: (symbol: string) => void }) {
  const tone = toneStyle(activeTone)
  return (
    <button
      type="button"
      onClick={() => onSelectSymbol(plan.stockCode)}
      style={{
        width: '100%',
        border: '1px solid var(--border)',
        background: 'rgba(255,255,255,0.025)',
        color: 'var(--text)',
        borderRadius: 8,
        padding: 11,
        display: 'grid',
        gridTemplateColumns: 'minmax(120px,1fr) 82px 88px',
        gap: 10,
        textAlign: 'left',
        cursor: 'pointer',
      }}
    >
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{plan.stockName}</span>
        <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>{plan.stockCode} / 当前 {money(plan.currentPrice)}</span>
      </span>
      <span style={{ ...tone, border: `1px solid ${tone.borderColor}`, borderRadius: 999, padding: '4px 8px', fontSize: 11, fontWeight: 850, textAlign: 'center', whiteSpace: 'nowrap' }}>{plan.actionLabel}</span>
      <span style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 750 }}>差距 {formatAbsPct(plan.distanceToTriggerPct)}</span>
      <span style={{ gridColumn: '1 / -1', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 88px 88px', gap: 8, alignItems: 'center' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.45 }}>{plan.oneLineAction}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>触发 {triggerText(plan)}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>止损 {money(plan.stopLossPrice)}</span>
      </span>
    </button>
  )
}

function PlanSection({ title, empty, tone, items, onSelectSymbol }: { title: string; empty: string; tone: string; items: ActionableStockPlan[]; onSelectSymbol: (symbol: string) => void }) {
  const headerTone = toneStyle(tone)
  return (
    <div style={{ border: `1px solid ${headerTone.borderColor}`, background: 'rgba(255,255,255,0.018)', borderRadius: 8, padding: 12, minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <div style={{ color: 'var(--text)', fontWeight: 900, fontSize: 14 }}>{title}</div>
        <span style={{ color: headerTone.color, fontSize: 12, fontWeight: 850 }}>{items.length} 只</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.slice(0, 3).map(item => <PlanRow key={`${title}-${item.stockCode}`} plan={item} activeTone={tone} onSelectSymbol={onSelectSymbol} />)}
        {items.length === 0 && <div style={{ border: '1px dashed var(--border)', borderRadius: 8, padding: 12, color: 'var(--text-muted)', fontSize: 12 }}>{empty}</div>}
      </div>
    </div>
  )
}

export default function ActionableTradingCenter({ dashboard, loading, error, onRefresh, onSelectSymbol }: Readonly<Props>) {
  return (
    <section style={{ padding: '0 12px 12px' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'linear-gradient(135deg, rgba(16,24,39,0.98), rgba(10,17,30,0.94))', overflow: 'hidden' }}>
        <div style={{ padding: 16, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 850, letterSpacing: 0.35 }}>今日/明日可执行操作中心</div>
            <h1 style={{ margin: '7px 0 0', color: 'var(--text)', fontSize: 26, lineHeight: 1.18, fontWeight: 900 }}>{dashboard.summary.plainConclusion}</h1>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 7 }}>目标交易日 {dashboard.targetTradeDate}，所有动作仅为模型辅助分析，不构成真实下单建议。</div>
          </div>
          <button type="button" className="dark-btn dark-btn-secondary" onClick={onRefresh} disabled={loading}>
            <ReloadOutlined /> {loading ? '更新中' : '刷新操作中心'}
          </button>
        </div>

        {error && <div style={{ margin: 16, border: '1px solid rgba(255,92,92,0.35)', background: 'rgba(255,92,92,0.08)', color: '#ffc9c9', borderRadius: 8, padding: 12 }}>{error}</div>}

        <div style={{ padding: 16, display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0,1fr))', gap: 12 }}>
          <Metric label="立即可买" value={dashboard.summary.actionableCount} tone="var(--positive)" />
          <Metric label="接近买点/突破" value={dashboard.summary.nearBuyCount} tone="var(--warning)" />
          <Metric label="卖出/减仓" value={dashboard.summary.sellSignalCount} tone="var(--negative)" />
          <Metric label="建议规避" value={dashboard.summary.avoidCount} tone="var(--avoid)" />
        </div>

        {dashboard.noActionReason && (
          <div style={{ margin: '0 16px 16px', border: '1px solid var(--action-hold-border)', background: 'var(--action-hold-bg)', color: 'var(--text)', borderRadius: 8, padding: 12, fontSize: 13, lineHeight: 1.55 }}>
            {dashboard.noActionReason}
          </div>
        )}

        <div style={{ padding: '0 16px 16px', display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 12 }}>
          <PlanSection {...sectionMeta.executableBuys} items={dashboard.executableBuys} onSelectSymbol={onSelectSymbol} />
          <PlanSection {...sectionMeta.nearBuyCandidates} items={dashboard.nearBuyCandidates} onSelectSymbol={onSelectSymbol} />
          <PlanSection {...sectionMeta.breakoutWatch} items={dashboard.breakoutWatch} onSelectSymbol={onSelectSymbol} />
          <PlanSection {...sectionMeta.holdingActions} items={dashboard.holdingActions} onSelectSymbol={onSelectSymbol} />
          <PlanSection {...sectionMeta.sellOrReduce} items={dashboard.sellOrReduce} onSelectSymbol={onSelectSymbol} />
          <PlanSection {...sectionMeta.avoidList} items={dashboard.avoidList} onSelectSymbol={onSelectSymbol} />
        </div>
      </div>
    </section>
  )
}