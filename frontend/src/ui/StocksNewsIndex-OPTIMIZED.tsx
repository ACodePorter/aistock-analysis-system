import React from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'

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

export default function StocksNewsIndex({ onOpen }: { onOpen: (symbol: string)=>void }){
  const [items, setItems] = React.useState<StockItem[]>([])
  const [loading, setLoading] = React.useState(false)
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(20)
  const [total, setTotal] = React.useState(0)
  const [q, setQ] = React.useState('')
  const [progress, setProgress] = React.useState<ProgressData | null>(null)
  const [taskProgress, setTaskProgress] = React.useState<any>(null)
  const [autoRefresh, setAutoRefresh] = React.useState(true)
  const [refreshInterval, setRefreshInterval] = React.useState(30)  // 改为 30 秒
  const [showInvalid, setShowInvalid] = React.useState(false)  // 是否显示无效的 Profiles
  const [market, setMarket] = React.useState('A股')  // 股票市场过滤，默认 A股

  // 防抖：避免同时发多个请求
  const [isLoadingData, setIsLoadingData] = React.useState(false)
  const [isLoadingProgress, setIsLoadingProgress] = React.useState(false)
  const lastLoadTimeRef = React.useRef(0)
  const lastProgressTimeRef = React.useRef(0)
  const allItemsCacheRef = React.useRef<any[]>([])  // 缓存所有已加载的数据
  const loadingPagesRef = React.useRef(new Set<number>())  // 记录正在加载的页面
  const searchDebounceTimerRef = React.useRef<ReturnType<typeof setTimeout> | undefined>()  // 搜索防抖计时器
  
  // ✨ NEW: 缓存键跟踪 - 用于识别是否是同一个市场+条件组合
  const cacheKeyRef = React.useRef('')
  const buildCacheKey = () => `${market}_${showInvalid}`

  // 前端搜索：在缓存的所有数据中搜索
  const performFrontendSearch = React.useCallback((searchQuery: string) => {
    console.log('🔍 performFrontendSearch called with:', searchQuery)
    console.log('   Cache size:', allItemsCacheRef.current.length)
    console.log('   First 3 items in cache:', allItemsCacheRef.current.slice(0, 3).map(s => ({symbol: s.symbol, name: s.name})))
    
    if (!searchQuery.trim()) {
      // 如果搜索框为空，显示所有缓存数据
      const allItems = allItemsCacheRef.current.map((stock: any) => ({
        symbol: stock.symbol,
        name: stock.name,
        completion_percentage: stock.completion_percentage,
        fields_filled: stock.fields_filled,
        total_fields: stock.total_fields,
        article_count: stock.article_count || 0
      }))
      console.log('   Empty search - showing all', allItems.length, 'items')
      setItems(allItems)
      setPage(1)
      return
    }

    // 在缓存中搜索
    const searchLower = searchQuery.toLowerCase()
    console.log('   Search term (lowercase):', searchLower)
    
    const filtered = allItemsCacheRef.current.filter((stock: any) => {
      // 如果搜索词看起来像是股票代码（全数字或包含点号），只匹配代码
      const looksLikeCode = /^[0-9.]+$/.test(searchLower)
      
      if (looksLikeCode) {
        // 代码搜索：精确匹配或以搜索词开头
        const matches = stock.symbol.toLowerCase() === searchLower || stock.symbol.toLowerCase().startsWith(searchLower)
        if (matches) console.log('     ✓ CODE MATCH:', stock.symbol, stock.name)
        return matches
      } else {
        // 名称搜索：包含搜索词
        const matches = stock.name?.toLowerCase().includes(searchLower)
        if (matches) console.log('     ✓ NAME MATCH:', stock.symbol, stock.name)
        return matches
      }
    })

    console.log('   Filtered results count:', filtered.length)
    console.log('   Filtered results:', filtered.map(s => ({symbol: s.symbol, name: s.name})))

    const displayItems = filtered.map((stock: any) => ({
      symbol: stock.symbol,
      name: stock.name,
      completion_percentage: stock.completion_percentage,
      fields_filled: stock.fields_filled,
      total_fields: stock.total_fields,
      article_count: stock.article_count || 0
    }))
    
    setItems(displayItems)
    setPage(1)
    
    // 如果搜索结果为空且缓存不完整（未加载所有页面），提示用户
    if (filtered.length === 0 && allItemsCacheRef.current.length < (total || 0)) {
      console.log(`搜索"${searchQuery}"未在已加载的 ${allItemsCacheRef.current.length} 条数据中找到结果。总共 ${total} 条数据，页面加载中...`)
    }
  }, [total])

  // 处理搜索框输入变化（带防抖）
  const handleSearchChange = React.useCallback((newSearchQuery: string) => {
    setQ(newSearchQuery)
    
    // 清除之前的防抖计时器
    if (searchDebounceTimerRef.current) {
      clearTimeout(searchDebounceTimerRef.current)
    }

    // 设置新的防抖计时器（500ms 后执行前端搜索）
    searchDebounceTimerRef.current = setTimeout(() => {
      performFrontendSearch(newSearchQuery)
    }, 500)
  }, [performFrontendSearch])

  // 处理搜索框失焦
  const handleSearchBlur = React.useCallback(() => {
    // 立即执行搜索（不等防抖）
    if (searchDebounceTimerRef.current) {
      clearTimeout(searchDebounceTimerRef.current)
    }
    performFrontendSearch(q)
  }, [q, performFrontendSearch])

  // ✨ OPTIMIZED: 改为只加载第一页，不进行后台预加载
  const load = React.useCallback(async (isInitialLoad = true)=>{
    const now = Date.now()
    // 防抖：距上次请求少于 5 秒则不再请求
    if (now - lastLoadTimeRef.current < 5000) {
      console.log('⏱️  [防抖] 距离上次请求不到 5 秒，跳过此次加载')
      return
    }
    
    if (isLoadingData) {
      console.log('⏳ [加载中] 有正在进行的加载操作，跳过此次加载')
      return
    }

    const cacheKey = buildCacheKey()
    
    // ✨ NEW: 检查缓存是否命中 - 同市场+同条件，直接返回（跳过 API 请求）
    if (cacheKey === cacheKeyRef.current && allItemsCacheRef.current.length > 0) {
      console.log('📦 [缓存命中] 使用已加载的数据，跳过 API 请求')
      console.log(`   缓存键: ${cacheKey}`)
      console.log(`   缓存大小: ${allItemsCacheRef.current.length} 条数据`)
      
      // 应用搜索过滤显示
      let displayItems = allItemsCacheRef.current.map((stock: any) => ({
        symbol: stock.symbol,
        name: stock.name,
        completion_percentage: stock.completion_percentage,
        fields_filled: stock.fields_filled,
        total_fields: stock.total_fields,
        article_count: stock.article_count || 0
      }))
      
      if (q.trim()) {
        const searchLower = q.toLowerCase()
        const looksLikeCode = /^[0-9.]+$/.test(searchLower)
        
        if (looksLikeCode) {
          displayItems = displayItems.filter(item => 
            item.symbol.toLowerCase() === searchLower || 
            item.symbol.toLowerCase().startsWith(searchLower)
          )
        } else {
          displayItems = displayItems.filter(item =>
            item.name?.toLowerCase().includes(searchLower)
          )
        }
      }
      
      setItems(displayItems)
      return  // ✨ 缓存命中，直接返回，不发起 API 请求
    }
    
    // 缓存未命中，重新加载
    setIsLoadingData(true)
    lastLoadTimeRef.current = now
    
    try{
      console.log(`📥 [加载数据] 市场=${market}, 显示无效=${showInvalid}`)
      console.log(`   缓存键变更: ${cacheKeyRef.current} → ${cacheKey}`)
      
      // ✨ 更新缓存键和清空缓存
      cacheKeyRef.current = cacheKey
      allItemsCacheRef.current = []
      loadingPagesRef.current.clear()
      
      // 只加载第一页数据（不再预加载所有页面）
      const firstPageUrl = buildApiUrl(`/api/news/stocks/progress?page=1&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`)
      console.log(`   请求 URL: ${firstPageUrl}`)
      
      const firstPageRes = await fetch(firstPageUrl, { cache: 'no-store' })
      
      if(!firstPageRes.ok) throw new Error(await firstPageRes.text())
      
      const firstPageData = await firstPageRes.json()
      const firstPageItems = firstPageData.stocks_detail || []
      
      console.log('✅ [首页加载成功]')
      console.log(`   市场: ${market}`)
      console.log(`   总股票数: ${firstPageData.total_stocks}`)
      console.log(`   首页数据: ${firstPageItems.length} 条`)
      console.log(`   前 3 条数据:`, firstPageItems.slice(0, 3).map((s: any) => ({symbol: s.symbol, name: s.name})))
      
      // 缓存第一页数据
      allItemsCacheRef.current = [...firstPageItems]
      
      // 立即显示数据（应用搜索过滤）
      let displayItems = allItemsCacheRef.current.map((stock: any) => ({
        symbol: stock.symbol,
        name: stock.name,
        completion_percentage: stock.completion_percentage,
        fields_filled: stock.fields_filled,
        total_fields: stock.total_fields,
        article_count: stock.article_count || 0
      }))
      
      // 如果有搜索词，在前端进行过滤
      if (q.trim()) {
        const searchLower = q.toLowerCase()
        const looksLikeCode = /^[0-9.]+$/.test(searchLower)
        
        if (looksLikeCode) {
          displayItems = displayItems.filter(item => 
            item.symbol.toLowerCase() === searchLower || item.symbol.toLowerCase().startsWith(searchLower)
          )
        } else {
          displayItems = displayItems.filter(item =>
            item.name?.toLowerCase().includes(searchLower)
          )
        }
      }
      
      setItems(displayItems)
      setTotal(firstPageData.total_stocks || 0)
      
      setProgress({
        ...firstPageData,
        stocks_detail: firstPageItems
      })
      
      // ✨ REMOVED: 不再启动后台预加载 loadRemainingPages()
      // 原来这里会导致 30+ 个额外的 HTTP 请求
      // 现在改为用户翻页时才按需加载
      
    }catch(e:any){
      console.error('❌ 加载数据失败:', e)
    }finally{
      setIsLoadingData(false)
    }
  },[showInvalid, q, market])

  // ✨ NEW: 翻页时按需加载指定页面（不再预加载所有页面）
  const loadPageOnDemand = React.useCallback(async (targetPage: number) => {
    try {
      // 计算该页的数据范围
      const pageStartIdx = (targetPage - 1) * 100
      const pageEndIdx = targetPage * 100
      
      // 检查该页是否已缓存
      const pageIsCached = allItemsCacheRef.current.length >= pageEndIdx
      
      if (pageIsCached) {
        console.log(`📦 [页面缓存命中] 第 ${targetPage} 页已在缓存中，无需重新加载`)
        // 直接从缓存显示
        const displayItems = allItemsCacheRef.current.slice(pageStartIdx, pageEndIdx)
        setItems(displayItems)
        setPage(targetPage)
        return
      }
      
      // 页面未缓存，发起请求
      console.log(`📥 [按需加载] 加载第 ${targetPage} 页`)
      
      if (loadingPagesRef.current.has(targetPage)) {
        console.log(`   ⏳ 第 ${targetPage} 页正在加载中，等待...`)
        // 等待该页加载完成（简单方案）
        await new Promise(resolve => setTimeout(resolve, 500))
        const displayItems = allItemsCacheRef.current.slice(pageStartIdx, pageEndIdx)
        setItems(displayItems)
        setPage(targetPage)
        return
      }
      
      loadingPagesRef.current.add(targetPage)
      
      // 加载该页数据
      const pageUrl = buildApiUrl(
        `/api/news/stocks/progress?page=${targetPage}&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`
      )
      
      const pageRes = await fetch(pageUrl, { cache: 'no-store' })
      
      if (pageRes.ok) {
        const pageData = await pageRes.json()
        const pageItems = pageData.stocks_detail || []
        
        // 追加到缓存
        allItemsCacheRef.current.push(...pageItems)
        
        console.log(`✅ [页面加载成功] 已加载至第 ${Math.ceil(allItemsCacheRef.current.length / 100)} 页`)
        
        // 显示该页数据
        const displayItems = allItemsCacheRef.current.slice(pageStartIdx, pageEndIdx)
        setItems(displayItems)
        setPage(targetPage)
      } else {
        console.error(`❌ 加载第 ${targetPage} 页失败`, pageRes.statusText)
      }
      
      loadingPagesRef.current.delete(targetPage)
      
    } catch (e: any) {
      console.error(`❌ 翻页加载失败:`, e)
      loadingPagesRef.current.delete(targetPage)
    }
  }, [market, showInvalid])

  // 加载实时任务进度（带防抖）
  const loadTaskProgress = React.useCallback(async () => {
    const now = Date.now()
    // 防抖：距上次请求少于 10 秒则不再请求
    if (now - lastProgressTimeRef.current < 10000) {
      return
    }
    
    if (isLoadingProgress) return
    setIsLoadingProgress(true)
    lastProgressTimeRef.current = now
    
    try {
      const response = await fetch(buildApiUrl('/api/profile/update-progress'), { cache: 'no-store' })
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setTaskProgress(data)
    } catch (e: any) {
      console.error('加载任务进度失败:', e)
    } finally {
      setIsLoadingProgress(false)
    }
  }, [])

  // 初始化及定时加载
  React.useEffect(()=>{
    load(true)
    loadTaskProgress()
    
    // 防抖处理页面切换（市场改变时）
    allItemsCacheRef.current = []
    loadingPagesRef.current.clear()
    cacheKeyRef.current = ''  // ✨ 重置缓存键
    
  },[market]) // 当市场改变时，重新加载

  // 自动刷新
  React.useEffect(()=>{
    if(!autoRefresh) return
    
    const timer = setInterval(()=>{
      load(false)
      loadTaskProgress()
    }, refreshInterval * 1000)
    
    return ()=>clearInterval(timer)
  },[autoRefresh, refreshInterval, load, loadTaskProgress])

  // 计算分页数据
  const paginatedItems = items.slice(0, pageSize)
  const totalPages = Math.ceil(items.length / pageSize)
  const currentPageNum = 1

  return (
    <div className="app-shell">
      <div className="page-container">
      {/* 市场选择 */}
      <div className="flex items-center gap-2 flex-wrap">
        <label className="font-semibold text-sm text-[var(--text)]">市场：</label>
        {['A股', '港股', '美股', '全部'].map(m => (
          <button
            key={m}
            onClick={() => setMarket(m)}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
              market === m
                ? 'dark-btn-primary'
                : 'dark-btn dark-btn-secondary'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* 搜索框 */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="输入股票代码或名称搜索..."
          value={q}
          onChange={(e) => handleSearchChange(e.target.value)}
          onBlur={handleSearchBlur}
          className="app-search"
        />
      </div>

      {/* 统计信息 */}
      {progress && (
        <div className="card-panel stats-panel">
          <div>📊 总股票数: <strong>{progress.total_stocks}</strong></div>
          <div>✅ 已完成: <strong>{progress.completed_profiles}</strong> ({(progress.progress_percentage || 0).toFixed(1)}%)</div>
          <div>📈 平均完成度: <strong>{(progress.average_completion || 0).toFixed(1)}%</strong></div>
          <div>💾 缓存数据: <strong>{allItemsCacheRef.current.length}</strong> 条</div>
        </div>
      )}

      {/* 自动刷新控制 */}
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
            className="w-4 h-4"
          />
          <span className="text-sm">自动刷新</span>
        </label>
        {autoRefresh && (
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(Number(e.target.value))}
            className="app-search"
          >
            <option value={10}>10 秒</option>
            <option value={20}>20 秒</option>
            <option value={30}>30 秒</option>
            <option value={60}>60 秒</option>
            <option value={120}>2 分钟</option>
          </select>
        )}
      </div>

      {/* 数据表格 */}
      {loading ? (
        <div className="text-center py-8 text-muted">加载中...</div>
      ) : items.length === 0 ? (
        <div className="text-center py-8 text-muted">暂无数据</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <div className="card-panel table-panel">
            <table className="dark-table w-full text-sm">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">代码</th>
                  <th className="px-3 py-2 text-left font-semibold">名称</th>
                  <th className="px-3 py-2 text-center font-semibold">完成度</th>
                  <th className="px-3 py-2 text-center font-semibold">新闻数</th>
                  <th className="px-3 py-2 text-center font-semibold">操作</th>
                </tr>
              </thead>
              <tbody>
                {paginatedItems.map((item, idx) => (
                  <tr key={`${item.symbol}-${idx}`}>
                    <td className="px-3 py-2 font-mono text-[var(--primary)]">{item.symbol}</td>
                    <td className="px-3 py-2">{item.name || '-'}</td>
                    <td className="px-3 py-2 text-center">
                      <div className="w-full dark-progress">
                        <div
                          className="dark-progress-bar primary"
                          style={{ width: `${item.completion_percentage || 0}%` }}
                        />
                      </div>
                      <span className="text-xs text-[var(--text-muted)]">{(item.completion_percentage || 0).toFixed(0)}%</span>
                    </td>
                    <td className="px-3 py-2 text-center">{item.article_count || 0}</td>
                    <td className="px-3 py-2 text-center">
                      <button onClick={() => onOpen(item.symbol)} className="dark-btn dark-btn-secondary">查看</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 分页控制 */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <div className="text-sm text-muted">
                共 <strong>{items.length}</strong> 条数据，第 <strong>{currentPageNum}</strong> 页，共 <strong>{totalPages}</strong> 页
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => loadPageOnDemand(Math.max(1, currentPageNum - 1))}
                  disabled={currentPageNum === 1}
                  className="soft-button"
                >
                  上一页
                </button>
                <button
                  onClick={() => loadPageOnDemand(Math.min(totalPages, currentPageNum + 1))}
                  disabled={currentPageNum === totalPages}
                  className="soft-button"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
