import React from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'
import HelpTooltip from './components/HelpTooltip'
import { helpTips } from '../config/helpTips'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StockItem {
  symbol: string
  name?: string | null
  start_date?: string | null
  article_count: number
  last_updated_at?: string | null
  is_updated?: boolean
  completion_percentage?: number
  fields_filled?: number
  total_fields?: number
}

interface ProfileDetail {
  symbol: string
  name: string
  completion_percentage: number
  fields_filled: number
  total_fields: number
  status: 'completed' | 'incomplete'
}

interface ProgressData {
  total_stocks: number
  completed_profiles: number
  progress_percentage: number
  average_completion: number
  stocks_detail: ProfileDetail[]
  page: number
  page_size: number
}

interface PoolMember {
  symbol: string
  company_name: string | null
  first_seen_date: string | null
  last_seen_date: string | null
  source: string
  industry: string | null
  days_active: number | null
  has_profile: boolean
  profile_completion?: number
}

interface ProfileStatusData {
  total_active: number
  completed: number
  incomplete: number
  avg_completion: number
  incomplete_stocks: {
    symbol: string
    company_name: string
    completion_pct: number
    has_profile_row: boolean
    last_refreshed: string | null
  }[]
}

interface ProfileCompletionStatus {
  running: boolean
  total: number
  processed: number
  successful: number
  failed: number
  skipped: number
  current_symbol: string | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}

interface PoolStats {
  total_active: number
  manual_count: number
  auto_count: number
  with_profile: number
  profile_rate: number
  latest_update: string | null
}

interface SearchResult {
  symbol: string
  name: string
  code: string
  in_pool: boolean
}

/* ------------------------------------------------------------------ */
/*  Sub-component: Stock Pool Manager                                  */
/* ------------------------------------------------------------------ */

function StockPoolManager({ onOpen }: { onOpen: (sym: string) => void }) {
  const [poolMembers, setPoolMembers] = React.useState<PoolMember[]>([])
  const [poolStats, setPoolStats] = React.useState<PoolStats | null>(null)
  const [poolPage, setPoolPage] = React.useState(1)
  const [poolTotal, setPoolTotal] = React.useState(0)
  const poolPageSize = 20

  const [searchQuery, setSearchQuery] = React.useState('')
  const [searchResults, setSearchResults] = React.useState<SearchResult[]>([])
  const [searching, setSearching] = React.useState(false)
  const [showSearch, setShowSearch] = React.useState(false)
  const [addingSymbol, setAddingSymbol] = React.useState<string | null>(null)

  const [sourceFilter, setSourceFilter] = React.useState<string>('all')
  const [profileFilterVal, setProfileFilterVal] = React.useState<string>('all')
  const [poolKeyword, setPoolKeyword] = React.useState('')
  const [poolKeywordInput, setPoolKeywordInput] = React.useState('')
  const poolKeywordTimerRef = React.useRef<ReturnType<typeof setTimeout>>()
  const [backfillStatus, setBackfillStatus] = React.useState<any>(null)

  // --- 画像补全状态 ---
  const [profileStatus, setProfileStatus] = React.useState<ProfileStatusData | null>(null)
  const [completionStatus, setCompletionStatus] = React.useState<ProfileCompletionStatus | null>(null)
  const [triggeringCompletion, setTriggeringCompletion] = React.useState(false)

  // --- 单只股票画像详情弹窗 ---
  const [detailSymbol, setDetailSymbol] = React.useState<string | null>(null)
  const [detailData, setDetailData] = React.useState<any>(null)
  const [detailLoading, setDetailLoading] = React.useState(false)
  const [rebuildLoading, setRebuildLoading] = React.useState(false)
  const [supplementaryInfo, setSupplementaryInfo] = React.useState('')
  const [rebuildMsg, setRebuildMsg] = React.useState<string | null>(null)

  const searchTimerRef = React.useRef<ReturnType<typeof setTimeout>>()

  // Load pool members
  const loadPool = React.useCallback(async (page = 1) => {
    try {
      const params = new URLSearchParams({
        limit: String(poolPageSize),
        offset: String((page - 1) * poolPageSize),
      })
      if (sourceFilter !== 'all') params.set('source', sourceFilter)
      if (profileFilterVal !== 'all') params.set('profile_filter', profileFilterVal)
      if (poolKeyword.trim()) params.set('keyword', poolKeyword.trim())
      const res = await fetch(buildApiUrl(`/api/stock-pool?${params}`))
      if (!res.ok) return
      const data = await res.json()
      setPoolMembers(data.rows || [])
      setPoolTotal(data.total || 0)
    } catch (e) {
      console.error('Load pool failed:', e)
    }
  }, [sourceFilter, profileFilterVal, poolKeyword])

  // Load stats
  const loadStats = React.useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.STATS))
      if (res.ok) setPoolStats(await res.json())
    } catch {}
  }, [])

  // Load backfill status
  const loadBackfillStatus = React.useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.BACKFILL_STATUS))
      if (res.ok) {
        const data = await res.json()
        setBackfillStatus(data)
      }
    } catch {}
  }, [])

  // Load profile status overview
  const loadProfileStatus = React.useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.PROFILE_STATUS))
      if (res.ok) setProfileStatus(await res.json())
    } catch {}
  }, [])

  // Load profile completion task progress
  const loadCompletionStatus = React.useCallback(async () => {
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.PROFILE_COMPLETION_STATUS))
      if (res.ok) setCompletionStatus(await res.json())
    } catch {}
  }, [])

  // Trigger profile completion
  const triggerProfileCompletion = React.useCallback(async (batchLimit = 0) => {
    setTriggeringCompletion(true)
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.PROFILE_COMPLETION), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_limit: batchLimit, delay: 3.0, force: false }),
      })
      if (res.ok) {
        loadCompletionStatus()
      }
    } catch {} finally { setTriggeringCompletion(false) }
  }, [])

  // Open profile detail modal
  const openProfileDetail = React.useCallback(async (symbol: string) => {
    setDetailSymbol(symbol)
    setDetailData(null)
    setDetailLoading(true)
    setSupplementaryInfo('')
    setRebuildMsg(null)
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.STOCK_PROFILE(symbol)))
      if (res.ok) {
        setDetailData(await res.json())
      } else if (res.status === 404) {
        setDetailData({ _empty: true, symbol })
      }
    } catch {} finally { setDetailLoading(false) }
  }, [])

  // Trigger rebuild
  const triggerRebuild = React.useCallback(async () => {
    if (!detailSymbol) return
    setRebuildLoading(true)
    setRebuildMsg(null)
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.REBUILD_PROFILE(detailSymbol)), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ supplementary_info: supplementaryInfo, force: true }),
      })
      if (res.ok) {
        const data = await res.json()
        setRebuildMsg(data.message || '重构任务已启动')
        setTimeout(() => openProfileDetail(detailSymbol), 8000)
      } else {
        const err = await res.json().catch(() => ({}))
        setRebuildMsg(`失败: ${err.detail || res.status}`)
      }
    } catch (e: any) {
      setRebuildMsg(`网络错误: ${e.message}`)
    } finally { setRebuildLoading(false) }
  }, [detailSymbol, supplementaryInfo, openProfileDetail])

  React.useEffect(() => { loadPool(poolPage); loadStats(); loadBackfillStatus(); loadProfileStatus(); loadCompletionStatus() }, [poolPage, sourceFilter, profileFilterVal, poolKeyword])

  // Poll backfill status while running
  React.useEffect(() => {
    if (!backfillStatus?.running) return
    const timer = setInterval(loadBackfillStatus, 5000)
    return () => clearInterval(timer)
  }, [backfillStatus?.running])

  // Poll completion status while running
  React.useEffect(() => {
    if (!completionStatus?.running) return
    const timer = setInterval(() => { loadCompletionStatus(); loadProfileStatus() }, 5000)
    return () => clearInterval(timer)
  }, [completionStatus?.running])

  // Search stocks
  const handleSearchInput = React.useCallback((val: string) => {
    setSearchQuery(val)
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!val.trim()) { setSearchResults([]); return }
    searchTimerRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.SEARCH(val)))
        if (res.ok) {
          const data = await res.json()
          setSearchResults(data.results || [])
        }
      } catch {
        setSearchResults([])
      } finally { setSearching(false) }
    }, 500)
  }, [])

  const [addError, setAddError] = React.useState<string | null>(null)

  // Add stock
  const addStock = React.useCallback(async (symbol: string, name?: string) => {
    setAddingSymbol(symbol)
    setAddError(null)
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.ADD), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, name }),
      })
      if (res.ok) {
        setSearchResults(prev => prev.map(r => r.symbol === symbol ? { ...r, in_pool: true } : r))
        loadPool(poolPage)
        loadStats()
      } else {
        const err = await res.json().catch(() => ({}))
        setAddError(err.detail || `添加失败 (${res.status})`)
      }
    } catch (e: any) {
      setAddError(`网络错误: ${e.message}`)
    } finally { setAddingSymbol(null) }
  }, [poolPage, loadPool, loadStats])

  // Remove stock
  const removeStock = React.useCallback(async (symbol: string) => {
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.REMOVE(symbol)), { method: 'DELETE' })
      if (res.ok) {
        loadPool(poolPage)
        loadStats()
      }
    } catch {}
  }, [poolPage, loadPool, loadStats])

  const [importing, setImporting] = React.useState(false)

  // Import today's Top10
  const importToday = React.useCallback(async () => {
    setImporting(true)
    try {
      const res = await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.IMPORT_TODAY), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (res.ok) {
        const data = await res.json()
        alert(`导入完成: 新增 ${data.added} 只，共 ${data.total_candidates} 只候选`)
        loadPool(poolPage)
        loadStats()
      } else {
        alert('导入失败，请查看后端日志')
      }
    } catch (e: any) {
      alert(`导入失败: ${e.message}`)
    } finally { setImporting(false) }
  }, [poolPage, loadPool, loadStats])

  // Trigger backfill
  const triggerBackfill = React.useCallback(async () => {
    try {
      await fetch(buildApiUrl(API_ENDPOINTS.STOCK_POOL.BACKFILL), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ months: 6 }),
      })
      loadBackfillStatus()
    } catch {}
  }, [])

  const sourceBadge = (source: string) => {
    const colors: Record<string, string> = {
      manual: 'rgba(99,102,241,0.3)',
      top_movers: 'rgba(251,191,36,0.3)',
      backfill: 'rgba(156,163,175,0.3)',
      bulk_import: 'rgba(34,197,94,0.2)',
    }
    const labels: Record<string, string> = {
      manual: '手动',
      top_movers: '涨跌榜',
      backfill: '回填',
      bulk_import: '批量导入',
    }
    return (
      <span style={{
        fontSize: 11, padding: '1px 6px', borderRadius: 4,
        background: colors[source] || 'rgba(255,255,255,0.1)',
        color: 'var(--text-muted)',
      }}>
        {labels[source] || source}
      </span>
    )
  }

  const totalPages = Math.ceil(poolTotal / poolPageSize)

  return (
    <div style={{ marginBottom: 24 }}>
      {/* Stats bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 12, padding: '10px 14px',
        background: 'rgba(99,102,241,0.08)', border: '1px solid var(--border)', borderRadius: 8,
      }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
          股票池管理
        </div>
        <div style={{ display: 'flex', gap: 20, fontSize: 12, color: 'var(--text-muted)' }}>
          {poolStats && (<>
            <span>总计: <strong style={{ color: 'var(--accent-lime)' }}>{poolStats.total_active}</strong></span>
            <span>手动: <strong>{poolStats.manual_count}</strong></span>
            <span>自动: <strong>{poolStats.auto_count}</strong></span>
            <span>画像: <strong style={{ color: 'var(--accent-amber)' }}>{poolStats.with_profile}</strong> ({poolStats.profile_rate}%)</span>
          </>)}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="dark-btn dark-btn-secondary" onClick={importToday} disabled={importing}>
            {importing ? '导入中...' : '导入今日Top10'}
          </button>
          <button className="dark-btn dark-btn-secondary" onClick={() => setShowSearch(!showSearch)}>
            {showSearch ? '收起搜索' : '+ 添加股票'}
          </button>
          <button className="dark-btn dark-btn-secondary" onClick={() => { loadPool(poolPage); loadStats() }}>
            刷新
          </button>
        </div>
      </div>

      {/* Backfill progress */}
      {backfillStatus?.running && (
        <div style={{
          marginBottom: 12, padding: '8px 14px',
          background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 8,
          fontSize: 12, color: 'var(--text-muted)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span>回填进行中: {backfillStatus.progress} / {backfillStatus.total} 个交易日</span>
            <span>已新增: {backfillStatus.added}</span>
          </div>
          <div style={{ width: '100%', height: 4, background: 'rgba(255,255,255,0.1)', borderRadius: 2 }}>
            <div style={{
              width: backfillStatus.total ? `${(backfillStatus.progress / backfillStatus.total * 100)}%` : '0%',
              height: '100%', background: 'var(--accent-amber)', borderRadius: 2, transition: 'width 0.3s',
            }} />
          </div>
        </div>
      )}

      {/* ==================== 画像补全进度面板 ==================== */}
      {profileStatus && (
        <div style={{
          marginBottom: 12, padding: '12px 14px',
          background: 'rgba(99,102,241,0.06)', border: '1px solid var(--border)', borderRadius: 8,
        }}>
          {/* 概览统计行 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>画像补全状态</div>
            <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-muted)' }}>
              <span>已完成: <strong style={{ color: 'var(--accent-lime)' }}>{profileStatus.completed}</strong></span>
              <span>未完成: <strong style={{ color: '#f59e0b' }}>{profileStatus.incomplete}</strong></span>
              <span>平均: <strong style={{ color: 'var(--accent-amber)' }}>{profileStatus.avg_completion}%</strong></span>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                className="dark-btn dark-btn-secondary"
                style={{ fontSize: 11 }}
                disabled={triggeringCompletion || completionStatus?.running}
                onClick={() => triggerProfileCompletion(0)}
              >
                {completionStatus?.running ? '执行中...' : triggeringCompletion ? '启动中...' : '执行画像补全'}
              </button>
              <button
                className="dark-btn dark-btn-secondary"
                style={{ fontSize: 11 }}
                disabled={triggeringCompletion || completionStatus?.running}
                onClick={() => triggerProfileCompletion(50)}
              >
                补全50只
              </button>
              <button className="dark-btn dark-btn-secondary" style={{ fontSize: 11 }} onClick={() => { loadProfileStatus(); loadCompletionStatus() }}>
                刷新
              </button>
            </div>
          </div>

          {/* 总体进度条 */}
          <div style={{ marginBottom: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>
              <span>总进度: {profileStatus.completed} / {profileStatus.total_active}</span>
              <span>{profileStatus.total_active > 0 ? (profileStatus.completed / profileStatus.total_active * 100).toFixed(1) : 0}%</span>
            </div>
            <div style={{ width: '100%', height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{
                width: profileStatus.total_active > 0 ? `${(profileStatus.completed / profileStatus.total_active * 100)}%` : '0%',
                height: '100%', borderRadius: 3, transition: 'width 0.5s ease',
                background: (profileStatus.completed / (profileStatus.total_active || 1) * 100) >= 80
                  ? 'var(--accent-lime)' : (profileStatus.completed / (profileStatus.total_active || 1) * 100) >= 40
                  ? 'var(--accent-amber)' : '#ef4444',
              }} />
            </div>
          </div>

          {/* 补全任务实时进度 */}
          {completionStatus?.running && (
            <div style={{
              marginTop: 8, padding: '8px 10px',
              background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)', borderRadius: 6,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                <span>补全进行中: <strong style={{ color: 'var(--text)' }}>{completionStatus.processed}</strong> / {completionStatus.total}</span>
                <span>成功: <strong style={{ color: 'var(--accent-lime)' }}>{completionStatus.successful}</strong> 失败: <strong style={{ color: '#ef4444' }}>{completionStatus.failed}</strong></span>
              </div>
              {completionStatus.current_symbol && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                  当前处理: <strong style={{ color: 'var(--text)' }}>{completionStatus.current_symbol}</strong>
                </div>
              )}
              <div style={{ width: '100%', height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2 }}>
                <div style={{
                  width: completionStatus.total > 0 ? `${(completionStatus.processed / completionStatus.total * 100)}%` : '0%',
                  height: '100%', background: '#f59e0b', borderRadius: 2, transition: 'width 0.3s',
                }} />
              </div>
              {completionStatus.started_at && (
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 3 }}>
                  开始于: {new Date(completionStatus.started_at).toLocaleString('zh-CN')}
                </div>
              )}
            </div>
          )}

          {/* 上次完成信息 */}
          {completionStatus && !completionStatus.running && completionStatus.finished_at && (
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
              上次执行: {new Date(completionStatus.finished_at).toLocaleString('zh-CN')}
              {' · '}成功 {completionStatus.successful} / 失败 {completionStatus.failed} / 共 {completionStatus.total}
              {completionStatus.error && <span style={{ color: '#ef4444' }}>{' · '}错误: {completionStatus.error}</span>}
            </div>
          )}
        </div>
      )}

      {/* Search panel */}
      {showSearch && (
        <div style={{
          marginBottom: 12, padding: 14,
          background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: 8,
        }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: searchResults.length ? 10 : 0 }}>
            <input
              value={searchQuery}
              onChange={e => handleSearchInput(e.target.value)}
              placeholder="输入股票代码或名称搜索..."
              className="app-search"
              style={{ flex: 1 }}
              autoFocus
            />
            {searching && <span style={{ fontSize: 12, color: 'var(--text-muted)', alignSelf: 'center' }}>搜索中...</span>}
          </div>
          {searchResults.length > 0 && (
            <div style={{ maxHeight: 260, overflowY: 'auto' }}>
              {searchResults.map(r => (
                <div key={r.symbol} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '6px 8px', borderBottom: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <div>
                    <span style={{ fontWeight: 500, color: 'var(--text)' }}>{r.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>{r.symbol}</span>
                  </div>
                  {r.in_pool ? (
                    <span style={{ fontSize: 11, color: 'var(--accent-lime)' }}>已在池中</span>
                  ) : (
                    <button
                      className="dark-btn dark-btn-secondary"
                      style={{ fontSize: 11, padding: '2px 10px' }}
                      disabled={addingSymbol === r.symbol}
                      onClick={() => addStock(r.symbol, r.name)}
                    >
                      {addingSymbol === r.symbol ? '添加中...' : '+ 入池'}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {searchQuery && !searching && searchResults.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>未找到匹配的股票</div>
          )}
          {addError && (
            <div style={{ fontSize: 12, color: '#ef4444', padding: '6px 0', marginTop: 4 }}>
              {addError}
              <span style={{ cursor: 'pointer', marginLeft: 8, opacity: 0.7 }} onClick={() => setAddError(null)}>✕</span>
            </div>
          )}
        </div>
      )}

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          value={poolKeywordInput}
          onChange={e => {
            setPoolKeywordInput(e.target.value)
            if (poolKeywordTimerRef.current) clearTimeout(poolKeywordTimerRef.current)
            poolKeywordTimerRef.current = setTimeout(() => {
              setPoolKeyword(e.target.value.trim())
              setPoolPage(1)
            }, 300)
          }}
          placeholder="代码/名称快速检索"
          className="app-search"
          style={{ width: 140 }}
        />
        <select value={sourceFilter} onChange={e => { setSourceFilter(e.target.value); setPoolPage(1) }} className="app-search" style={{ width: 'auto' }}>
          <option value="all">全部来源</option>
          <option value="manual">手动添加</option>
          <option value="top_movers">涨跌榜</option>
          <option value="backfill">历史回填</option>
          <option value="bulk_import">批量导入</option>
        </select>
        <select value={profileFilterVal} onChange={e => { setProfileFilterVal(e.target.value); setPoolPage(1) }} className="app-search" style={{ width: 'auto' }}>
          <option value="all">全部画像状态</option>
          <option value="completed">已完成画像</option>
          <option value="incomplete">未完成画像</option>
        </select>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          共 {poolTotal} 条
        </span>
        {!backfillStatus?.running && (
          <HelpTooltip {...helpTips.backfillHistory}>
            <button className="dark-btn dark-btn-secondary" style={{ fontSize: 11 }} onClick={triggerBackfill}>
              回填历史
            </button>
          </HelpTooltip>
        )}
      </div>

      {/* Pool table */}
      <div className="card-panel" style={{ overflow: 'hidden' }}>
        <table className="dark-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: 8 }}>名称</th>
              <th style={{ textAlign: 'center', padding: 8 }}>来源</th>
              <th style={{ textAlign: 'center', padding: 8 }}>行业</th>
              <th style={{ textAlign: 'center', padding: 8 }}>首次入池</th>
              <th style={{ textAlign: 'center', padding: 8 }}>最近活跃</th>
              <th style={{ textAlign: 'center', padding: 8 }}>在池天数</th>
              <th style={{ textAlign: 'center', padding: 8 }}>画像</th>
              <th style={{ textAlign: 'right', padding: 8 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {poolMembers.length === 0 ? (
              <tr><td colSpan={8} style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>暂无数据</td></tr>
            ) : poolMembers.map(m => (
              <tr key={m.symbol}>
                <td style={{ padding: 8 }}>
                  {m.company_name
                    ? <><span style={{ fontWeight: 500, color: 'var(--text)' }}>{m.company_name}</span> <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({m.symbol})</span></>
                    : <span style={{ color: 'var(--text-muted)' }}>{m.symbol}</span>
                  }
                </td>
                <td style={{ padding: 8, textAlign: 'center' }}>{sourceBadge(m.source)}</td>
                <td style={{ padding: 8, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>{m.industry || '-'}</td>
                <td style={{ padding: 8, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>{m.first_seen_date || '-'}</td>
                <td style={{ padding: 8, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>{m.last_seen_date || '-'}</td>
                <td style={{ padding: 8, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>{m.days_active ?? '-'}</td>
                <td style={{ padding: 8, textAlign: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                    <div style={{ width: 48, height: 5, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{
                        width: `${m.profile_completion ?? 0}%`, height: '100%',
                        background: (m.profile_completion ?? 0) >= 50 ? 'var(--accent-lime)' : 'var(--accent-amber)',
                        transition: 'width 0.3s',
                      }} />
                    </div>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)', minWidth: 28 }}>
                      {(m.profile_completion ?? 0).toFixed(0)}%
                    </span>
                  </div>
                </td>
                <td style={{ padding: 8, textAlign: 'right' }}>
                  <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                    <button className="dark-btn dark-btn-secondary" style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => openProfileDetail(m.symbol)}>
                      画像
                    </button>
                    <button className="dark-btn dark-btn-secondary" style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => onOpen(m.symbol)}>
                      新闻
                    </button>
                    <button
                      className="dark-btn dark-btn-secondary"
                      style={{ fontSize: 11, padding: '2px 8px', color: 'var(--accent-red, #ef4444)' }}
                      onClick={() => removeStock(m.symbol)}
                    >
                      移除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end', gap: 8, alignItems: 'center' }}>
          <button className="dark-btn dark-btn-secondary" disabled={poolPage <= 1} onClick={() => setPoolPage(p => p - 1)} style={{ opacity: poolPage > 1 ? 1 : 0.4 }}>上一页</button>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{poolPage} / {totalPages}</span>
          <button className="dark-btn dark-btn-secondary" disabled={poolPage >= totalPages} onClick={() => setPoolPage(p => p + 1)} style={{ opacity: poolPage < totalPages ? 1 : 0.4 }}>下一页</button>
        </div>
      )}

      {/* ==================== 画像详情弹窗 ==================== */}
      {detailSymbol && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setDetailSymbol(null)}>
          <div style={{
            width: '90%', maxWidth: 720, maxHeight: '85vh', overflowY: 'auto',
            background: 'var(--bg-card, #1e1e2e)', border: '1px solid var(--border)',
            borderRadius: 12, padding: 24,
          }} onClick={e => e.stopPropagation()}>
            {detailLoading ? (
              <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>加载中...</div>
            ) : detailData?._empty ? (
              <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
                <p>暂无 {detailSymbol} 的画像数据</p>
                <button className="dark-btn dark-btn-secondary" onClick={triggerRebuild} disabled={rebuildLoading}>
                  {rebuildLoading ? '执行中...' : '立即生成画像'}
                </button>
              </div>
            ) : detailData ? (
              <>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <div>
                    <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>{detailData.company_name || detailSymbol}</span>
                    <span style={{ fontSize: 13, color: 'var(--text-muted)', marginLeft: 10 }}>{detailData.symbol}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      完成度: <strong style={{ color: (detailData.profile_completion ?? 0) >= 50 ? 'var(--accent-lime)' : '#f59e0b' }}>
                        {(detailData.profile_completion ?? 0).toFixed(0)}%
                      </strong>
                    </span>
                    <button className="dark-btn dark-btn-secondary" style={{ fontSize: 12 }} onClick={() => setDetailSymbol(null)}>关闭</button>
                  </div>
                </div>

                {/* Profile fields */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 20px', marginBottom: 20 }}>
                  {([
                    ['行业', detailData.industry],
                    ['细分行业', detailData.sub_industry],
                    ['核心产品', detailData.core_products],
                    ['竞争对手', detailData.competitors],
                    ['战略关键词', detailData.strategic_keywords],
                    ['风险因素', detailData.risk_factors],
                  ] as [string, string | null][]).map(([label, value]) => (
                    <div key={label}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
                      <div style={{ fontSize: 13, color: value ? 'var(--text)' : 'rgba(255,255,255,0.2)' }}>{value || '—'}</div>
                    </div>
                  ))}
                </div>

                {/* Full-width fields */}
                {([
                  ['业务概述', detailData.business_summary],
                  ['市场地位', detailData.competitive_position],
                  ['历史亮点', detailData.history_highlights],
                ] as [string, string | null][]).map(([label, value]) => (
                  <div key={label} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
                    <div style={{
                      fontSize: 13, color: value ? 'var(--text)' : 'rgba(255,255,255,0.2)',
                      lineHeight: 1.6, padding: '6px 10px',
                      background: 'rgba(255,255,255,0.03)', borderRadius: 6,
                    }}>
                      {value || '—'}
                    </div>
                  </div>
                ))}

                {detailData.last_refreshed && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 16 }}>
                    最后更新: {new Date(detailData.last_refreshed).toLocaleString('zh-CN')}
                  </div>
                )}

                {/* Rebuild section */}
                <div style={{
                  marginTop: 8, padding: 14,
                  background: 'rgba(99,102,241,0.06)', border: '1px solid var(--border)', borderRadius: 8,
                }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>
                    重构画像
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                    输入补充信息（可选），系统将结合现有画像和网络搜索结果，通过 LLM 重新生成企业画像。
                  </div>
                  <textarea
                    value={supplementaryInfo}
                    onChange={e => setSupplementaryInfo(e.target.value)}
                    placeholder="输入关于该公司的补充信息，例如：最新发布的产品、业务调整、战略合作等。留空则仅基于网络数据重新生成。"
                    style={{
                      width: '100%', minHeight: 80, padding: 10, fontSize: 13,
                      background: 'rgba(0,0,0,0.2)', color: 'var(--text)',
                      border: '1px solid var(--border)', borderRadius: 6,
                      resize: 'vertical', fontFamily: 'inherit',
                    }}
                  />
                  <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
                    <button
                      className="dark-btn dark-btn-secondary"
                      disabled={rebuildLoading}
                      onClick={triggerRebuild}
                      style={{ fontWeight: 600 }}
                    >
                      {rebuildLoading ? '执行中...' : '执行画像重构'}
                    </button>
                    {rebuildMsg && (
                      <span style={{
                        fontSize: 12,
                        color: rebuildMsg.startsWith('失败') || rebuildMsg.startsWith('网络') ? '#ef4444' : 'var(--accent-lime)',
                      }}>
                        {rebuildMsg}
                      </span>
                    )}
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main page                                                          */
/* ------------------------------------------------------------------ */

export default function StocksNewsIndex({ onOpen }: { onOpen: (symbol: string) => void }) {
  const [items, setItems] = React.useState<StockItem[]>([])
  const [loading, setLoading] = React.useState(false)
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(20)
  const [total, setTotal] = React.useState(0)
  const [q, setQ] = React.useState('')
  const [progress, setProgress] = React.useState<ProgressData | null>(null)
  const [taskProgress, setTaskProgress] = React.useState<any>(null)
  const [autoRefresh, setAutoRefresh] = React.useState(true)
  const [refreshInterval, setRefreshInterval] = React.useState(30)
  const [showInvalid, setShowInvalid] = React.useState(false)
  const [market, setMarket] = React.useState('A股')

  // Tab state: 'pool' = stock pool manager, 'profiles' = existing profile list
  const [activeTab, setActiveTab] = React.useState<'pool' | 'profiles'>('pool')

  const [isLoadingData, setIsLoadingData] = React.useState(false)
  const [isLoadingProgress, setIsLoadingProgress] = React.useState(false)
  const lastLoadTimeRef = React.useRef(0)
  const lastProgressTimeRef = React.useRef(0)
  const allItemsCacheRef = React.useRef<any[]>([])
  const loadingPagesRef = React.useRef(new Set<number>())
  const searchDebounceTimerRef = React.useRef<ReturnType<typeof setTimeout> | undefined>()

  const performFrontendSearch = React.useCallback((searchQuery: string) => {
    if (!searchQuery.trim()) {
      const allItems = allItemsCacheRef.current.map((stock: any) => ({
        symbol: stock.symbol, name: stock.name,
        completion_percentage: stock.completion_percentage, fields_filled: stock.fields_filled,
        total_fields: stock.total_fields, article_count: stock.article_count || 0
      }))
      setItems(allItems)
      setPage(1)
      return
    }
    const searchLower = searchQuery.toLowerCase()
    const filtered = allItemsCacheRef.current.filter((stock: any) => {
      const looksLikeCode = /^[0-9.]+$/.test(searchLower)
      if (looksLikeCode) {
        return stock.symbol.toLowerCase() === searchLower || stock.symbol.toLowerCase().startsWith(searchLower)
      }
      return stock.name?.toLowerCase().includes(searchLower)
    })
    setItems(filtered.map((stock: any) => ({
      symbol: stock.symbol, name: stock.name,
      completion_percentage: stock.completion_percentage, fields_filled: stock.fields_filled,
      total_fields: stock.total_fields, article_count: stock.article_count || 0
    })))
    setPage(1)
  }, [total])

  const handleSearchChange = React.useCallback((newSearchQuery: string) => {
    setQ(newSearchQuery)
    if (searchDebounceTimerRef.current) clearTimeout(searchDebounceTimerRef.current)
    searchDebounceTimerRef.current = setTimeout(() => {
      performFrontendSearch(newSearchQuery)
    }, 500)
  }, [performFrontendSearch])

  const handleSearchBlur = React.useCallback(() => {
    if (searchDebounceTimerRef.current) clearTimeout(searchDebounceTimerRef.current)
    performFrontendSearch(q)
  }, [q, performFrontendSearch])

  const load = React.useCallback(async (isInitialLoad = true) => {
    const now = Date.now()
    if (now - lastLoadTimeRef.current < 5000) return
    if (isLoadingData) return
    setIsLoadingData(true)
    lastLoadTimeRef.current = now
    try {
      const firstPageUrl = buildApiUrl(`/api/news/stocks/progress?page=1&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`)
      const firstPageRes = await fetch(firstPageUrl, { cache: 'no-store' })
      if (!firstPageRes.ok) throw new Error(await firstPageRes.text())
      const firstPageData = await firstPageRes.json()
      const firstPageItems = firstPageData.stocks_detail || []
      if (isInitialLoad) {
        allItemsCacheRef.current = [...firstPageItems]
        loadingPagesRef.current.clear()
      } else {
        const firstPageSize = Math.min(100, allItemsCacheRef.current.length)
        allItemsCacheRef.current.splice(0, firstPageSize, ...firstPageItems)
      }
      setItems(allItemsCacheRef.current.map((stock: any) => ({
        symbol: stock.symbol, name: stock.name,
        completion_percentage: stock.completion_percentage, fields_filled: stock.fields_filled,
        total_fields: stock.total_fields, article_count: stock.article_count || 0
      })))
      setTotal(firstPageData.total_stocks || 0)
      setPage(1)
      setProgress({ ...firstPageData, stocks_detail: firstPageItems })
    } catch (e: any) {
      console.error('加载数据失败:', e)
    } finally {
      setIsLoadingData(false)
    }
  }, [showInvalid, market])

  const loadPageOnDemand = React.useCallback(async (targetPage: number) => {
    const pageStartIdx = (targetPage - 1) * 100
    const pageEndIdx = targetPage * 100
    if (allItemsCacheRef.current.length >= pageEndIdx) return
    if (loadingPagesRef.current.has(targetPage)) return
    loadingPagesRef.current.add(targetPage)
    try {
      const pageUrl = buildApiUrl(`/api/news/stocks/progress?page=${targetPage}&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`)
      const pageRes = await fetch(pageUrl, { cache: 'no-store' })
      if (!pageRes.ok) throw new Error(await pageRes.text())
      const pageData = await pageRes.json()
      allItemsCacheRef.current.push(...(pageData.stocks_detail || []))
    } catch (e: any) {
      console.error(`加载第 ${targetPage} 页失败:`, e)
    } finally {
      loadingPagesRef.current.delete(targetPage)
    }
  }, [showInvalid, market])

  const loadTaskProgress = React.useCallback(async () => {
    const now = Date.now()
    if (now - lastProgressTimeRef.current < 10000) return
    if (isLoadingProgress) return
    setIsLoadingProgress(true)
    lastProgressTimeRef.current = now
    try {
      const response = await fetch(buildApiUrl('/api/profile/update-progress'), { cache: 'no-store' })
      if (!response.ok) throw new Error(await response.text())
      setTaskProgress(await response.json())
    } catch (e: any) {
      console.error('加载任务进度失败:', e)
    } finally {
      setIsLoadingProgress(false)
    }
  }, [])

  React.useEffect(() => {
    if (activeTab === 'profiles') load(true)
  }, [activeTab])

  React.useEffect(() => {
    if (activeTab !== 'profiles') return
    allItemsCacheRef.current = []
    loadingPagesRef.current.clear()
    lastLoadTimeRef.current = 0
    load(true)
  }, [market])

  React.useEffect(() => {
    if (!autoRefresh || activeTab !== 'profiles') return
    const progressTimer = setInterval(loadTaskProgress, 60000)
    const fullDataTimer = setInterval(() => load(false), Math.max(refreshInterval * 1000, 30000))
    return () => { clearInterval(progressTimer); clearInterval(fullDataTimer) }
  }, [autoRefresh, refreshInterval, loadTaskProgress, activeTab])

  const formatTime = (isoString: string | null | undefined) => {
    if (!isoString) return '-'
    try {
      return new Date(isoString).toLocaleString('zh-CN', {
        year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
      })
    } catch { return '-' }
  }

  return (
    <div>
      <div className="page-container">

        {/* Tab switcher */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
          {([
            { key: 'pool', label: '股票池管理' },
            { key: 'profiles', label: '画像与新闻' },
          ] as const).map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: '8px 20px', fontSize: 13, fontWeight: activeTab === tab.key ? 600 : 400,
                color: activeTab === tab.key ? 'var(--accent-lime)' : 'var(--text-muted)',
                background: 'transparent', border: 'none', cursor: 'pointer',
                borderBottom: activeTab === tab.key ? '2px solid var(--accent-lime)' : '2px solid transparent',
                transition: 'all 0.2s',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab: Stock Pool Manager */}
        {activeTab === 'pool' && <StockPoolManager onOpen={onOpen} />}

        {/* Tab: Profiles & News (existing content) */}
        {activeTab === 'profiles' && (<>
          {/* Task progress */}
          {taskProgress && taskProgress.is_running && (
            <div className="card-panel task-progress">
              <div className="task-progress-head">
                <div className="task-progress-title">Profile 更新任务进行中...</div>
                <div className="task-progress-stats">
                  <span>{taskProgress.processed} / {taskProgress.total_stocks}</span>
                  <span>{taskProgress.successful} / {taskProgress.failed}</span>
                  <span>{taskProgress.elapsed_time_seconds}s</span>
                  <span>{taskProgress.speed_stocks_per_minute.toFixed(1)}/分钟</span>
                </div>
              </div>
              <div className="task-progress-current">当前处理: {taskProgress.current_stock_name} ({taskProgress.current_stock})</div>
              <div className="progress-bar-outer">
                <div className="progress-bar-inner" style={{ width: `${taskProgress.progress_percentage}%` }} />
              </div>
              <div className="task-progress-footer">进度: {taskProgress.progress_percentage.toFixed(1)}% · 预计剩余: {Math.floor(taskProgress.estimated_remaining_seconds / 60)}分{taskProgress.estimated_remaining_seconds % 60}秒</div>
            </div>
          )}

          {/* Profile progress */}
          {progress && (
            <div style={{ marginBottom: 16, padding: 12, background: 'rgba(99,102,241,0.1)', border: '1px solid var(--border)', borderRadius: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Profile 数据填充进度</div>
                <div style={{ fontSize: 12, color: 'var(--text)', display: 'flex', gap: 20 }}>
                  <span>已完成: <strong style={{ color: 'var(--accent-lime)' }}>{progress.completed_profiles}</strong> / {progress.total_stocks}</span>
                  <span>完成度: <strong style={{ color: 'var(--accent-amber)' }}>{progress.progress_percentage.toFixed(2)}%</strong></span>
                  <span>平均: <strong>{progress.average_completion.toFixed(1)}%</strong></span>
                </div>
              </div>
              <div style={{ width: '100%', height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 3, overflow: 'hidden', marginTop: 8 }}>
                <div style={{
                  width: `${progress.progress_percentage}%`,
                  background: progress.progress_percentage >= 50 ? 'var(--accent-lime)' : 'var(--accent-amber)',
                  height: '100%', transition: 'width 0.3s ease'
                }} />
              </div>
            </div>
          )}

          {/* Filters */}
          <div className="page-actions" style={{ marginBottom: 12 }}>
            <input value={q} onChange={e => handleSearchChange(e.target.value)} onBlur={handleSearchBlur} placeholder='按代码或名称筛选' className="app-search" />
            <select value={market} onChange={(e) => setMarket(e.target.value)} className="app-search">
              <option value="A股">A股</option>
              <option value="港股">港股</option>
              <option value="美股">美股</option>
              <option value="全部">全部市场</option>
            </select>
            <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer', marginLeft: 'auto', borderLeft: '1px solid var(--border)', paddingLeft: 8 }}>
              <input type='checkbox' checked={showInvalid} onChange={(e) => setShowInvalid(e.target.checked)} style={{ cursor: 'pointer' }} />
              显示已作废数据
            </label>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}>
                <input type='checkbox' checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} style={{ cursor: 'pointer' }} />
                自动刷新
              </label>
              {autoRefresh && (
                <select value={refreshInterval} onChange={(e) => setRefreshInterval(Number(e.target.value))} className="app-search">
                  <option value={3}>3 秒</option>
                  <option value={5}>5 秒</option>
                  <option value={10}>10 秒</option>
                  <option value={15}>15 秒</option>
                  <option value={30}>30 秒</option>
                </select>
              )}
              <HelpTooltip {...helpTips.refreshData}>
                <button onClick={() => { load(false); loadTaskProgress() }} className="dark-btn dark-btn-secondary">刷新</button>
              </HelpTooltip>
            </div>
          </div>

          {/* Data table */}
          <div className="card-panel" style={{ overflow: 'hidden' }}>
            <table className="dark-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '8px' }}>名称</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>开始统计</th>
                  <th style={{ textAlign: 'right', padding: '8px' }}>文章数</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>Profile 完成度</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>更新状态</th>
                  <th style={{ textAlign: 'center', padding: '8px' }}>最后更新</th>
                  <th style={{ textAlign: 'right', padding: '8px' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const startIdx = (page - 1) * pageSize
                  const paginatedItems = items.slice(startIdx, startIdx + pageSize)
                  if (loading && items.length === 0)
                    return <tr><td colSpan={7} style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)' }}>加载中...</td></tr>
                  if (!loading && items.length === 0)
                    return <tr><td colSpan={7} style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)' }}>没有数据</td></tr>
                  return paginatedItems.map(it => {
                    const isCompleted = (it.completion_percentage ?? 0) >= 50
                    return (
                      <tr key={it.symbol}>
                        <td style={{ padding: '8px' }}>
                          {it.name && it.name !== '-' && it.name !== it.symbol
                            ? <><span style={{ fontWeight: 500, color: 'var(--text)' }}>{it.name}</span> <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({it.symbol})</span></>
                            : <span style={{ color: 'var(--text-muted)' }}>{it.symbol}</span>}
                        </td>
                        <td style={{ padding: '8px' }}>{it.start_date || '-'}</td>
                        <td style={{ padding: '8px', textAlign: 'right' }}>{it.article_count}</td>
                        <td style={{ padding: '8px', textAlign: 'center' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                            <div style={{ width: 60, height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 2, overflow: 'hidden' }}>
                              <div style={{ width: `${it.completion_percentage ?? 0}%`, height: '100%', background: isCompleted ? 'var(--accent-lime)' : 'var(--accent-amber)', transition: 'width 0.3s ease' }} />
                            </div>
                            <span style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 30 }}>{(it.completion_percentage ?? 0).toFixed(0)}%</span>
                          </div>
                        </td>
                        <td style={{ padding: '8px', textAlign: 'center' }}>
                          <div style={{
                            width: 12, height: 12, borderRadius: '50%',
                            backgroundColor: isCompleted ? 'var(--accent-lime)' : 'rgba(255,255,255,0.2)',
                            margin: '0 auto',
                            boxShadow: isCompleted ? '0 0 6px rgba(110, 231, 183, 0.5)' : 'none',
                          }} title={isCompleted ? '已完成' : '待更新'} />
                        </td>
                        <td style={{ padding: '8px', textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>{formatTime(it.last_updated_at)}</td>
                        <td style={{ padding: '8px', textAlign: 'right' }}>
                          <button onClick={() => onOpen(it.symbol)} className="dark-btn dark-btn-secondary">查看</button>
                        </td>
                      </tr>
                    )
                  })
                })()}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>共 {total} 条，已加载 {allItemsCacheRef.current.length} 条</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button disabled={page <= 1} onClick={() => { setPage(Math.max(1, page - 1)); loadPageOnDemand(Math.max(1, page - 1)) }} className="dark-btn dark-btn-secondary" style={{ opacity: page > 1 ? 1 : 0.5 }}>上一页</button>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>第 {page} 页</span>
              <button disabled={(page * pageSize) >= total} onClick={() => { setPage(page + 1); loadPageOnDemand(page + 1) }} className="dark-btn dark-btn-secondary" style={{ opacity: (page * pageSize) < total ? 1 : 0.5 }}>下一页</button>
            </div>
          </div>
        </>)}
      </div>
    </div>
  )
}
