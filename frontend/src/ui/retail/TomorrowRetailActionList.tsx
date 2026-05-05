import React from 'react'
import { fetchTomorrowRetailActions, type TomorrowRetailActionItem, type TomorrowRetailActionsResponse } from '../../api/retailDecision'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../../config/helpTips'

type Props = {
  current?: string
  onSelectSymbol: (symbol: string) => void
}

const sectionMeta: Record<string, { title: string; empty: string; border: string; bg: string; tip: HelpTipKey }> = {
  buy: { title: '可以买入', empty: '暂无可以买入候选', border: 'rgba(34,197,94,0.34)', bg: 'rgba(34,197,94,0.08)', tip: 'retailActionBuy' },
  watch: { title: '小仓观察', empty: '暂无观察候选', border: 'rgba(20,184,166,0.34)', bg: 'rgba(20,184,166,0.07)', tip: 'retailActionWatch' },
  sell: { title: '建议卖出/减仓', empty: '暂无减仓提示', border: 'rgba(251,146,60,0.34)', bg: 'rgba(251,146,60,0.08)', tip: 'retailActionSell' },
  avoid: { title: '建议规避', empty: '暂无规避候选', border: 'rgba(248,113,113,0.36)', bg: 'rgba(248,113,113,0.08)', tip: 'retailActionAvoid' },
}

function money(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return value.toFixed(2)
}

function rangeLabel(item: TomorrowRetailActionItem) {
  if (item.suggestedBuyRange) return item.suggestedBuyRange.label
  if (item.action === 'sell_reduce') return `目标 ${money(item.takeProfitPrice1)}`
  return '等待计划价'
}

function CandidateRow({ item, active, onSelect }: { item: TomorrowRetailActionItem; active: boolean; onSelect: (symbol: string) => void }) {
  const rangeTip: HelpTipKey = item.action === 'sell_reduce' ? 'takeProfitPrice1' : 'idealBuyRange'
  return (
    <button
      type="button"
      onClick={() => onSelect(item.symbol)}
      style={{
        width: '100%',
        display: 'grid',
        gridTemplateColumns: 'minmax(110px,1fr) 96px 90px',
        gap: 10,
        alignItems: 'center',
        border: active ? '1px solid rgba(99,102,241,0.65)' : '1px solid var(--border)',
        background: active ? 'rgba(99,102,241,0.14)' : 'rgba(255,255,255,0.025)',
        borderRadius: 8,
        color: 'var(--text)',
        padding: 10,
        textAlign: 'left',
        cursor: 'pointer',
      }}
    >
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', fontWeight: 800, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name || item.symbol}</span>
        <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>{item.symbol} / 风险{item.riskLabel}</span>
      </span>
      <span style={{ color: 'var(--text)', fontWeight: 760, fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>{rangeLabel(item)}<HelpTooltip {...helpTips[rangeTip]}><HelpIcon /></HelpTooltip></span>
      <span style={{ color: 'var(--text-muted)', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>止损 {money(item.stopLossPrice)}<HelpTooltip {...helpTips.stopLossPrice}><HelpIcon /></HelpTooltip></span>
      <span style={{ gridColumn: '1 / -1', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.45 }}>{item.oneSentenceReason}</span>
    </button>
  )
}

function CandidateSection({ type, items, current, onSelectSymbol }: { type: keyof typeof sectionMeta; items: TomorrowRetailActionItem[]; current?: string; onSelectSymbol: (symbol: string) => void }) {
  const meta = sectionMeta[type]
  return (
    <div style={{ border: `1px solid ${meta.border}`, background: meta.bg, borderRadius: 8, padding: 12, minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <div style={{ color: 'var(--text)', fontSize: 15, fontWeight: 850, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {meta.title}
          <HelpTooltip {...helpTips[meta.tip]}><HelpIcon /></HelpTooltip>
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{items.length} 只</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.slice(0, 4).map(item => (
          <CandidateRow key={`${type}-${item.symbol}`} item={item} active={item.symbol === current} onSelect={onSelectSymbol} />
        ))}
        {items.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 13, border: '1px dashed var(--border)', borderRadius: 8, padding: 12 }}>{meta.empty}</div>}
      </div>
    </div>
  )
}

export default function TomorrowRetailActionList({ current, onSelectSymbol }: Props) {
  const [data, setData] = React.useState<TomorrowRetailActionsResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await fetchTomorrowRetailActions(12))
    } catch (err: any) {
      setError(err?.message || '明日操作清单加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    load()
  }, [load])

  return (
    <section style={{ padding: 12 }}>
      <div style={{ border: '1px solid var(--border)', background: 'linear-gradient(135deg, rgba(17,24,39,0.98), rgba(15,23,42,0.90))', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ padding: 18, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 800, letterSpacing: 0.4, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              明日小散操作清单
              <HelpTooltip {...helpTips.tomorrowActionList}><HelpIcon /></HelpTooltip>
            </div>
            <h2 style={{ margin: '8px 0 0', color: 'var(--text)', fontSize: 26, lineHeight: 1.18, fontWeight: 900 }}>
              {data?.tomorrowStrategy || (loading ? '正在生成明日清单...' : '等待生成明日清单')}
            </h2>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5, marginTop: 8 }}>{data?.marketSummary || '根据自选/股票池最新数据做散户友好聚合。'}</div>
          </div>
          <HelpTooltip {...helpTips.refreshData}>
            <span style={{ display: 'inline-flex' }}>
              <button type="button" className="dark-btn dark-btn-secondary" onClick={load} disabled={loading} style={{ opacity: loading ? 0.65 : 1 }}>
                {loading ? '更新中' : '刷新清单'}
              </button>
            </span>
          </HelpTooltip>
        </div>

        {error ? (
          <div style={{ margin: 18, border: '1px solid rgba(248,113,113,0.35)', background: 'rgba(248,113,113,0.08)', color: '#fecaca', borderRadius: 8, padding: 12, fontSize: 13 }}>
            新清单暂不可用，下面保留原模型摘要。{error.slice(0, 160)}
          </div>
        ) : (
          <div style={{ padding: 18, display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 12 }}>
            <CandidateSection type="buy" items={data?.buyCandidates || []} current={current} onSelectSymbol={onSelectSymbol} />
            <CandidateSection type="watch" items={data?.watchCandidates || []} current={current} onSelectSymbol={onSelectSymbol} />
            <CandidateSection type="sell" items={data?.sellCandidates || []} current={current} onSelectSymbol={onSelectSymbol} />
            <CandidateSection type="avoid" items={data?.avoidCandidates || []} current={current} onSelectSymbol={onSelectSymbol} />
          </div>
        )}

        <div style={{ borderTop: '1px solid var(--border)', padding: '10px 18px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5 }}>
          {data?.disclaimer || '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。'}
        </div>
      </div>
    </section>
  )
}