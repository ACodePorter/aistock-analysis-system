import React from 'react'
import { fetchTomorrowPlaybook, type TomorrowPlaybookResponse, type TradePlaybook } from '../../api/tradePlaybook'
import { TradePlaybookSummaryCard } from './TradePlaybookCard'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../../config/helpTips'

type Props = {
  current?: string
  onSelectSymbol: (symbol: string) => void
}

const groupMeta: Array<{ key: keyof Pick<TomorrowPlaybookResponse, 'executableNow' | 'waitForPullback' | 'waitForBreakout' | 'holdWatch' | 'reduceOrSell' | 'avoid'>; title: string; empty: string; border: string; bg: string; tip: HelpTipKey }> = [
  { key: 'executableNow', title: '立即可执行', empty: '暂无立即执行候选', border: 'rgba(34,197,94,0.34)', bg: 'rgba(34,197,94,0.07)', tip: 'executableNow' },
  { key: 'waitForPullback', title: '等回调低吸', empty: '暂无低吸候选', border: 'rgba(20,184,166,0.34)', bg: 'rgba(20,184,166,0.06)', tip: 'waitForPullback' },
  { key: 'waitForBreakout', title: '等突破确认', empty: '暂无突破候选', border: 'rgba(96,165,250,0.34)', bg: 'rgba(96,165,250,0.07)', tip: 'waitForBreakout' },
  { key: 'holdWatch', title: '持有观察', empty: '暂无持有观察', border: 'rgba(148,163,184,0.30)', bg: 'rgba(148,163,184,0.06)', tip: 'holdWatch' },
  { key: 'reduceOrSell', title: '减仓/卖出', empty: '暂无减仓提示', border: 'rgba(251,146,60,0.34)', bg: 'rgba(251,146,60,0.07)', tip: 'reduceOrSell' },
  { key: 'avoid', title: '规避', empty: '暂无规避候选', border: 'rgba(248,113,113,0.34)', bg: 'rgba(248,113,113,0.07)', tip: 'avoid' },
]

function PlaybookGroup({ title, empty, border, bg, tip, items, current, onSelectSymbol }: { title: string; empty: string; border: string; bg: string; tip: HelpTipKey; items: TradePlaybook[]; current?: string; onSelectSymbol: (symbol: string) => void }) {
  return (
    <div style={{ border: `1px solid ${border}`, background: bg, borderRadius: 8, padding: 12, minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <div style={{ color: 'var(--text)', fontSize: 15, fontWeight: 900, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {title}
          <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{items.length} 只</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.slice(0, 3).map(item => (
          <TradePlaybookSummaryCard key={`${title}-${item.stockCode}`} playbook={item} active={item.stockCode === current} onSelect={onSelectSymbol} />
        ))}
        {items.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: 13, border: '1px dashed var(--border)', borderRadius: 8, padding: 12 }}>{empty}</div>}
      </div>
    </div>
  )
}

export default function TomorrowPlaybookBoard({ current, onSelectSymbol }: Props) {
  const [data, setData] = React.useState<TomorrowPlaybookResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await fetchTomorrowPlaybook(12))
    } catch (err: any) {
      setError(err?.message || '明日交易剧本加载失败')
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
          <div style={{ minWidth: 0 }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 850, letterSpacing: 0.35, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              明日操作清单
              <HelpTooltip {...helpTips.tomorrowActionList}><HelpIcon /></HelpTooltip>
            </div>
            <h2 style={{ margin: '8px 0 0', color: 'var(--text)', fontSize: 26, lineHeight: 1.18, fontWeight: 900 }}>
              {data?.marketSummary.plainSummary || (loading ? '正在生成明日交易剧本...' : '等待生成明日交易剧本')}
            </h2>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5, marginTop: 8 }}>
              {data?.marketSummary.suggestedPositionSummary || '按自选/股票池最新模型、价格、资金和风险数据生成。'}
            </div>
          </div>
          <HelpTooltip {...helpTips.refreshPlaybook}>
            <span style={{ display: 'inline-flex' }}>
              <button type="button" className="dark-btn dark-btn-secondary" onClick={load} disabled={loading} style={{ opacity: loading ? 0.65 : 1 }}>
                {loading ? '更新中' : '刷新剧本'}
              </button>
            </span>
          </HelpTooltip>
        </div>

        {error ? (
          <div style={{ margin: 18, border: '1px solid rgba(248,113,113,0.35)', background: 'rgba(248,113,113,0.08)', color: '#fecaca', borderRadius: 8, padding: 12, fontSize: 13 }}>
            交易剧本暂不可用，页面会继续展示原有摘要模块。{error.slice(0, 160)}
          </div>
        ) : (
          <div style={{ padding: 18, display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 12 }}>
            {groupMeta.map(meta => (
              <PlaybookGroup
                key={meta.key}
                title={meta.title}
                empty={meta.empty}
                border={meta.border}
                bg={meta.bg}
                tip={meta.tip}
                items={data?.[meta.key] || []}
                current={current}
                onSelectSymbol={onSelectSymbol}
              />
            ))}
          </div>
        )}

        <div style={{ borderTop: '1px solid var(--border)', padding: 18, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 12 }}>
          <div>
            <div style={{ color: 'var(--text)', fontWeight: 850, fontSize: 14, marginBottom: 8, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              昨日计划复盘
              <HelpTooltip {...helpTips.tomorrowReviewSummary}><HelpIcon /></HelpTooltip>
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.55 }}>{data?.yesterdayReviewSummary.plainSummary || '等待生成复盘样本。'}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text)', fontWeight: 850, fontSize: 14, marginBottom: 8, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              风险提醒
              <HelpTooltip {...helpTips.riskReminder}><HelpIcon /></HelpTooltip>
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.55 }}>
              {(data?.riskWarnings?.length ? data.riskWarnings : ['只按计划内价位行动，高开急拉不追，跌破止损不补仓。']).slice(0, 2).join(' ')}
            </div>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)', padding: '10px 18px', color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5 }}>
          {data?.disclaimer || '本系统仅为模型辅助分析，不构成投资建议。市场有风险，交易需谨慎。'}
        </div>
      </div>
    </section>
  )
}