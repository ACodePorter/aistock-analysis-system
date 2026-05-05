import React from 'react'
import ReactDOM from 'react-dom'
import * as ReactWindow from 'react-window'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips } from '../../config/helpTips'

const VirtualList = (ReactWindow as any).List as any

export type WatchlistManagerItem = {
  symbol: string
  name?: string
  sector?: string
  enabled: boolean
  pinned?: boolean
}

export type ExternalStockSearchResult = {
  symbol: string
  name: string
  ts_code: string
  market: string
}

type ToastType = 'success' | 'error' | 'info'
type JFetch = <T>(path: string, init?: RequestInit) => Promise<T>

type WatchDrawerRowProps = {
  index: number
  style: React.CSSProperties
  filteredWatch: WatchlistManagerItem[]
  current?: string
  setCurrent: (symbol: string | undefined) => void
  setWatchDrawerOpen: (open: boolean) => void
  jfetch: JFetch
  loadWatch: () => Promise<void>
  watchlistSnapshotRefresh?: (() => void) | null
  showToast: (message: string, type?: ToastType) => void
  showConfirm: (message: string, onConfirm: () => void, title?: string) => void
  setLoading: (loading: boolean) => void
}

const WatchDrawerRow = React.memo(({
  index,
  style,
  filteredWatch,
  current,
  setCurrent,
  setWatchDrawerOpen,
  jfetch,
  loadWatch,
  watchlistSnapshotRefresh,
  showToast,
  showConfirm,
  setLoading,
}: WatchDrawerRowProps) => {
  const item = filteredWatch?.[index]
  if (!item) return null

  const label = item.name && item.name.trim() ? `${item.name} (${item.symbol})` : item.symbol
  const isActive = current === item.symbol
  const isPinned = !!item.pinned

  return (
    <div
      style={{
        ...style,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 12px',
        borderBottom: '1px solid var(--border)',
        background: isActive ? 'var(--primary-light)' : 'transparent',
      }}
    >
      <button
        onClick={() => { setCurrent(item.symbol); setWatchDrawerOpen(false) }}
        style={{ flex: 1, textAlign: 'left', border: 'none', background: 'transparent', padding: '8px 4px', fontSize: 13, cursor: 'pointer', color: isActive ? 'var(--primary)' : 'var(--text)', fontWeight: isActive ? 600 : 400 }}
      >
        {isPinned && <span style={{ marginRight: 4 }}>📌</span>}
        {label}
      </button>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <HelpTooltip {...helpTips.pinStock} content={isPinned ? '取消后，该股票仍在股票池中，但不会优先出现在首页顶部。切换股票后，交易剧本、预测图表、复盘和专业数据都会同步更新。' : helpTips.pinStock.content}>
          <button
            onClick={async () => {
              try {
                await jfetch(`/watchlist/${item.symbol}/pin?pinned=${!isPinned}`, { method: 'PATCH' })
                await loadWatch()
                watchlistSnapshotRefresh?.()
                showToast(`${item.name || item.symbol} ${isPinned ? '已取消置顶' : '已置顶到首页'}`, 'success')
              } catch {
                showToast('操作失败', 'error')
              }
            }}
            style={{ padding: '4px 10px', border: isPinned ? '1px solid rgba(245,158,11,0.3)' : '1px solid rgba(99,102,241,0.3)', borderRadius: 6, background: isPinned ? 'rgba(245,158,11,0.1)' : 'rgba(99,102,241,0.1)', color: isPinned ? '#f59e0b' : 'var(--primary)', fontSize: 11, cursor: 'pointer', fontWeight: 500 }}
          >
            {isPinned ? '取消置顶' : '置顶'}
          </button>
        </HelpTooltip>
        <HelpTooltip {...helpTips.deleteStock}>
          <button
            onClick={() => {
              const stockDisplayName = item.name && item.name.trim() ? item.name : item.symbol
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
            }}
            style={{ padding: '4px 10px', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 6, background: 'rgba(239,68,68,0.1)', color: 'var(--accent-red)', fontSize: 11, cursor: 'pointer', fontWeight: 500 }}
          >
            删除
          </button>
        </HelpTooltip>
      </div>
    </div>
  )
})

type WatchlistManagerDrawerProps = {
  open: boolean
  filteredWatch: WatchlistManagerItem[]
  current?: string
  watchSearch: string
  externalResults: ExternalStockSearchResult[]
  searchingExternal: boolean
  jfetch: JFetch
  loadWatch: () => Promise<void>
  watchlistSnapshotRefresh?: (() => void) | null
  setCurrent: (symbol: string | undefined) => void
  setWatchDrawerOpen: (open: boolean) => void
  setWatchSearch: (value: string) => void
  setExternalResults: React.Dispatch<React.SetStateAction<ExternalStockSearchResult[]>>
  setLoading: (loading: boolean) => void
  showToast: (message: string, type?: ToastType) => void
  showConfirm: (message: string, onConfirm: () => void, title?: string) => void
}

export default function WatchlistManagerDrawer({
  open,
  filteredWatch,
  current,
  watchSearch,
  externalResults,
  searchingExternal,
  jfetch,
  loadWatch,
  watchlistSnapshotRefresh,
  setCurrent,
  setWatchDrawerOpen,
  setWatchSearch,
  setExternalResults,
  setLoading,
  showToast,
  showConfirm,
}: WatchlistManagerDrawerProps) {
  if (!open) return null

  const listHeight = window.innerHeight - 180 - (externalResults.length > 0 ? 200 : 0)
  const rowProps = {
    filteredWatch,
    current,
    setCurrent,
    setWatchDrawerOpen,
    jfetch,
    loadWatch,
    watchlistSnapshotRefresh,
    showToast,
    showConfirm,
    setLoading,
  }

  return ReactDOM.createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.7)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        justifyContent: 'flex-end',
        zIndex: 9999,
      }}
      onClick={() => setWatchDrawerOpen(false)}
    >
      <div
        style={{
          width: 440,
          maxWidth: '90vw',
          height: '100vh',
          background: 'var(--surface-dark)',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.5)',
          padding: 24,
          display: 'flex',
          flexDirection: 'column',
          borderLeft: '1px solid var(--border)',
        }}
        onClick={event => event.stopPropagation()}
      >
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16}}>
          <div style={{fontSize:18, fontWeight:700, color:'var(--text)', display:'flex', alignItems:'center', gap:6}}>
            自选管理 · {filteredWatch.length} 只
            <HelpTooltip {...helpTips.manageStockPool}><HelpIcon /></HelpTooltip>
          </div>
          <button
            onClick={() => setWatchDrawerOpen(false)}
            style={{fontSize:24, border:'none', background:'transparent', cursor:'pointer', color:'var(--text-muted)', lineHeight:1}}
          >
            ×
          </button>
        </div>

        <input
          value={watchSearch}
          onChange={event => setWatchSearch(event.target.value)}
          placeholder="搜索名称或代码（池内无结果自动搜全市场）"
          className="dark-search-input"
          style={{
            width:'100%',
            marginBottom:16,
            borderRadius: 8,
          }}
        />

        <div style={{flex:1, minHeight:0, overflowY:'auto'}}>
          {filteredWatch.length > 0 ? (
            <VirtualList
              height={listHeight}
              style={{width: '100%'}}
              rowHeight={48}
              rowCount={filteredWatch.length}
              overscanCount={10}
              rowComponent={WatchDrawerRow}
              rowProps={rowProps}
            />
          ) : watchSearch.length >= 2 ? (
            <div style={{padding:'16px 0', textAlign:'center', color:'var(--text-muted)', fontSize:13}}>
              池内无匹配，{searchingExternal ? '正在搜索全市场...' : externalResults.length > 0 ? `找到 ${externalResults.length} 只外部股票：` : '全市场也无匹配结果'}
            </div>
          ) : watchSearch.length > 0 ? (
            <div style={{padding:'16px 0', textAlign:'center', color:'var(--text-muted)', fontSize:13}}>输入至少2个字符搜索</div>
          ) : (
            <VirtualList
              height={window.innerHeight - 180}
              style={{width: '100%'}}
              rowHeight={48}
              rowCount={filteredWatch.length}
              overscanCount={10}
              rowComponent={WatchDrawerRow}
              rowProps={rowProps}
            />
          )}

          {externalResults.length > 0 && (
            <div style={{borderTop: '1px solid var(--border)', paddingTop: 8}}>
              {externalResults.slice(0, 20).map(result => (
                <div key={result.ts_code || result.symbol} style={{
                  display:'flex', alignItems:'center', justifyContent:'space-between',
                  padding:'8px 12px', borderBottom:'1px solid var(--border)',
                }}>
                  <span style={{fontSize:13, color:'var(--text)'}}>{result.name} ({result.ts_code || result.symbol})</span>
                  <HelpTooltip {...helpTips.addStock}>
                    <button
                      onClick={async () => {
                        try {
                          await jfetch('/watchlist', {
                            method: 'POST',
                            body: JSON.stringify({ symbol: result.ts_code || result.symbol, name: result.name, sector: result.market || '', enabled: true }),
                          })
                          await loadWatch()
                          setExternalResults(prev => prev.filter(item => item.ts_code !== result.ts_code))
                          showToast(`${result.name} 已加入股票池`, 'success')
                        } catch {
                          showToast('添加失败', 'error')
                        }
                      }}
                      style={{padding:'4px 12px', border:'1px solid rgba(34,197,94,0.3)', borderRadius:6, background:'rgba(34,197,94,0.1)', color:'#22c55e', fontSize:11, cursor:'pointer', fontWeight:500}}
                    >
                      + 加入股票池
                    </button>
                  </HelpTooltip>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}