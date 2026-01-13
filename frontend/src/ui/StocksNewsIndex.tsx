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

  // 前端搜索：在缓存的所有数据中搜索（不触发 API 调用）
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
      console.log(`搜索"${searchQuery}"未在已加载的 ${allItemsCacheRef.current.length} 条数据中找到结果。总共 ${total} 条数据，正在加载中...`)
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

  const load = React.useCallback(async (isInitialLoad = true)=>{
    const now = Date.now()
    // 防抖：距上次请求少于 5 秒则不再请求
    if (now - lastLoadTimeRef.current < 5000) {
      return
    }
    
    if (isLoadingData) return
    setIsLoadingData(true)
    lastLoadTimeRef.current = now
    
    try{
      // ✨ 改进：只加载第一页数据，快速响应，后续页面按需加载
      const firstPageUrl = buildApiUrl(`/api/news/stocks/progress?page=1&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`)
      const firstPageRes = await fetch(firstPageUrl, { cache: 'no-store' })
      
      if(!firstPageRes.ok) throw new Error(await firstPageRes.text())
      
      const firstPageData = await firstPageRes.json()
      const firstPageItems = firstPageData.stocks_detail || []
      
      console.log('📦 First page data loaded from API (on-demand loading enabled)')
      console.log('   Market:', market)
      console.log('   Total stocks:', firstPageData.total_stocks)
      console.log('   First page items:', firstPageItems.length)
      console.log('   First 3 items:', firstPageItems.slice(0, 3).map((s: any) => ({symbol: s.symbol, name: s.name})))
      
      // ✨ 改进：只在需要时加载页面数据
      if (isInitialLoad) {
        // 初始加载：清空缓存并设置第一页数据
        allItemsCacheRef.current = [...firstPageItems]
        loadingPagesRef.current.clear()
      } else {
        // 刷新时：只更新第一页的数据，保留已加载的后续页面
        const firstPageSize = Math.min(100, allItemsCacheRef.current.length)
        allItemsCacheRef.current.splice(0, firstPageSize, ...firstPageItems)
      }
      
      // 立即显示数据（不在此处应用搜索，搜索由 performFrontendSearch 单独处理）
      let displayItems = allItemsCacheRef.current.map((stock: any) => ({
        symbol: stock.symbol,
        name: stock.name,
        completion_percentage: stock.completion_percentage,
        fields_filled: stock.fields_filled,
        total_fields: stock.total_fields,
        article_count: stock.article_count || 0
      }))
      
      setItems(displayItems)
      setTotal(firstPageData.total_stocks || 0)
      setPage(1)  // 重置到第1页
      
      setProgress({
        ...firstPageData,
        stocks_detail: firstPageItems
      })
      
      // ✨ 改进说明：删除了自动加载所有页面的代码
      // 现在只在用户翻页时才调用 loadPageOnDemand() 加载该页数据
      // 这样可以显著减少 API 请求（从 31+ 个减少到 1-2 个）
    }catch(e:any){
      console.error('加载数据失败:', e)
    }finally{
      setIsLoadingData(false)
    }
  },[showInvalid, market])

  // 后台加载剩余页面的函数（已弃用，改为按需加载）
  const loadRemainingPages = React.useCallback(async (totalStocks: number, showInvalidFlag: boolean = false) => {
    // ✨ 此函数已不再使用，保留以保持代码兼容性
    // 现在改为按需加载：当用户翻页时才调用 loadPageOnDemand()
    console.log('⚠️ loadRemainingPages() 已不再自动调用，改为按需加载模式')
  }, [market])

  // ✨ 新增：按需加载特定页面（用户翻页时调用）
  const loadPageOnDemand = React.useCallback(async (targetPage: number) => {
    // 计算目标页的数据范围
    const pageStartIdx = (targetPage - 1) * 100
    const pageEndIdx = targetPage * 100
    
    // 检查该页数据是否已在缓存中
    if (allItemsCacheRef.current.length >= pageEndIdx) {
      console.log(`✅ 页面 ${targetPage} 已在缓存中（缓存大小: ${allItemsCacheRef.current.length}），直接使用`)
      return
    }
    
    // 检查该页是否正在加载
    if (loadingPagesRef.current.has(targetPage)) {
      console.log(`⏳ 页面 ${targetPage} 正在加载，请稍候...`)
      return
    }
    
    // 标记该页为加载中
    loadingPagesRef.current.add(targetPage)
    
    try {
      console.log(`📥 按需加载第 ${targetPage} 页（市场: ${market}）...`)
      
      const pageUrl = buildApiUrl(
        `/api/news/stocks/progress?page=${targetPage}&page_size=100&show_invalid=${showInvalid}&market=${encodeURIComponent(market)}`
      )
      
      const pageRes = await fetch(pageUrl, { cache: 'no-store' })
      
      if (!pageRes.ok) {
        throw new Error(await pageRes.text())
      }
      
      const pageData = await pageRes.json()
      const pageItems = pageData.stocks_detail || []
      
      // 添加到缓存
      allItemsCacheRef.current.push(...pageItems)
      
      console.log(`✅ 第 ${targetPage} 页加载完成（${pageItems.length} 条数据，缓存总大小: ${allItemsCacheRef.current.length}）`)
      
    } catch (e: any) {
      console.error(`❌ 加载第 ${targetPage} 页失败:`, e)
    } finally {
      loadingPagesRef.current.delete(targetPage)
    }
  }, [showInvalid, market])

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

  const loadProgress = React.useCallback(async () => {
    // 进度数据已在 load() 中加载，此处保留为空实现以保持兼容性
  }, [])

  // ✨ 初始化加载：只在组件挂载时执行一次
  React.useEffect(()=>{ 
    console.log('🚀 组件初始化，首次加载数据...')
    load(true) 
  },[])  // 空依赖项数组：只在组件初始化时执行一次
  
  // 🔧 当市场筛选改变时，重新加载数据
  React.useEffect(() => {
    console.log('🔄 市场改变为:', market)
    // 清空缓存和加载标记
    allItemsCacheRef.current = []
    loadingPagesRef.current.clear()
    lastLoadTimeRef.current = 0  // 重置防抖计时器，允许立即加载
    
    // 立即加载新市场的数据
    load(true)
  }, [market])  // 只在market改变时触发
  
  // 自动刷新：降低频率以减少后端压力
  // 任务进度每 60 秒更新一次，完整数据根据用户设置（默认 30 秒）更新
  React.useEffect(() => {
    if (!autoRefresh) return
    
    // 任务进度更新（60 秒一次，避免频繁查询）
    const progressTimer = setInterval(() => {
      loadTaskProgress()
    }, 60000)
    
    // 完整数据刷新（按用户设定间隔，最少 30 秒）
    const fullDataTimer = setInterval(() => {
      load(false)  // 刷新时设置 isInitialLoad=false，不重新加载所有页面
    }, Math.max(refreshInterval * 1000, 30000))
    
    return () => {
      clearInterval(progressTimer)
      clearInterval(fullDataTimer)
    }
  }, [autoRefresh, refreshInterval, loadTaskProgress])  // 移除 load 依赖项，避免重复创建定时器

  const formatTime = (isoString: string | null | undefined) => {
    if (!isoString) return '-'
    try {
      const date = new Date(isoString)
      return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    } catch {
      return '-'
    }
  }

  return (
    <div style={{padding:16}}>
      {/* 实时任务进度显示 */}
      {taskProgress && taskProgress.is_running && (
        <div style={{marginBottom:16, padding:12, background:'#fef3c7', border:'1px solid #fcd34d', borderRadius:8}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8}}>
            <div style={{fontSize:13, fontWeight:600, color:'#1a1a1a'}}>
              🔄 Profile 更新任务进行中...
            </div>
            <div style={{fontSize:12, color:'#1f2937', display:'flex', gap:16}}>
              <span>📊 {taskProgress.processed} / {taskProgress.total_stocks}</span>
              <span>✅ {taskProgress.successful} · ❌ {taskProgress.failed}</span>
              <span>⏱️ {taskProgress.elapsed_time_seconds}s</span>
              <span>🚀 {taskProgress.speed_stocks_per_minute.toFixed(1)}/分钟</span>
            </div>
          </div>
          <div style={{fontSize:11, color:'#6b7280', marginBottom:8}}>
            当前处理: {taskProgress.current_stock_name} ({taskProgress.current_stock})
          </div>
          <div style={{width:'100%', height:4, background:'#fee2e2', borderRadius:2, overflow:'hidden'}}>
            <div 
              style={{
                width: `${taskProgress.progress_percentage}%`,
                background: '#f59e0b',
                height:'100%',
                transition:'width 0.1s linear'
              }}
            />
          </div>
          <div style={{marginTop:6, fontSize:11, color:'#6b7280', textAlign:'right'}}>
            进度: {taskProgress.progress_percentage.toFixed(1)}% · 预计剩余: {Math.floor(taskProgress.estimated_remaining_seconds / 60)}分钟 {taskProgress.estimated_remaining_seconds % 60}秒
          </div>
        </div>
      )}

      {/* 简化的总体 Profile 统计 */}
      {progress && (
        <div style={{marginBottom:16, padding:12, background:'#f0f9ff', border:'1px solid #bfdbfe', borderRadius:8}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
            <div style={{fontSize:13, fontWeight:600, color:'#1a1a1a'}}>
              📋 Profile 数据填充进度
            </div>
            <div style={{fontSize:12, color:'#1f2937', display:'flex', gap:20}}>
              <span>✅ 已完成: <strong style={{color:'#10b981'}}>{progress.completed_profiles}</strong> / {progress.total_stocks}</span>
              <span>� 完成度: <strong style={{color:'#f59e0b'}}>{progress.progress_percentage.toFixed(2)}%</strong></span>
              <span>📈 平均: <strong>{progress.average_completion.toFixed(1)}%</strong></span>
            </div>
          </div>
          {/* 简单进度条 */}
          <div style={{width:'100%', height:6, background:'#e5e7eb', borderRadius:3, overflow:'hidden', marginTop:8}}>
            <div 
              style={{
                width: `${progress.progress_percentage}%`,
                background: progress.progress_percentage >= 50 ? '#10b981' : '#f59e0b',
                height:'100%',
                transition:'width 0.3s ease'
              }}
            />
          </div>
        </div>
      )}

      <div style={{display:'flex', gap:8, alignItems:'center', marginBottom:12, flexWrap:'wrap'}}>
        <input value={q} onChange={e=> handleSearchChange(e.target.value)} onBlur={handleSearchBlur} placeholder='按代码或名称筛选' style={{padding:'6px 8px', border:'1px solid #e5e7eb', borderRadius:8}}/>
        
        {/* 市场选择器 */}
        <select 
          value={market}
          onChange={(e) => {
            setMarket(e.target.value)
          }}
          style={{
            padding:'6px 8px', 
            border:'1px solid #3b82f6', 
            borderRadius:8,
            background:'#eff6ff',
            color:'#1e40af',
            fontWeight:600,
            cursor:'pointer'
          }}
        >
          <option value="A股">📍 A股</option>
          <option value="港股">🇭🇰 港股</option>
          <option value="美股">🇺🇸 美股</option>
          <option value="全部">🌍 全部市场</option>
        </select>
        
        {/* 过滤无效 Profiles 开关 */}
        <label style={{fontSize:12, color:'#6b7280', display:'flex', gap:4, alignItems:'center', cursor:'pointer', marginLeft:'auto', borderLeft:'1px solid #e5e7eb', paddingLeft:8}}>
          <input 
            type='checkbox' 
            checked={showInvalid} 
            onChange={(e)=> setShowInvalid(e.target.checked)}
            style={{cursor:'pointer'}}
          />
          显示已作废数据
        </label>
        
        {/* 刷新控制 */}
        <div style={{display:'flex', gap:6, alignItems:'center'}}>
          <label style={{fontSize:12, color:'#6b7280', display:'flex', gap:4, alignItems:'center', cursor:'pointer'}}>
            <input 
              type='checkbox' 
              checked={autoRefresh} 
              onChange={(e)=> setAutoRefresh(e.target.checked)}
              style={{cursor:'pointer'}}
            />
            自动刷新
          </label>
          {autoRefresh && (
            <select 
              value={refreshInterval} 
              onChange={(e)=> setRefreshInterval(Number(e.target.value))}
              style={{padding:'4px 6px', border:'1px solid #e5e7eb', borderRadius:4, fontSize:12}}
            >
              <option value={3}>3 秒</option>
              <option value={5}>5 秒</option>
              <option value={10}>10 秒</option>
              <option value={15}>15 秒</option>
              <option value={30}>30 秒</option>
            </select>
          )}
          <button 
            onClick={()=> { load(false); loadTaskProgress() }} 
            style={{padding:'6px 10px', border:'1px solid #e5e7eb', borderRadius:4, background:'#fff', cursor:'pointer'}}
            title='手动刷新数据'
          >
            🔄 刷新
          </button>
        </div>
      </div>
      <div style={{border:'1px solid #e5e7eb', borderRadius:8, overflow:'hidden'}}>
        <table style={{width:'100%', borderCollapse:'collapse', fontSize:13}}>
          <thead style={{background:'#f8fafc'}}>
            <tr>
              <th style={{textAlign:'left', padding:'8px'}}>名称</th>
              <th style={{textAlign:'left', padding:'8px'}}>代码</th>
              <th style={{textAlign:'left', padding:'8px'}}>开始统计</th>
              <th style={{textAlign:'right', padding:'8px'}}>文章数</th>
              <th style={{textAlign:'center', padding:'8px'}}>Profile 完成度</th>
              <th style={{textAlign:'center', padding:'8px'}}>更新状态</th>
              <th style={{textAlign:'center', padding:'8px'}}>最后更新</th>
              <th style={{textAlign:'right', padding:'8px'}}>操作</th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              // 计算分页：只显示当前页的数据
              const startIdx = (page - 1) * pageSize
              const endIdx = startIdx + pageSize
              const paginatedItems = items.slice(startIdx, endIdx)
              
              if (loading && items.length === 0) {
                return <tr><td colSpan={8} style={{padding:16, textAlign:'center', color:'#9ca3af'}}>加载中...</td></tr>
              }
              
              if (!loading && items.length === 0) {
                return <tr><td colSpan={8} style={{padding:16, textAlign:'center', color:'#9ca3af'}}>没有数据</td></tr>
              }
              
              return paginatedItems.map(it => {
                // 根据 completion_percentage 判断是否完成 (≥50% 为已完成)
                const isCompleted = (it.completion_percentage ?? 0) >= 50
                return (
                  <tr key={it.symbol}>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9'}}>{it.name||'-'}</td>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9'}}>{it.symbol}</td>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9'}}>{it.start_date||'-'}</td>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9', textAlign:'right'}}>{it.article_count}</td>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9', textAlign:'center'}}>
                      <div style={{display:'flex', alignItems:'center', justifyContent:'center', gap:4}}>
                        <div style={{width:60, height:6, background:'#e5e7eb', borderRadius:2, overflow:'hidden'}}>
                          <div 
                            style={{
                              width: `${it.completion_percentage ?? 0}%`,
                              height:'100%',
                              background: isCompleted ? '#10b981' : '#f59e0b',
                              transition:'width 0.3s ease'
                            }}
                          />
                        </div>
                        <span style={{fontSize:11, color:'#6b7280', minWidth:30}}>{(it.completion_percentage ?? 0).toFixed(0)}%</span>
                      </div>
                    </td>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9', textAlign:'center'}}>
                      <div style={{
                        width: 12,
                        height: 12,
                        borderRadius: '50%',
                        backgroundColor: isCompleted ? '#10b981' : '#d1d5db',
                        margin: '0 auto',
                        boxShadow: isCompleted ? '0 0 6px rgba(16, 185, 129, 0.5)' : 'none',
                        transition: 'all 0.2s ease'
                      }} title={isCompleted ? '已完成' : '待更新'}>
                      </div>
                    </td>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9', textAlign:'center', fontSize: 12, color: '#6b7280'}}>
                      {formatTime(it.last_updated_at)}
                    </td>
                    <td style={{padding:'8px', borderTop:'1px solid #f1f5f9', textAlign:'right'}}>
                      <button onClick={()=> onOpen(it.symbol)} style={{padding:'4px 10px', border:'1px solid #e5e7eb', borderRadius:8, background:'#fff'}}>查看</button>
                    </td>
                  </tr>
                )
              })
            })()}
          </tbody>
        </table>
      </div>
      <div style={{marginTop:12, display:'flex', justifyContent:'space-between', alignItems:'center'}}>
        <div style={{fontSize:12, color:'#6b7280'}}>共 {total} 条，已加载 {allItemsCacheRef.current.length} 条</div>
        <div style={{display:'flex', gap:8, alignItems:'center'}}>
          <button 
            disabled={page<=1} 
            onClick={()=> {
              const newPage = Math.max(1, page - 1)
              setPage(newPage)
              loadPageOnDemand(newPage)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }} 
            style={{padding:'6px 10px', border:'1px solid #e5e7eb', borderRadius:8, background:'#fff', cursor: page > 1 ? 'pointer' : 'not-allowed', opacity: page > 1 ? 1 : 0.5}}
          >
            上一页
          </button>
          <span style={{fontSize:12}}>第 {page} 页</span>
          <button 
            disabled={(page*pageSize)>=total} 
            onClick={()=> {
              const newPage = page + 1
              setPage(newPage)
              loadPageOnDemand(newPage)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }} 
            style={{padding:'6px 10px', border:'1px solid #e5e7eb', borderRadius:8, background:'#fff', cursor: (page*pageSize) < total ? 'pointer' : 'not-allowed', opacity: (page*pageSize) < total ? 1 : 0.5}}
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  )
}
