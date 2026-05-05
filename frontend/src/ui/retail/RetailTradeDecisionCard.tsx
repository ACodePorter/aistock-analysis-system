import React from 'react'
import { fetchRetailDecision, type RetailAgentView, type RetailTradeDecisionCardData, type StockRetailDecisionResponse } from '../../api/retailDecision'
import { explainMetricForRetailUser } from './MetricTranslator'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../../config/helpTips'

type Props = {
  symbol?: string
}

const actionTone: Record<string, { bg: string; fg: string; border: string }> = {
  can_buy: { bg: 'rgba(34,197,94,0.16)', fg: '#86efac', border: 'rgba(34,197,94,0.38)' },
  small_position_watch: { bg: 'rgba(20,184,166,0.14)', fg: '#5eead4', border: 'rgba(20,184,166,0.36)' },
  wait: { bg: 'rgba(148,163,184,0.12)', fg: '#cbd5e1', border: 'rgba(148,163,184,0.30)' },
  sell_reduce: { bg: 'rgba(251,146,60,0.14)', fg: '#fdba74', border: 'rgba(251,146,60,0.36)' },
  avoid: { bg: 'rgba(248,113,113,0.15)', fg: '#fca5a5', border: 'rgba(248,113,113,0.40)' },
}

function toneFor(action?: string) {
  return actionTone[action || 'wait'] || actionTone.wait
}

function money(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return value.toFixed(2)
}

function percent(value: number | null | undefined, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '-'
  return `${(value * 100).toFixed(digits)}%`
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
    hold: '观望信号',
    sell: '卖出信号',
    strong_sell: '强卖信号',
    positive: '偏积极',
    negative: '偏消极',
  }[key] || '中性'
}

function MiniMetric({ label, value, detail, tip }: { label: string; value: React.ReactNode; detail?: string; tip?: HelpTipKey }) {
  return (
    <div style={{ border: '1px solid var(--border)', background: 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 12, minWidth: 0 }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        {label}
        {tip && <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>}
      </div>
      <div style={{ color: 'var(--text)', fontSize: 20, fontWeight: 850, lineHeight: 1.15 }}>{value}</div>
      {detail && <div style={{ color: 'var(--text-muted)', fontSize: 11, lineHeight: 1.45, marginTop: 6 }}>{detail}</div>}
    </div>
  )
}

function agentTipForTitle(title: string): HelpTipKey {
  if (title.includes('宏观') || title.includes('政策')) return 'agentMacroPolicy'
  if (title.includes('企业') || title.includes('基本面')) return 'agentCompanyFundamental'
  if (title.includes('新闻') || title.includes('情绪')) return 'agentNewsSentiment'
  if (title.includes('资金')) return 'agentCapitalFlow'
  if (title.includes('技术')) return 'agentTechnicalTiming'
  if (title.includes('预测') || title.includes('价格')) return 'agentPriceForecast'
  if (title.includes('风险')) return 'agentRiskControl'
  return 'agentPlainExplain'
}

function ReasonGroup({ view }: { view: RetailAgentView }) {
  return (
    <div style={{ border: '1px solid var(--border)', background: 'rgba(15,23,42,0.42)', borderRadius: 8, padding: 12, minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <div style={{ color: 'var(--text)', fontWeight: 800, fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {view.title}
          <HelpTooltip {...helpTips[agentTipForTitle(view.title)]}><HelpIcon /></HelpTooltip>
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>{stanceLabel(view.stance)}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {(view.points || []).slice(0, 3).map((point, index) => (
          <div key={`${view.title}-${index}`} style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5 }}>
            {point}
          </div>
        ))}
      </div>
    </div>
  )
}

function PricePlan({ card }: { card: RetailTradeDecisionCardData }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 10 }}>
      <MiniMetric label="建议买入区间" value={card.suggestedBuyRange?.label || '暂不生成'} detail="只在计划区间内考虑，不追高" tip="idealBuyRange" />
      <MiniMetric label="不建议追高价" value={money(card.doNotChaseAbove)} detail="高于该价更偏向等待" tip="doNotChaseAbove" />
      <MiniMetric label="止损价" value={money(card.stopLossPrice)} detail="跌破后本次短线计划失效" tip="stopLossPrice" />
      <MiniMetric label="目标卖出价 1" value={money(card.takeProfitPrice1)} detail="先看第一目标，分批处理" tip="takeProfitPrice1" />
      <MiniMetric label="目标卖出价 2" value={money(card.takeProfitPrice2)} detail="强势延续时才看第二目标" tip="takeProfitPrice2" />
      <MiniMetric label="建议仓位" value={card.suggestedPositionPct?.label || '0% - 0%'} detail="模型辅助仓位，不代表真实下单" tip="suggestedPosition" />
    </div>
  )
}

export default function RetailTradeDecisionCard({ symbol }: Props) {
  const [data, setData] = React.useState<StockRetailDecisionResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    setError(null)
    try {
      setData(await fetchRetailDecision(symbol))
    } catch (err: any) {
      setError(err?.message || '散户决策卡加载失败')
    } finally {
      setLoading(false)
    }
  }, [symbol])

  React.useEffect(() => {
    load()
  }, [load])

  if (!symbol) return null

  const card = data?.card
  const tone = toneFor(card?.finalAction)

  return (
    <section style={{ padding: 12 }}>
      <div style={{ border: `1px solid ${card ? tone.border : 'var(--border)'}`, background: 'linear-gradient(135deg, rgba(15,23,42,0.98), rgba(17,24,39,0.92))', borderRadius: 8, overflow: 'hidden' }}>
        <div style={{ padding: 18, display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', borderBottom: '1px solid var(--border)' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 800, letterSpacing: 0.4, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              这只股票现在是否值得买？
              <HelpTooltip {...helpTips.retailDecisionCard}><HelpIcon /></HelpTooltip>
            </div>
            <h2 style={{ margin: '8px 0 0', color: 'var(--text)', fontSize: 26, lineHeight: 1.18, fontWeight: 900 }}>
              {card ? card.plainConclusion : loading ? '正在生成散户决策卡...' : '暂无散户决策结果'}
            </h2>
          </div>
          <HelpTooltip {...helpTips.refreshData}>
            <span style={{ display: 'inline-flex' }}>
              <button type="button" onClick={load} className="dark-btn dark-btn-secondary" disabled={loading} style={{ opacity: loading ? 0.65 : 1 }}>
                {loading ? '更新中' : '刷新'}
              </button>
            </span>
          </HelpTooltip>
        </div>

        {error ? (
          <div style={{ margin: 18, border: '1px solid rgba(248,113,113,0.35)', background: 'rgba(248,113,113,0.08)', color: '#fecaca', borderRadius: 8, padding: 12, fontSize: 13 }}>
            新散户决策卡暂不可用，下面的专业数据仍可查看。{error.slice(0, 160)}
          </div>
        ) : card ? (
          <div style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', padding: '6px 12px', borderRadius: 999, background: tone.bg, color: tone.fg, border: `1px solid ${tone.border}`, fontSize: 13, fontWeight: 850 }}>
                {card.finalActionLabel}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>{card.oneSentenceReason}</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0,1fr))', gap: 10 }}>
              <MiniMetric label="当前价" value={money(card.currentPrice)} detail={card.latestPriceDate || undefined} tip="currentPrice" />
              <MiniMetric label="系统信心" value={card.confidenceLabel} detail={percent(card.confidence, 0)} tip="confidence" />
              <MiniMetric label="风险等级" value={card.riskLabel} detail={explainMetricForRetailUser('risk_score', card.riskScore)} tip="riskLevel" />
              <MiniMetric label="适合周期" value={card.applicableHorizon} detail="短线辅助，不适合长期替代研究" tip="targetHorizon" />
            </div>

            <PricePlan card={card} />

            <div style={{ border: '1px solid var(--border)', background: 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 12 }}>
              <div style={{ color: 'var(--text)', fontWeight: 800, fontSize: 14, marginBottom: 8, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                什么时候这套计划失效
                <HelpTooltip {...helpTips.planInvalidation}><HelpIcon /></HelpTooltip>
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.55 }}>{card.invalidationCondition}</div>
            </div>

            {card.dataWarnings.length > 0 && (
              <div style={{ border: '1px solid rgba(251,191,36,0.28)', background: 'rgba(251,191,36,0.08)', borderRadius: 8, padding: 12, color: '#fde68a', fontSize: 12, lineHeight: 1.55 }}>
                {card.dataWarnings.join(' ')}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
              {Object.values(data.agentViews || {}).map(view => <ReasonGroup key={view.title} view={view} />)}
            </div>

            <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
              {card.disclaimer}
            </div>
          </div>
        ) : (
          <div style={{ padding: 18, color: 'var(--text-muted)', fontSize: 13 }}>正在等待后端返回散户化解释。</div>
        )}
      </div>
    </section>
  )
}