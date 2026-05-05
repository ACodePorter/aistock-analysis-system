import React from 'react'
import type { WatchlistSearchResult } from '../HomeWatchlistSearchSection'
import type { ExternalStockSearchResult } from './WatchlistManagerDrawer'

export type WatchItem = {
  symbol: string
  name?: string
  sector?: string
  enabled: boolean
  pinned?: boolean
}

type ToastType = 'success' | 'error' | 'info'
type JFetch = <T>(path: string, init?: RequestInit) => Promise<T>

type UseHomeWatchlistControlsOptions = {
  current?: string
  setCurrent: (symbol: string | undefined) => void
  watchlistSnapshotRefresh?: (() => void) | null
  jfetch: JFetch
  showToast: (message: string, type?: ToastType) => void
}

export function useHomeWatchlistControls({
  current,
  setCurrent,
  watchlistSnapshotRefresh,
  jfetch,
  showToast,
}: UseHomeWatchlistControlsOptions) {
  const [watch, setWatch] = React.useState<WatchItem[]>([])
  const [isWatchDrawerOpen, setWatchDrawerOpen] = React.useState(false)
  const [watchSearch, setWatchSearch] = React.useState('')
  const [externalResults, setExternalResults] = React.useState<ExternalStockSearchResult[]>([])
  const [searchingExternal, setSearchingExternal] = React.useState(false)
  const [name, setName] = React.useState('')
  const [searchResults, setSearchResults] = React.useState<WatchlistSearchResult[]>([])
  const [searching, setSearching] = React.useState(false)
  const [showSearchModal, setShowSearchModal] = React.useState(false)
  const externalSearchTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  const filteredWatch = React.useMemo(
    () => watch.filter(item => (item.name || item.symbol).toLowerCase().includes(watchSearch.toLowerCase())),
    [watch, watchSearch],
  )

  const loadWatch = React.useCallback(async () => {
    const list = await jfetch<WatchItem[]>('/watchlist')
    setWatch(list)
    if (!current && list.length) {
      const firstPinned = list.find(item => item.pinned)
      setCurrent(firstPinned ? firstPinned.symbol : list[0].symbol)
    }
  }, [current, jfetch, setCurrent])

  React.useEffect(() => {
    void loadWatch()
  }, [])

  React.useEffect(() => {
    if (externalSearchTimer.current) clearTimeout(externalSearchTimer.current)

    if (watchSearch.length >= 2 && filteredWatch.length === 0) {
      externalSearchTimer.current = setTimeout(async () => {
        setSearchingExternal(true)
        try {
          const results = await jfetch<ExternalStockSearchResult[]>(`/search_stock?q=${encodeURIComponent(watchSearch)}`)
          const existingSymbols = new Set(watch.map(item => item.symbol.toUpperCase()))
          setExternalResults((results || []).filter(item => !existingSymbols.has((item.ts_code || item.symbol || '').toUpperCase())))
        } catch {
          setExternalResults([])
        } finally {
          setSearchingExternal(false)
        }
      }, 400)
    } else {
      setExternalResults([])
      setSearchingExternal(false)
    }

    return () => {
      if (externalSearchTimer.current) clearTimeout(externalSearchTimer.current)
    }
  }, [watchSearch, filteredWatch.length, watch, jfetch])

  const handleSearchStocks = React.useCallback(async () => {
    if (!name || name.length < 1) {
      setSearchResults([])
      setShowSearchModal(false)
      return
    }

    setSearching(true)
    try {
      const query = name.toLowerCase()
      const matched = watch.filter(item => {
        const symbol = (item.symbol || '').toLowerCase()
        const stockName = (item.name || '').toLowerCase()
        return symbol.includes(query) || stockName.includes(query)
      }).map(item => ({
        ts_code: item.symbol,
        symbol: item.symbol,
        name: item.name || item.symbol,
        market: item.sector || '',
        pinned: !!item.pinned,
      }))
      setSearchResults(matched)
      setShowSearchModal(true)
    } finally {
      setSearching(false)
    }
  }, [name, watch])

  const handleStockSelect = React.useCallback(async (selectedStock: WatchlistSearchResult) => {
    try {
      const item = watch.find(candidate => candidate.symbol === selectedStock.ts_code)
      const newPinned = !item?.pinned
      await jfetch(`/watchlist/${selectedStock.ts_code}/pin?pinned=${newPinned}`, { method: 'PATCH' })
      await loadWatch()
      watchlistSnapshotRefresh?.()
      setSearchResults(prev => prev.map(stock =>
        stock.ts_code === selectedStock.ts_code ? { ...stock, pinned: newPinned } : stock,
      ))
      showToast(`${selectedStock.name} ${newPinned ? '已置顶到首页' : '已取消置顶'}`, 'success')
    } catch {
      showToast('操作失败', 'error')
    }
  }, [jfetch, loadWatch, showToast, watch, watchlistSnapshotRefresh])

  return {
    watch,
    isWatchDrawerOpen,
    setWatchDrawerOpen,
    watchSearch,
    setWatchSearch,
    filteredWatch,
    externalResults,
    setExternalResults,
    searchingExternal,
    name,
    setName,
    searchResults,
    searching,
    showSearchModal,
    setShowSearchModal,
    loadWatch,
    handleSearchStocks,
    handleStockSelect,
  }
}