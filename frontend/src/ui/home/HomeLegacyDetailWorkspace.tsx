import React from 'react'
import type { PredictionHistoryResponse, StockInsightResponse } from '../../api/report'
import type { StockTradePlaybookResponse } from '../../api/tradePlaybook'
import FloatingModule from '../FloatingModule'
import HomeModelStatusSection from '../HomeModelStatusSection'
import HomePriceChartSection from '../HomePriceChartSection'
import HomeReviewDetailsSection from '../HomeReviewDetailsSection'
import HomeStockReportSection from '../HomeStockReportSection'
import HomeWatchlistPinnedSection from '../HomeWatchlistPinnedSection'
import HomeWatchlistSearchSection, { type WatchlistSearchResult } from '../HomeWatchlistSearchSection'
import RetailTradeDecisionCard from '../retail/RetailTradeDecisionCard'
import StockTradePlaybookPanel from '../trade-playbook/StockTradePlaybookPanel'
import WatchlistSnapshot from '../WatchlistSnapshot'

type WatchItem = {
  symbol: string
  name?: string
  sector?: string
  enabled: boolean
  pinned?: boolean
}

type TimeRange = React.ComponentProps<typeof HomePriceChartSection>['timeRange']
type ChartSeries = React.ComponentProps<typeof HomePriceChartSection>['chartSeries']
type StockReport = React.ComponentProps<typeof HomeStockReportSection>['report']
type JFetch = <T>(path: string, init?: RequestInit) => Promise<T>
type ToastType = 'success' | 'error' | 'info'

type HomeLegacyDetailWorkspaceProps = {
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
  merged: React.ComponentProps<typeof HomePriceChartSection>['merged']
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

export default function HomeLegacyDetailWorkspace({
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
}: HomeLegacyDetailWorkspaceProps) {
  const currentName = current ? watch.find(item => item.symbol === current)?.name : undefined
  const [tradePlaybookResponse, setTradePlaybookResponse] = React.useState<StockTradePlaybookResponse | null>(null)
  const [professionalMode, setProfessionalMode] = React.useState(false)

  return (
    <div style={{display:'flex', gap:12, alignItems:'flex-start'}}>
      <div style={{flex:2, minWidth:0}}>
        <StockTradePlaybookPanel
          symbol={current}
          onLoaded={setTradePlaybookResponse}
          fallback={<RetailTradeDecisionCard symbol={current} />}
        />

        <div style={{ margin: '0 12px 12px', display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>明日短线以计划价、止损线和仓位上限为核心。</div>
          <div style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
            <button
              type="button"
              onClick={() => setProfessionalMode(false)}
              style={{ padding: '7px 12px', border: 0, background: professionalMode ? 'transparent' : 'rgba(99,102,241,0.24)', color: professionalMode ? 'var(--text-muted)' : 'var(--text)', cursor: 'pointer', fontWeight: 800 }}
            >
              普通模式
            </button>
            <button
              type="button"
              onClick={() => setProfessionalMode(true)}
              style={{ padding: '7px 12px', border: 0, borderLeft: '1px solid var(--border)', background: professionalMode ? 'rgba(99,102,241,0.24)' : 'transparent', color: professionalMode ? 'var(--text)' : 'var(--text-muted)', cursor: 'pointer', fontWeight: 800 }}
            >
              专业模式
            </button>
          </div>
        </div>

        <div style={{ margin: '0 12px 12px' }}>
          <HomePriceChartSection
            current={current}
            currentName={currentName}
            timeRange={timeRange}
            onTimeRangeChange={setTimeRange}
            predictionHistory={predictionHistory}
            predictionHistoryLoading={predictionHistoryLoading}
            loading={loading}
            merged={merged}
            chartSeries={chartSeries}
            onOpenDiagnostics={setPipelineDrawerSymbol}
            tradePlaybook={tradePlaybookResponse?.playbook || null}
            professionalMode={professionalMode}
          />
        </div>

        <div style={{padding:12}}>
          <FloatingModule
            title="自选实时看板（今日）"
            subtitle="每分钟自动刷新，帮助你快速洞察自选股票表现"
            rightActions={
              <button
                onClick={() => watchlistSnapshotRefresh?.()}
                className="dark-btn dark-btn-secondary"
                disabled={!watchlistSnapshotRefresh}
                style={{opacity: watchlistSnapshotRefresh ? 1 : 0.6}}
              >
                刷新
              </button>
            }
            style={{paddingBottom: 12}}
          >
            <WatchlistSnapshot
              variant="content"
              pinnedOnly={true}
              activeSymbol={current}
              onSelectSymbol={setCurrent}
              onReadyRefresh={(refresh) => setWatchlistSnapshotRefresh(() => refresh)}
            />
          </FloatingModule>

          <div style={{height:12}} />

          <HomeWatchlistSearchSection
            name={name}
            onNameChange={setName}
            searching={searching}
            error={error}
            searchResults={searchResults}
            showSearchModal={showSearchModal}
            onSearch={handleSearchStocks}
            onSelectResult={handleStockSelect}
            onCloseModal={() => setShowSearchModal(false)}
          />
          <HomeWatchlistPinnedSection
            watch={watch}
            current={current}
            onSelectSymbol={setCurrent}
            onOpenManager={() => setWatchDrawerOpen(true)}
            onUnpin={async (item) => {
              try {
                await jfetch(`/watchlist/${item.symbol}/pin?pinned=false`, { method:'PATCH' })
                await loadWatch()
                watchlistSnapshotRefresh?.()
                showToast(`${item.name || item.symbol} 已取消置顶`, 'success')
              } catch {
                showToast('操作失败', 'error')
              }
            }}
            onDelete={(item) => {
              const stockDisplayName = item.name && item.name.trim() ? item.name : item.symbol
              showConfirm(
                `确定要删除 ${stockDisplayName} 吗？`,
                async () => {
                  setLoading(true)
                  try {
                    await jfetch(`/watchlist/${item.symbol}`, { method:'DELETE' })
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
            }}
          />
        </div>

        <details style={{ margin: '0 12px 12px', border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', overflow: 'hidden' }}>
          <summary style={{ padding: '12px 14px', cursor: 'pointer', color: 'var(--text)', fontWeight: 800 }}>
            专业数据 / 展开查看模型复盘明细
          </summary>
          <HomeReviewDetailsSection timeRange={timeRange} merged={merged} />
        </details>
      </div>

      <div style={{flex:1, display:'flex', flexDirection:'column', gap:12}}>
        <details style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', overflow: 'hidden' }}>
          <summary style={{ padding: '12px 14px', cursor: 'pointer', color: 'var(--text)', fontWeight: 800 }}>
            专业数据 / 展开查看模型状态与技术指标
          </summary>
          <div style={{ display:'flex', flexDirection:'column', gap:12, padding: 12 }}>
            <HomeModelStatusSection
              current={current}
              predictionHistory={predictionHistory}
              predictionHistoryLoading={predictionHistoryLoading}
              insight={insight}
              insightLoading={insightLoading}
              running={loading}
              onRunDaily={runDaily}
              onOpenDiagnostics={setPipelineDrawerSymbol}
            />
            <HomeStockReportSection
              current={current}
              currentName={currentName}
              report={report}
            />
          </div>
        </details>
      </div>
    </div>
  )
}