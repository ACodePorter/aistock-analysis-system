import React from 'react'
import type { PredictionHistoryResponse, StockInsightResponse } from '../../api/report'
import type { StockTradePlaybookResponse, TomorrowPlaybookResponse } from '../../api/tradePlaybook'
import HomeModelStatusSection from '../HomeModelStatusSection'
import HomePriceChartSection from '../HomePriceChartSection'
import HomeReviewDetailsSection from '../HomeReviewDetailsSection'
import HomeStockReportSection from '../HomeStockReportSection'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips, type HelpTipKey } from '../../config/helpTips'
import { TradePlaybookCard } from './TradePlaybookCard'

type TimeRange = React.ComponentProps<typeof HomePriceChartSection>['timeRange']
type ChartSeries = React.ComponentProps<typeof HomePriceChartSection>['chartSeries']
type StockReport = React.ComponentProps<typeof HomeStockReportSection>['report']

type Props = {
  current?: string
  currentName?: string
  response: StockTradePlaybookResponse | null
  tomorrowData: TomorrowPlaybookResponse | null
  professionalMode: boolean
  timeRange: TimeRange
  predictionHistory: PredictionHistoryResponse | null
  predictionHistoryLoading: boolean
  loading: boolean
  merged: any[]
  chartSeries: ChartSeries
  insight: StockInsightResponse | null
  insightLoading: boolean
  report: StockReport
  onTimeRangeChange: (range: TimeRange) => void
  onOpenDiagnostics: (symbol: string) => void
  onRunDaily: () => void
  onRefreshPlaybook: () => void
}

type TabKey = 'playbook' | 'chart' | 'reasons' | 'review' | 'professional'

const tabs: Array<{ key: TabKey; label: string; tip: HelpTipKey }> = [
  { key: 'playbook', label: '交易剧本', tip: 'currentPlaybook' },
  { key: 'chart', label: '预测图表', tip: 'predictionChart' },
  { key: 'reasons', label: '为什么这样判断', tip: 'agentReason' },
  { key: 'review', label: '复盘表现', tip: 'tradeReview' },
  { key: 'professional', label: '专业数据', tip: 'professionalData' },
]

function EmptyState({ text }: { text: string }) {
  return <div style={{ border: '1px dashed var(--border)', borderRadius: 8, padding: 18, color: 'var(--text-muted)' }}>{text}</div>
}

function AgentReasonPanel({ response }: { response: StockTradePlaybookResponse | null }) {
  const views = response?.agentViews || {}
  const entries = Object.entries(views).filter(([, view]) => !!view)
  const tipByKey: Record<string, HelpTipKey> = {
    priceForecast: 'agentPriceForecast',
    technicalTiming: 'agentTechnicalTiming',
    capitalFlow: 'agentCapitalFlow',
    newsSentiment: 'agentNewsSentiment',
    macroPolicy: 'agentMacroPolicy',
    companyFundamental: 'agentCompanyFundamental',
    riskControl: 'agentRiskControl',
  }
  if (!entries.length) return <EmptyState text="等待 Agent 解释数据。" />
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
      {entries.map(([key, view]) => (
        <div key={key} style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', padding: 12 }}>
          <div style={{ color: 'var(--text)', fontWeight: 850, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            {view?.title || key}
            <HelpTooltip {...helpTips[tipByKey[key] || 'agentPlainExplain']}><HelpIcon /></HelpTooltip>
          </div>
          {(view?.points || []).slice(0, 4).map((point, index) => <div key={`${key}-${index}`} style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.55, marginTop: index ? 6 : 0 }}>{point}</div>)}
        </div>
      ))}
    </div>
  )
}

function TradeReviewPanel({ tomorrowData, current }: { tomorrowData: TomorrowPlaybookResponse | null; current?: string }) {
  const reviews = (tomorrowData?.reviews || []).filter(review => !current || review.stockCode === current)
  const ReviewFlag = ({ label, active, tip }: { label: string; active: boolean; tip: HelpTipKey }) => (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, border: '1px solid var(--border)', borderRadius: 999, padding: '3px 8px', color: active ? '#86efac' : 'var(--text-muted)', background: active ? 'rgba(34,197,94,0.10)' : 'rgba(255,255,255,0.025)', fontSize: 11 }}>
      {label}: {active ? '是' : '否'}
      <HelpTooltip {...helpTips[tip]}><HelpIcon /></HelpTooltip>
    </span>
  )
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', padding: 12 }}>
        <div style={{ color: 'var(--text)', fontWeight: 850, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
          昨日计划复盘
          <HelpTooltip {...helpTips.yesterdayPlan}><HelpIcon /></HelpTooltip>
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.55 }}>{tomorrowData?.yesterdayReviewSummary.plainSummary || '等待生成复盘样本。'}</div>
      </div>
      {reviews.slice(0, 4).map(review => (
        <div key={review.id} style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', padding: 12 }}>
          <div style={{ color: 'var(--text)', fontWeight: 850, display: 'flex', alignItems: 'center', gap: 6 }}>
            {review.stockName}：{review.planResult}
            <HelpTooltip {...helpTips.planValid}><HelpIcon /></HelpTooltip>
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.55, marginTop: 6 }}>{review.plainReview}</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 9 }}>
            <ReviewFlag label="买入触发" active={review.buyTriggered} tip="buyTriggered" />
            <ReviewFlag label="目标1" active={review.takeProfit1Triggered} tip="targetReached" />
            <ReviewFlag label="目标2" active={review.takeProfit2Triggered} tip="targetReached" />
            <ReviewFlag label="止损" active={review.stopLossTriggered} tip="stopLossTriggered" />
          </div>
          {!!review.lessons?.length && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5, marginTop: 8, display: 'flex', alignItems: 'flex-start', gap: 6 }}>
              <span>优化建议：{review.lessons[0]}</span>
              <HelpTooltip {...helpTips.nextOptimization}><HelpIcon /></HelpTooltip>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default function StockDetailTabs({ current, currentName, response, tomorrowData, professionalMode, timeRange, predictionHistory, predictionHistoryLoading, loading, merged, chartSeries, insight, insightLoading, report, onTimeRangeChange, onOpenDiagnostics, onRunDaily, onRefreshPlaybook }: Props) {
  const [active, setActive] = React.useState<TabKey>('playbook')

  return (
    <section style={{ padding: '0 12px 12px' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(15,23,42,0.72)', overflow: 'hidden' }}>
        <div className="dark-tabs" style={{ margin: 12, overflowX: 'auto' }}>
          {tabs.map(tab => (
            <button key={tab.key} type="button" className={`dark-tab ${active === tab.key ? 'active' : ''}`} onClick={() => setActive(tab.key)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
              {tab.label}
              <HelpTooltip {...helpTips[tab.tip]}><HelpIcon /></HelpTooltip>
            </button>
          ))}
        </div>

        <div style={{ padding: 12 }}>
          {active === 'playbook' && (response ? <TradePlaybookCard response={response} onRefresh={onRefreshPlaybook} loading={loading} /> : <EmptyState text="请选择股票或等待交易剧本生成。" />)}
          {active === 'chart' && (
            <HomePriceChartSection
              current={current}
              currentName={currentName}
              timeRange={timeRange}
              onTimeRangeChange={onTimeRangeChange}
              predictionHistory={predictionHistory}
              predictionHistoryLoading={predictionHistoryLoading}
              loading={loading}
              merged={merged}
              chartSeries={chartSeries}
              onOpenDiagnostics={onOpenDiagnostics}
              tradePlaybook={response?.playbook || null}
              professionalMode={professionalMode}
            />
          )}
          {active === 'reasons' && <AgentReasonPanel response={response} />}
          {active === 'review' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <TradeReviewPanel tomorrowData={tomorrowData} current={current} />
              {professionalMode && <HomeReviewDetailsSection timeRange={timeRange} merged={merged} />}
            </div>
          )}
          {active === 'professional' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(320px,0.85fr)', gap: 12 }}>
              <HomeModelStatusSection current={current} predictionHistory={predictionHistory} predictionHistoryLoading={predictionHistoryLoading} insight={insight} insightLoading={insightLoading} running={loading} onRunDaily={onRunDaily} onOpenDiagnostics={onOpenDiagnostics} />
              <HomeStockReportSection current={current} currentName={currentName} report={report} />
            </div>
          )}
        </div>
      </div>
    </section>
  )
}