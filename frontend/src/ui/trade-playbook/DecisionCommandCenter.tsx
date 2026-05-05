import React from 'react'
import type { StockTradePlaybookResponse, TomorrowPlaybookResponse, TradePlaybook } from '../../api/tradePlaybook'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../../config/helpTips'
import { money, rangeText, toneForPlaybook, TradePlaybookSummaryCard } from './TradePlaybookCard'

type Props = {
  current?: string
  data: TomorrowPlaybookResponse | null
  stockResponse: StockTradePlaybookResponse | null
  loading: boolean
  stockLoading: boolean
  error?: string | null
  onRefresh: () => void
  onSelectSymbol: (symbol: string) => void
}

const groups: Array<{ key: keyof Pick<TomorrowPlaybookResponse, 'executableNow' | 'waitForPullback' | 'waitForBreakout' | 'holdWatch' | 'reduceOrSell' | 'avoid'>; title: string; tip: HelpTipKey }> = [
  { key: 'executableNow', title: '立即可执行', tip: 'executableNow' },
  { key: 'waitForPullback', title: '等回调低吸', tip: 'waitForPullback' },
  { key: 'waitForBreakout', title: '等突破确认', tip: 'waitForBreakout' },
  { key: 'holdWatch', title: '持有观察', tip: 'holdWatch' },
  { key: 'reduceOrSell', title: '减仓/卖出', tip: 'reduceOrSell' },
  { key: 'avoid', title: '规避', tip: 'avoid' },
]

function MiniField({ label, value, tip }: { label: string; value: React.ReactNode; tip?: HelpTipKey }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', padding: 10, minWidth: 0 }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 5, display: 'flex', alignItems: 'center', gap: 5 }}>
        {label}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </div>
      <div style={{ color: 'var(--text)', fontSize: 17, fontWeight: 850, lineHeight: 1.16, overflowWrap: 'anywhere' }}>{value}</div>
    </div>
  )
}

function TomorrowActionBoard({ data, current, onSelectSymbol }: { data: TomorrowPlaybookResponse | null; current?: string; onSelectSymbol: (symbol: string) => void }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
      {groups.map(group => {
        const items = data?.[group.key] || []
        return (
          <div key={group.key} style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.018)', padding: 10, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ color: 'var(--text)', fontWeight: 850, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                {group.title}
                <HelpTooltip {...helpTips[group.tip]}><HelpIcon /></HelpTooltip>
              </div>
              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{items.length} 只</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              {items.slice(0, 2).map(item => <TradePlaybookSummaryCard key={`${group.key}-${item.stockCode}`} playbook={item} active={item.stockCode === current} onSelect={onSelectSymbol} />)}
              {items.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 12, border: '1px dashed var(--border)', borderRadius: 8, padding: 10 }}>暂无候选</div>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function SelectedStockPlaybookSummary({ response, loading }: { response: StockTradePlaybookResponse | null; loading: boolean }) {
  const playbook = response?.playbook
  if (!playbook) {
    return <div style={{ color: 'var(--text-muted)', border: '1px dashed var(--border)', borderRadius: 8, padding: 18 }}>{loading ? '正在生成当前股票交易剧本...' : '请选择一只股票查看交易剧本。'}</div>
  }
  const tone = toneForPlaybook(playbook.actionCategory)
  return (
    <div style={{ border: `1px solid ${tone.border}`, background: 'rgba(255,255,255,0.02)', borderRadius: 8, padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start', marginBottom: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 850, display: 'flex', alignItems: 'center', gap: 6 }}>
            当前股票交易剧本
            <HelpTooltip {...helpTips.currentPlaybook}><HelpIcon /></HelpTooltip>
          </div>
          <h2 style={{ margin: '6px 0 0', color: 'var(--text)', fontSize: 24, lineHeight: 1.16 }}>{playbook.stockName}：{playbook.actionLabel}</h2>
        </div>
        <span style={{ border: `1px solid ${tone.border}`, background: tone.bg, color: tone.fg, borderRadius: 999, padding: '5px 10px', fontSize: 12, fontWeight: 850, whiteSpace: 'nowrap' }}>{playbook.actionLabel}</span>
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.55, marginBottom: 12 }}>{playbook.plainSummary}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 9 }}>
        <MiniField label="当前价" value={money(playbook.currentPrice)} tip="currentPrice" />
        <MiniField label="买入区" value={rangeText(playbook.buyPlan.idealBuyRange)} tip="idealBuyRange" />
        <MiniField label="突破价" value={money(playbook.buyPlan.breakoutBuyAbove)} tip="breakoutBuyAbove" />
        <MiniField label="不追高" value={money(playbook.buyPlan.doNotChaseAbove)} tip="doNotChaseAbove" />
        <MiniField label="止损" value={money(playbook.sellPlan.stopLossPrice)} tip="stopLossPrice" />
        <MiniField label="目标" value={`${money(playbook.sellPlan.takeProfitPrice1)} / ${money(playbook.sellPlan.takeProfitPrice2)}`} tip="takeProfitPrice1" />
        <MiniField label="仓位" value={`${playbook.buyPlan.maxPositionPct}%`} tip="suggestedPosition" />
        <MiniField label="信心" value={`${playbook.confidenceScore.toFixed(0)}/100`} tip="confidence" />
        <MiniField label="风险" value={playbook.riskSummary} tip="riskLevel" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9, marginTop: 10 }}>
        <MiniField label="未持有" value={playbook.holdingPlan.ifNotHolding} tip="ifNotHolding" />
        <MiniField label="已持有" value={playbook.holdingPlan.ifAlreadyHolding} tip="ifAlreadyHolding" />
      </div>
    </div>
  )
}

export default function DecisionCommandCenter({ current, data, stockResponse, loading, stockLoading, error, onRefresh, onSelectSymbol }: Props) {
  return (
    <section style={{ padding: '0 12px 12px' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'linear-gradient(135deg, rgba(17,24,39,0.98), rgba(15,23,42,0.90))', overflow: 'hidden' }}>
        <div style={{ padding: 16, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 850, display: 'flex', alignItems: 'center', gap: 6 }}>
              明日整体策略
              <HelpTooltip {...helpTips.tomorrowActionList}><HelpIcon /></HelpTooltip>
            </div>
            <h1 style={{ margin: '7px 0 0', color: 'var(--text)', fontSize: 26, lineHeight: 1.18 }}>{data?.marketSummary.plainSummary || (loading ? '正在生成明日交易剧本...' : '等待明日交易剧本')}</h1>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 7 }}>{data?.marketSummary.suggestedPositionSummary || '按自选/股票池最新模型、价格、资金和风险数据生成。'}</div>
          </div>
          <HelpTooltip {...helpTips.refreshPlaybook}><button type="button" className="dark-btn dark-btn-secondary" onClick={onRefresh} disabled={loading}>{loading ? '更新中' : '刷新剧本'}</button></HelpTooltip>
        </div>
        {error && <div style={{ margin: 16, border: '1px solid rgba(248,113,113,0.34)', background: 'rgba(248,113,113,0.08)', color: '#fecaca', borderRadius: 8, padding: 12 }}>{error}</div>}
        <div style={{ padding: 16, display: 'grid', gridTemplateColumns: 'minmax(0,1.05fr) minmax(360px,0.95fr)', gap: 14, alignItems: 'start' }}>
          <TomorrowActionBoard data={data} current={current} onSelectSymbol={onSelectSymbol} />
          <SelectedStockPlaybookSummary response={stockResponse} loading={stockLoading} />
        </div>
        <div style={{ borderTop: '1px solid var(--border)', padding: 12, color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5 }}>
          {data?.disclaimer || stockResponse?.playbook.disclaimer || '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。'}
        </div>
      </div>
    </section>
  )
}