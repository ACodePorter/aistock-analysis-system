import React from 'react'
import type { PredictionHistoryResponse, StockInsightResponse } from '../../api/report'
import { fetchTomorrowPlaybook, fetchTradePlaybook, type StockTradePlaybookResponse, type TomorrowPlaybookResponse } from '../../api/tradePlaybook'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips } from '../../config/helpTips'
import StockPoolSelectorBar from './StockPoolSelectorBar'
import type { WatchItem } from './useHomeWatchlistControls'
import type { WatchlistSearchResult } from '../HomeWatchlistSearchSection'
import SelectedStockStickyStatus from '../trade-playbook/SelectedStockStickyStatus'
import StockDetailTabs from '../trade-playbook/StockDetailTabs'
import WatchlistSnapshot from '../WatchlistSnapshot'
import ActionableTradingCenter from './ActionableTradingCenter'
import AgentDecisionTracePanel from './AgentDecisionTracePanel'
import AgentWorkStatusStrip from './AgentWorkStatusStrip'
import InlineAgentChatBox from './InlineAgentChatBox'
import TodayActionEvents from './TodayActionEvents'
import UserPortfolioOpportunityPanel from './UserPortfolioOpportunityPanel'
import { buildActionableTradingDashboard, buildAgentDecisionTrace, buildTodayActionEvents } from './actionability'
import type { AgentStatusSnapshot } from '../../api/agent'

type TimeRange = React.ComponentProps<typeof StockDetailTabs>['timeRange']
type ChartSeries = React.ComponentProps<typeof StockDetailTabs>['chartSeries']
type StockReport = React.ComponentProps<typeof StockDetailTabs>['report']
type JFetch = <T>(path: string, init?: RequestInit) => Promise<T>
type ToastType = 'success' | 'error' | 'info'

type Props = {
  current?: string
  watch: WatchItem[]
  watchlistSnapshotRefresh?: (() => void) | null
  name: string
  searching: boolean
  error?: string
  searchResults: WatchlistSearchResult[]
  showSearchModal: boolean
  timeRange: TimeRange
  predictionHistory: PredictionHistoryResponse | null
  predictionHistoryLoading: boolean
  loading: boolean
  merged: any[]
  chartSeries: ChartSeries
  insight: StockInsightResponse | null
  insightLoading: boolean
  report: StockReport
  jfetch: JFetch
  loadWatch: () => Promise<void>
  runDaily: () => void
  setCurrent: (symbol: string | undefined) => void
  setWatchlistSnapshotRefresh: React.Dispatch<React.SetStateAction<(() => void) | null>>
  setName: (value: string) => void
  setShowSearchModal: (show: boolean) => void
  setWatchDrawerOpen: (open: boolean) => void
  setTimeRange: (range: TimeRange) => void
  setPipelineDrawerSymbol: (symbol: string | null) => void
  setLoading: (loading: boolean) => void
  handleSearchStocks: () => void
  handleStockSelect: (stock: WatchlistSearchResult) => void
  showToast: (message: string, type?: ToastType) => void
  showConfirm: (message: string, onConfirm: () => void, title?: string) => void
}

export default function HomeDecisionWorkspace({
  current,
  watch,
  watchlistSnapshotRefresh,
  name,
  searching,
  error,
  searchResults,
  showSearchModal,
  timeRange,
  predictionHistory,
  predictionHistoryLoading,
  loading,
  merged,
  chartSeries,
  insight,
  insightLoading,
  report,
  jfetch,
  loadWatch,
  runDaily,
  setCurrent,
  setWatchlistSnapshotRefresh,
  setName,
  setShowSearchModal,
  setWatchDrawerOpen,
  setTimeRange,
  setPipelineDrawerSymbol,
  setLoading,
  handleSearchStocks,
  handleStockSelect,
  showToast,
  showConfirm,
}: Readonly<Props>) {
  const [professionalMode, setProfessionalMode] = React.useState(false)
  const [tomorrowData, setTomorrowData] = React.useState<TomorrowPlaybookResponse | null>(null)
  const [tomorrowLoading, setTomorrowLoading] = React.useState(false)
  const [tomorrowError, setTomorrowError] = React.useState<string | null>(null)
  const [stockResponse, setStockResponse] = React.useState<StockTradePlaybookResponse | null>(null)
  const [stockLoading, setStockLoading] = React.useState(false)
  const [agentStatuses, setAgentStatuses] = React.useState<AgentStatusSnapshot[]>([])

  const currentName = current ? watch.find(item => item.symbol === current)?.name : undefined

  const loadTomorrow = React.useCallback(async () => {
    setTomorrowLoading(true)
    setTomorrowError(null)
    try {
      setTomorrowData(await fetchTomorrowPlaybook(12))
    } catch (err: any) {
      setTomorrowError(err?.message || '明日交易剧本加载失败')
    } finally {
      setTomorrowLoading(false)
    }
  }, [])

  const loadStockPlaybook = React.useCallback(async () => {
    if (!current) {
      setStockResponse(null)
      return
    }
    setStockLoading(true)
    try {
      setStockResponse(await fetchTradePlaybook(current))
    } catch {
      setStockResponse(null)
    } finally {
      setStockLoading(false)
    }
  }, [current])

  React.useEffect(() => {
    loadTomorrow()
  }, [loadTomorrow])

  React.useEffect(() => {
    loadStockPlaybook()
  }, [loadStockPlaybook])

  const refreshAll = React.useCallback(() => {
    loadTomorrow()
    loadStockPlaybook()
    watchlistSnapshotRefresh?.()
  }, [loadTomorrow, loadStockPlaybook, watchlistSnapshotRefresh])

  const openAgentLogs = React.useCallback((taskId?: string) => {
    const query = taskId ? `?taskId=${encodeURIComponent(taskId)}` : ''
    try { globalThis.location.hash = `#agent-logs${query}` } catch { /* noop */ }
  }, [])

  const actionableDashboard = React.useMemo(
    () => buildActionableTradingDashboard(tomorrowData, stockResponse),
    [stockResponse, tomorrowData],
  )
  const todayEvents = React.useMemo(
    () => buildTodayActionEvents(actionableDashboard, agentStatuses),
    [actionableDashboard, agentStatuses],
  )
  const agentTrace = React.useMemo(
    () => buildAgentDecisionTrace(stockResponse, agentStatuses),
    [agentStatuses, stockResponse],
  )

  const handleDelete = React.useCallback((item: WatchItem) => {
    const stockDisplayName = item.name?.trim() ? item.name : item.symbol
    showConfirm(
      `确定要删除 ${stockDisplayName} 吗？`,
      async () => {
        setLoading(true)
        try {
          await jfetch(`/watchlist/${item.symbol}`, { method: 'DELETE' })
          await loadWatch()
          if (current === item.symbol) setCurrent(undefined)
          showToast(`${stockDisplayName} 已删除`, 'success')
        } catch {
          showToast('删除失败', 'error')
        } finally {
          setLoading(false)
        }
      },
      '确认删除',
    )
  }, [current, jfetch, loadWatch, setCurrent, setLoading, showConfirm, showToast])

  return (
    <div>
      <StockPoolSelectorBar
        current={current}
        watch={watch}
        name={name}
        searching={searching}
        error={error}
        searchResults={searchResults}
        showSearchModal={showSearchModal}
        professionalMode={professionalMode}
        onNameChange={setName}
        onSearch={handleSearchStocks}
        onSelectSymbol={setCurrent}
        onToggleSearchResultPin={handleStockSelect}
        onCloseModal={() => setShowSearchModal(false)}
        onOpenManager={() => setWatchDrawerOpen(true)}
        onModeChange={setProfessionalMode}
        onRefresh={refreshAll}
      />
      <AgentWorkStatusStrip selectedStockCode={current} onOpenLogs={openAgentLogs} onStatusChange={setAgentStatuses} />
      <InlineAgentChatBox selectedStockCode={current} selectedMode={professionalMode ? 'professional' : 'normal'} onOpenLogs={openAgentLogs} />
      <UserPortfolioOpportunityPanel selectedSymbol={current} onSelectSymbol={setCurrent} onRefreshPlaybook={refreshAll} />
      <ActionableTradingCenter dashboard={actionableDashboard} loading={tomorrowLoading || stockLoading} error={tomorrowError} onRefresh={refreshAll} onSelectSymbol={setCurrent} />
      <SelectedStockStickyStatus playbook={stockResponse?.playbook || null} current={current} currentName={currentName} />
      <AgentDecisionTracePanel trace={agentTrace} onOpenLogs={openAgentLogs} />
      <TodayActionEvents events={todayEvents} onSelectSymbol={setCurrent} />
      <StockDetailTabs
        current={current}
        currentName={currentName}
        response={stockResponse}
        tomorrowData={tomorrowData}
        professionalMode={professionalMode}
        timeRange={timeRange}
        predictionHistory={predictionHistory}
        predictionHistoryLoading={predictionHistoryLoading}
        loading={loading || stockLoading}
        merged={merged}
        chartSeries={chartSeries}
        insight={insight}
        insightLoading={insightLoading}
        report={report}
        onTimeRangeChange={setTimeRange}
        onOpenDiagnostics={setPipelineDrawerSymbol}
        onRunDaily={runDaily}
        onRefreshPlaybook={loadStockPlaybook}
      />

      <section style={{ padding: '0 12px 12px' }}>
        <details style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', overflow: 'hidden' }}>
          <summary style={{ padding: '12px 14px', cursor: 'pointer', color: 'var(--text)', fontWeight: 850, display: 'flex', alignItems: 'center', gap: 8 }}>
            自选实时看板（折叠）
            <HelpTooltip {...helpTips.watchlistSnapshot}><HelpIcon /></HelpTooltip>
          </summary>
          <div style={{ padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 10 }}>
              <button className="dark-btn dark-btn-secondary" onClick={() => watchlistSnapshotRefresh?.()} disabled={!watchlistSnapshotRefresh}>刷新看板</button>
            </div>
            <WatchlistSnapshot variant="content" pinnedOnly={true} activeSymbol={current} onSelectSymbol={setCurrent} onReadyRefresh={(refresh) => setWatchlistSnapshotRefresh(() => refresh)} />
          </div>
        </details>
      </section>

      {watch.length > 0 && (
        <section style={{ padding: '0 12px 12px' }}>
          <details style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', overflow: 'hidden' }}>
            <summary style={{ padding: '12px 14px', cursor: 'pointer', color: 'var(--text)', fontWeight: 850, display:'flex', alignItems:'center', gap:8 }}>
              低频股票池维护
              <HelpTooltip {...helpTips.manageStockPool}><HelpIcon /></HelpTooltip>
            </summary>
            <div style={{ padding: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {watch.slice(0, 30).map(item => (
                <span key={item.symbol} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', border: '1px solid var(--border)', borderRadius: 999, padding: '5px 9px', color: 'var(--text-muted)', fontSize: 12 }}>
                  <HelpTooltip {...helpTips.stockPoolTags}>
                    <button type="button" onClick={() => setCurrent(item.symbol)} style={{ border: 0, background: 'transparent', color: 'var(--text)', cursor: 'pointer', padding: 0 }}>{item.name || item.symbol}</button>
                  </HelpTooltip>
                  <HelpTooltip {...helpTips.deleteStock}>
                    <button type="button" aria-label={`删除 ${item.name || item.symbol}`} onClick={() => handleDelete(item)} style={{ border: 0, background: 'transparent', color: '#fca5a5', cursor: 'pointer', padding: 0 }}>×</button>
                  </HelpTooltip>
                </span>
              ))}
            </div>
          </details>
        </section>
      )}
    </div>
  )
}