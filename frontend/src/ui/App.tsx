import React, { useEffect, useMemo, useState, useRef } from 'react'
import { sliceByTimeRange } from './utils/rangeSlice'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Area, ComposedChart, Legend } from 'recharts'
import * as ReactWindow from 'react-window'
import Dashboard from './Dashboard'
import DailyAnalysisPage from './DailyAnalysisPage'
import MacroReportPage from './MacroReportPage'
import FundFlowPanel from './FundFlowPanel'
import WatchlistSnapshot from './WatchlistSnapshot'
import FloatingModule from './FloatingModule'
import WatchlistAnalysis from './WatchlistAnalysis'
import ModernNewsComponent from './ModernNewsComponent'
import NewsManagement from './NewsManagement'
import QueryTemplateManager from './QueryTemplateManager'
import StocksNewsIndex from './StocksNewsIndex'
import StockNewsDetail from './StockNewsDetail'
import ProfileValidationManager from './ProfileValidationManager'
import { API_BASE, buildApiUrl, API_ENDPOINTS } from '../config/api'

const VirtualList = (ReactWindow as any).List as any

// MOVERS endpoints centralization removed; using API_ENDPOINTS.MOVERS now

async function jfetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(path), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers||{}) }
  })
  if(!r.ok) throw new Error(await r.text())
  return r.json()
}

type WatchItem = { symbol: string; name?: string; sector?: string; enabled: boolean }
type PriceRow = { trade_date: string; close: number; open?: number; high?: number; low?: number; vol?: number }
type ReportResp = {
  symbol: string
  data_updated: string | null
  data_quality_score: number | null
  prediction_confidence: number | null
  analysis_summary: string | null
  
  // 价格数据
  price_data: {
    date: string
    open: number | null
    high: number | null
    low: number | null
    close: number | null
    volume: number
    pct_change: number
    type: 'historical'
  }[]
  
  // 预测数据
  predictions: {
    date: string
    predicted_price: number
    upper_bound: number
    lower_bound: number
    type: 'prediction'
  }[]
  
  // 前端兼容格式
  dates: string[]
  predictions_mean: number[]
  predictions_upper: number[]
  predictions_lower: number[]
  
  // 最新价格和信号
  latest_price: any
  signal: { 
    trade_date: string
    ma_short: number
    ma_long: number
    rsi: number
    macd: number
    signal_score: number
    action: string 
  } | null
  
  // 保持向后兼容
  latest?: any
  forecast?: { target_date: string; yhat: number; yl: number; yu: number }[]
}

// 自定义弹窗组件
function CustomDialog({ 
  isOpen, 
  onClose, 
  title, 
  message, 
  type = 'alert',
  onConfirm 
}: {
  isOpen: boolean
  onClose: () => void
  title?: string
  message: string
  type?: 'alert' | 'confirm'
  onConfirm?: () => void
}) {
  if (!isOpen) return null

  const handleConfirm = () => {
    if (onConfirm) onConfirm()
    onClose()
  }

  const handleCancel = () => {
    onClose()
  }

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      width: '100vw',
      height: '100vh',
      background: 'rgba(0,0,0,0.3)',
      zIndex: 9999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }}>
      <div style={{
        background: '#fff',
        borderRadius: 12,
        padding: 24,
        minWidth: 320,
        maxWidth: 480,
        boxShadow: '0 4px 24px rgba(0,0,0,0.15)'
      }}>
        {title && (
          <div style={{
            fontWeight: 600,
            fontSize: 18,
            marginBottom: 16,
            color: type === 'confirm' ? '#d32f2f' : '#1976d2'
          }}>
            {title}
          </div>
        )}
        
        <div style={{
          fontSize: 14,
          color: '#424242',
          marginBottom: 24,
          lineHeight: 1.5
        }}>
          {message}
        </div>
        
        <div style={{
          display: 'flex',
          gap: 12,
          justifyContent: 'flex-end'
        }}>
          {type === 'confirm' && (
            <button
              onClick={handleCancel}
              style={{
                padding: '8px 16px',
                border: '1px solid #e5e7eb',
                borderRadius: 6,
                background: '#fff',
                cursor: 'pointer',
                color: '#6b7280'
              }}
            >
              取消
            </button>
          )}
          <button
            onClick={handleConfirm}
            style={{
              padding: '8px 16px',
              border: 'none',
              borderRadius: 6,
              background: type === 'confirm' ? '#d32f2f' : '#1976d2',
              color: '#fff',
              cursor: 'pointer',
              fontWeight: 500
            }}
          >
            {type === 'confirm' ? '确定' : '知道了'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Toast 消息组件
function Toast({ 
  isVisible, 
  message, 
  type = 'success',
  onClose 
}: {
  isVisible: boolean
  message: string
  type?: 'success' | 'error' | 'info'
  onClose: () => void
}) {
  useEffect(() => {
    if (isVisible) {
      const timer = setTimeout(() => {
        onClose()
      }, 3000) // 3秒后自动消失
      return () => clearTimeout(timer)
    }
  }, [isVisible, onClose])

  if (!isVisible) return null

  const getToastStyles = () => {
    const baseStyles = {
      position: 'fixed' as const,
      top: '20px',
      right: '20px',
      padding: '12px 20px',
      borderRadius: '8px',
      color: '#fff',
      fontWeight: 500,
      fontSize: '14px',
      zIndex: 10000,
      boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      animation: 'slideIn 0.3s ease-out',
      minWidth: '200px',
      maxWidth: '400px'
    }

    const typeStyles = {
      success: { background: '#10b981' },
      error: { background: '#ef4444' },
      info: { background: '#3b82f6' }
    }

    return { ...baseStyles, ...typeStyles[type] }
  }

  return (
    <>
      <style>
        {`
          @keyframes slideIn {
            from {
              transform: translateX(100%);
              opacity: 0;
            }
            to {
              transform: translateX(0);
              opacity: 1;
            }
          }
        `}
      </style>
      <div style={getToastStyles()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>{message}</span>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#fff',
              cursor: 'pointer',
              marginLeft: '12px',
              fontSize: '16px',
              padding: '0',
              opacity: 0.8
            }}
          >
            ×
          </button>
        </div>
      </div>
    </>
  )
}

function Metric({ label, value }: { label: string; value: React.ReactNode }){
  return <div style={{padding:'10px', border:'1px solid #e5e7eb', borderRadius:12}}>
    <div style={{fontSize:12, color:'#6b7280'}}>{label}</div>
    <div style={{fontSize:18, fontWeight:600}}>{value}</div>
  </div>
}

// 自选汇总统计组件
function WatchlistSummary({ watch, current }: { watch: any[]; current?: string }){
  // 计算汇总：上涨/下跌家数、平均涨幅、主力净流入总和（需二次请求或已有实时数据，这里先从 window 缓存尝试）
  const [stats, setStats] = React.useState({ up:0, down:0, flat:0, avgPct:0, totalNet:0 })

  React.useEffect(()=>{
    // 暂用全局缓存 window.__watchlistSnapshotRows (由 WatchlistSnapshot 渲染时可挂载) 若不可用则跳过
    const g:any = (window as any).__watchlistSnapshotRows
    if(!Array.isArray(g)) return
    if(g.length===0){ setStats({up:0,down:0,flat:0,avgPct:0,totalNet:0}); return }
    let up=0,down=0,flat=0,sum=0,totalNet=0
    g.forEach((r:any)=>{
      const pct = Number(r.pct_change)
      if(!isNaN(pct)) sum += pct
      if(pct>0) up++; else if(pct<0) down++; else flat++
      const mainNet = Number(r.main_net)
      if(!isNaN(mainNet)) totalNet += mainNet
    })
    const avgPct = sum / g.length
    setStats({up,down,flat,avgPct,totalNet})
  }, [watch, current])

  const pillStyle:React.CSSProperties={
    padding:'4px 10px',
    background:'#f1f5f9',
    borderRadius:999,
    fontSize:11,
    display:'flex',
    alignItems:'center',
    gap:4,
    whiteSpace:'nowrap'
  }
  return (
    <div style={{marginTop:10, display:'flex', flexWrap:'wrap', gap:6}}>
      <div style={pillStyle}>自选 {watch.length} 只</div>
      <div style={pillStyle}>↑ {stats.up}</div>
      <div style={pillStyle}>↓ {stats.down}</div>
      {stats.flat>0 && <div style={pillStyle}>→ {stats.flat}</div>}
      <div style={pillStyle}>平均涨幅 {stats.avgPct.toFixed(2)}%</div>
      <div style={pillStyle}>主力净流入 {(stats.totalNet/1e8).toFixed(2)} 亿</div>
    </div>
  )
}

// 深度行情页面（占位版）
function DeepMarketInsight(){
  const [live, setLive] = React.useState<any|null>(null)
  const [exchange, setExchange] = React.useState<string>('ALL')
  const [selectedSymbol, setSelectedSymbol] = React.useState<string|undefined>()
  const [series, setSeries] = React.useState<any|null>(null)
  const [loadingSeries, setLoadingSeries] = React.useState(false)
  const [error, setError] = React.useState<string|undefined>()
  const [autoRefresh, setAutoRefresh] = React.useState<boolean>(true)
  const [refreshIntervalMs, setRefreshIntervalMs] = React.useState<number>(15000)
  const timerRef = React.useRef<any>(null)

  const fetchJSON = async (endpointOrFull:string) => {
    const url = endpointOrFull.startsWith('http') ? endpointOrFull : buildApiUrl(endpointOrFull)
    const r = await fetch(url)
    if(!r.ok) throw new Error(await r.text())
    return r.json()
  }
  const loadLive = React.useCallback(()=>{
    fetchJSON(`/api/movers/live_insight?exchange=${exchange}&limit=20`).then(d=>{
      setLive(d); setError(undefined)
    }).catch(e=> setError(String(e)))
  },[exchange])

  React.useEffect(()=>{ loadLive(); },[loadLive])

  React.useEffect(()=>{
    if(!autoRefresh){ if(timerRef.current){ clearInterval(timerRef.current); timerRef.current=null;} return }
    timerRef.current = setInterval(()=>{ loadLive() }, refreshIntervalMs)
    return ()=> { if(timerRef.current) clearInterval(timerRef.current) }
  },[autoRefresh, refreshIntervalMs, loadLive])

  React.useEffect(()=>{
    if(!selectedSymbol) return
    setLoadingSeries(true)
    fetchJSON(`/api/movers/live_series/${selectedSymbol}?days=60`).then(d=>{ setSeries(d); setLoadingSeries(false) }).catch(e=>{ setError(String(e)); setLoadingSeries(false) })
  },[selectedSymbol])

  const renderTable = (title:string, rows:any[]) => (
    <div style={{flex:1, minWidth:0}}>
      <div style={{fontWeight:600, marginBottom:6}}>{title}</div>
      <div style={{border:'1px solid #e5e7eb', borderRadius:8, overflow:'hidden'}}>
        <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
          <thead style={{background:'#f8fafc'}}>
            <tr>
              <th style={{textAlign:'left', padding:'6px 8px'}}>代码</th>
              <th style={{textAlign:'left', padding:'6px 8px'}}>名称</th>
              <th style={{textAlign:'right', padding:'6px 8px'}}>涨跌幅%</th>
              <th style={{textAlign:'right', padding:'6px 8px'}}>价格</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r=> (
              <tr key={r.symbol}>
                <td style={{padding:'6px 8px', borderTop:'1px solid #f1f5f9'}}>{r.symbol}</td>
                <td style={{padding:'6px 8px', borderTop:'1px solid #f1f5f9', color:'#64748b'}}>{r.name||'-'}</td>
                <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f1f5f9', color: (r.pct_chg)>0?'#16a34a':'#dc2626'}}>{r.pct_chg!=null? Number(r.pct_chg).toFixed(2):'-'}</td>
                <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f1f5f9'}}>{r.price!=null? Number(r.price).toFixed(2):'-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )

  return (
    <div style={{padding:12}}>
      <h2 style={{margin:'0 0 12px', fontSize:22}}>深度每日行情（实时独立数据源）</h2>
      <div style={{display:'flex', gap:12, flexWrap:'wrap', alignItems:'center', marginBottom:12}}>
        <div style={{display:'flex', gap:6, alignItems:'center'}}>
          <label style={{fontSize:12, color:'#64748b'}}>交易所:</label>
          <select value={exchange} onChange={e=> setExchange(e.target.value)} style={{fontSize:12, padding:'4px 6px'}}>
            <option value="ALL">全部 A 股</option>
            <option value="SH">上证 (SH)</option>
            <option value="SZ">深证 (SZ)</option>
          </select>
        </div>
        <button onClick={()=> loadLive()} style={{padding:'4px 10px', fontSize:12, border:'1px solid #e5e7eb', borderRadius:6, background:'#fff', cursor:'pointer'}}>手动刷新</button>
        <label style={{fontSize:12, display:'flex', alignItems:'center', gap:4}}>
          <input type="checkbox" checked={autoRefresh} onChange={e=> setAutoRefresh(e.target.checked)} />自动刷新
        </label>
        <select value={refreshIntervalMs} onChange={e=> setRefreshIntervalMs(Number(e.target.value))} style={{fontSize:12, padding:'4px 6px'}}>
          <option value={10000}>10s</option>
          <option value={15000}>15s</option>
          <option value={30000}>30s</option>
          <option value={60000}>60s</option>
        </select>
        {live && <div style={{fontSize:12, fontWeight:500, color: live.mock ? '#dc2626' : '#0ea5e9', padding:'2px 8px', borderRadius:4, background: live.mock ? '#fee2e2' : '#e0f2fe'}}>
          数据源：{(() => {
            const p = live.provider;
            if(p==='akshare') return 'Akshare';
            if(p==='eastmoney') return '东方财富';
            if(p==='sina_top'||p==='sina') return '新浪';
            if(p==='tencent') return '腾讯';
            if(live.mock) return '模拟数据（仅占位）';
            return p||'-';
          })()} （全量 {live.universe_size}） 更新时间: {new Date(live.generated_at).toLocaleTimeString()}
        </div>}
        {live && <div style={{fontSize:12, marginTop:4, color:'#64748b', background:'#f8fafc', borderRadius:4, padding:'6px 10px', maxWidth:600}}>
          <b>数据源校验说明：</b> 客户可通过以下官方榜单链接手动校验当前榜单数据：<br/>
          {(() => {
            const p = live.provider;
            if(p==='sina_top'||p==='sina') return <a href="https://vip.stock.finance.sina.com.cn/mkt/#hs_a" target="_blank" rel="noopener noreferrer" style={{color:'#0ea5e9'}}>新浪A股实时榜单</a>;
            if(p==='eastmoney') return <a href="https://quote.eastmoney.com/center/gridlist.html#hs_a_board" target="_blank" rel="noopener noreferrer" style={{color:'#0ea5e9'}}>东方财富A股榜单</a>;
            if(p==='tencent') return <a href="https://stockapp.finance.qq.com/mstats/" target="_blank" rel="noopener noreferrer" style={{color:'#0ea5e9'}}>腾讯A股榜单</a>;
            if(p==='akshare') return <span>Akshare为聚合数据源，请用 <a href="https://quote.eastmoney.com/center/gridlist.html#hs_a_board" target="_blank" rel="noopener noreferrer" style={{color:'#0ea5e9'}}>东方财富榜单</a> 或 <a href="https://vip.stock.finance.sina.com.cn/mkt/#hs_a" target="_blank" rel="noopener noreferrer" style={{color:'#0ea5e9'}}>新浪榜单</a> 校验。</span>;
            if(live.mock) return <span>当前为模拟数据，仅供占位，无需校验。</span>;
            return <span>未知数据源，请手动比对主流榜单。</span>;
          })()}
        </div>}
      </div>
      {error && <div style={{color:'#dc2626', fontSize:12, marginBottom:8}}>错误：{error}</div>}
      {live && (
        <div style={{display:'flex', gap:16, flexWrap:'wrap'}}>
          {renderTable('涨幅 TOP', live.gainers)}
          {renderTable('跌幅 TOP', live.losers)}
        </div>
      )}
      <div style={{marginTop:16, display:'flex', gap:12}}>
        <div style={{flex:2, minWidth:0, padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
          <div style={{fontWeight:600, marginBottom:8}}>日线走势 {selectedSymbol && <span style={{color:'#64748b', fontWeight:400}}>({selectedSymbol})</span>}</div>
          {!selectedSymbol && <div style={{fontSize:12, color:'#6b7280'}}>点击上方表格中的股票行加载近 60 日价格曲线</div>}
          {loadingSeries && <div style={{fontSize:12}}>加载中...</div>}
          {series && !loadingSeries && (
            <div style={{height:300}}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={series.rows} margin={{top:10,right:20,bottom:10,left:0}}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="trade_date" tick={{fontSize:11}} minTickGap={24} />
                  <YAxis tick={{fontSize:11}} domain={['auto','auto']} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="close" name="收盘" stroke="#2563eb" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="pct_chg" name="日涨幅%" stroke="#10b981" dot={false} strokeWidth={1} yAxisId={1} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function App(){
  const [currentPage, setCurrentPage] = useState<'main' | 'dashboard' | 'daily-analysis' | 'macro-report' | 'news' | 'news-management' | 'deep-insight' | 'query-templates' | 'stocks-news' | 'profile-manager'>('main')
  const [stocksDetailSymbol, setStocksDetailSymbol] = useState<string | null>(null)
  const [watch, setWatch] = useState<WatchItem[]>([])
  const [current, setCurrent] = useState<string | undefined>(undefined)
  const [report, setReport] = useState<ReportResp | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)
  const [watchlistSnapshotRefresh, setWatchlistSnapshotRefresh] = useState<(() => void) | null>(null)

  const [name, setName] = useState('')
  const [searchResults, setSearchResults] = useState<{ts_code:string,symbol:string,name:string,market:string}[]>([])
  const [searching, setSearching] = useState(false)
  const [showSearchModal, setShowSearchModal] = useState(false)

  const [prices, setPrices] = useState<PriceRow[]>([])

  // 时间区间选择状态
  const [timeRange, setTimeRange] = useState<'5d' | '1m' | '3m' | '6m' | '1y' | 'all'>('5d')
  const [customDays, setCustomDays] = useState<number>(5)

  // 自定义弹窗状态
  const [dialog, setDialog] = useState({
    isOpen: false,
    title: '',
    message: '',
    type: 'alert' as 'alert' | 'confirm',
    onConfirm: undefined as (() => void) | undefined
  })

  // Toast 状态
  const [toast, setToast] = useState({
    isVisible: false,
    message: '',
    type: 'success' as 'success' | 'error' | 'info'
  })

  // Drawer 管理自选列表
  const [isWatchDrawerOpen, setWatchDrawerOpen] = useState(false)
  const [watchSearch, setWatchSearch] = useState('')
  const filteredWatch = useMemo(
    () => watch.filter(w => (w.name || w.symbol).toLowerCase().includes(watchSearch.toLowerCase())),
    [watch, watchSearch]
  )

  // 显示 Toast 消息
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({
      isVisible: true,
      message,
      type
    })
  }

  // 关闭 Toast
  const closeToast = () => {
    setToast({
      isVisible: false,
      message: '',
      type: 'success'
    })
  }

  // 显示提示弹窗（仅用于需要用户确认的情况）
  const showAlert = (message: string, title?: string) => {
    setDialog({
      isOpen: true,
      title: title || '提示',
      message,
      type: 'alert',
      onConfirm: undefined
    })
  }

  // 显示确认弹窗
  const showConfirm = (message: string, onConfirm: () => void, title?: string) => {
    setDialog({
      isOpen: true,
      title: title || '确认',
      message,
      type: 'confirm',
      onConfirm
    })
  }

  // 关闭弹窗
  const closeDialog = () => {
    setDialog({
      isOpen: false,
      title: '',
      message: '',
      type: 'alert',
      onConfirm: undefined
    })
  }

  async function loadWatch(){
    const list = await jfetch<WatchItem[]>('/watchlist')
    setWatch(list)
    if(!current && list.length) setCurrent(list[0].symbol)
  }
  useEffect(()=>{ loadWatch() }, [])

  useEffect(()=>{
    if(!current) return
    ;(async()=>{
      try{
        setLoading(true); setError(undefined)
        const r = await jfetch<ReportResp>(`/api/report/${current}/full?timeRange=${timeRange}`)
        setReport(r)
        
        // 新API已经包含了价格数据和预测数据，不需要单独获取prices
        if(r.price_data && r.price_data.length > 0) {
          // 将API返回的price_data转换为PriceRow格式
          const priceRows: PriceRow[] = r.price_data.map(p => ({
            trade_date: p.date,
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close,
            volume: p.volume,
            pct_change: p.pct_change
          }))
          setPrices(priceRows)
        } else {
          setPrices([])
        }
      }catch(e:any){
        if(e?.message?.includes('no data')) {
          setError(undefined)
          setReport(undefined)
        } else {
          setError(String(e?.message||e))
        }
      }
      finally{ setLoading(false) }
    })()
  },[current, timeRange])


  // 股票搜索逻辑
  // 按回车键触发搜索
  const handleSearchStocks = async () => {
    if(!name || name.length<2) { 
      setSearchResults([])
      setShowSearchModal(false)
      return 
    }
    
    setSearching(true)
    // 立即显示搜索模态框显示加载状态
    setShowSearchModal(true)
    try {
      const res = await jfetch<{ts_code:string,symbol:string,name:string,market:string}[]>(`/search_stock?q=${encodeURIComponent(name)}`)
      setSearchResults(res)
      // 如果没有结果，3秒后自动关闭弹窗
      if(res.length === 0) {
        setTimeout(() => {
          setShowSearchModal(false)
        }, 3000)
      }
    } catch(error) {
      console.error('搜索失败:', error)
      setSearchResults([])
      // 搜索失败时也显示3秒后关闭
      setTimeout(() => {
        setShowSearchModal(false)
      }, 3000)
    } finally {
      setSearching(false)
    }
  }

  // 处理股票选择 - 直接添加到自选列表
  const handleStockSelect = async (selectedStock: {ts_code:string,symbol:string,name:string,market:string}) => {
    // 立即关闭弹窗和清理搜索状态
    setShowSearchModal(false)
    setSearchResults([])
    setSearching(false)
    
    // 清空输入框
    setName('')
    
    // 直接添加到自选列表
    setLoading(true)
    setError(undefined)
    try {
      await jfetch('/watchlist', { 
        method:'POST', 
        body: JSON.stringify({
          symbol: selectedStock.ts_code, 
          name: selectedStock.name, 
          enabled: true
        }) 
      })
      await loadWatch()
      showToast(`${selectedStock.name} 已加入自选列表`, 'success')
    } catch(e:any) {
      setError(String(e?.message||e))
      showToast('添加失败，请检查后端服务或网络连接', 'error')
    } finally {
      setLoading(false)
    }
  }

  async function runDaily(){
    try {
      showToast('开始执行当日训练...', 'info')
      setLoading(true)
      await jfetch('/run/daily', { method:'POST' })
      showToast('当日训练执行成功！数据已更新', 'success')
      if(current){ 
        const r = await jfetch<ReportResp>(`/api/report/${current}/full?timeRange=${timeRange}`)
        setReport(r)
        
        // 更新价格数据
        if(r.price_data && r.price_data.length > 0) {
          const priceRows: PriceRow[] = r.price_data.map(p => ({
            trade_date: p.date,
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close,
            volume: p.volume,
            pct_change: p.pct_change
          }))
          setPrices(priceRows)
        }
      }
    } catch (e) {
      console.error('Run daily failed:', e)
      showToast('当日训练执行失败，请检查后端服务', 'error')
    } finally {
      setLoading(false)
    }
  }

  // 将历史数据裁剪逻辑抽离为 util（见 utils/rangeSlice.ts）。
  // 后端可能返回带 buffer 的区间（例如多返回几周数据以便指标计算），
  // 这里通过 sliceByTimeRange 再次确保图表展示严格符合用户选择的交易日长度。
  const merged = useMemo(()=>{
    const m:any[] = []
    if (report?.price_data && report?.predictions) {
      // Apply strict slicing to historical segment before merging predictions.
      // (Predictions are ALWAYS shown, even if they extend beyond the selected historical window.)
      let hist = sliceByTimeRange(report.price_data, timeRange)
      hist.forEach((p:any) => m.push({ date: p.date, close: p.close, type: 'historical' }))
      if (hist.length > 0 && report.predictions.length > 0) {
        const lastHistorical = hist[hist.length - 1]
        m.push({
          date: lastHistorical.date,
          close: lastHistorical.close,
          yhat: lastHistorical.close,
          yl: lastHistorical.close,
            yu: lastHistorical.close,
          type: 'historical_extended'
        })
        report.predictions.forEach(pred => m.push({
          date: pred.date,
          yhat: pred.predicted_price,
          yl: pred.lower_bound,
          yu: pred.upper_bound,
          type: 'prediction'
        }))
      }
    } else {
      const filteredPrices = prices || []
      filteredPrices.forEach(p=>m.push({date:p.trade_date, close:p.close}))
      report?.forecast?.forEach(f=>m.push({date:f.target_date, yhat:f.yhat, yl:f.yl, yu:f.yu}))
    }
    return m.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
  },[prices,report,timeRange])

  return (
    <div className="page-shell">
      <div className="page-container" style={{gap:20}}>
        {/* 导航栏 */}
        <div className="card-panel" style={{padding:'18px 22px'}}>
          <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:16}}>
            <div>
              <div className="page-eyebrow">AI Stock Toolkit</div>
              <h2 className="page-title" style={{fontSize:26}}>A 股 AI 助手</h2>
              <div className="page-subtitle">智能洞察、策略分析与全局新闻的统一工作台</div>
            </div>
            <div style={{display:'flex', flexDirection:'column', gap:12, alignItems:'flex-end'}}>
              <nav style={{display:'flex', gap:12, flexWrap:'wrap', justifyContent:'flex-end'}}>
                <button
                  onClick={() => setCurrentPage('main')}
                  className={`ghost-button ${currentPage === 'main' ? 'nav-active' : ''}`}
                  style={{minWidth:96}}
                >
                  股票分析
                </button>
                <button
                  onClick={() => setCurrentPage('dashboard')}
                  className={`ghost-button ${currentPage === 'dashboard' ? 'nav-active' : ''}`}
                  style={{minWidth:96}}
                >
                  任务监控
                </button>
                <button
                  onClick={() => setCurrentPage('daily-analysis')}
                  className={`ghost-button ${currentPage === 'daily-analysis' ? 'nav-active' : ''}`}
                  style={{minWidth:120}}
                >
                  每日分析
                </button>
                <button
                  onClick={() => setCurrentPage('macro-report')}
                  className={`ghost-button ${currentPage === 'macro-report' ? 'nav-active' : ''}`}
                  style={{minWidth:96}}
                >
                  宏观日报
                </button>
                <button
                  onClick={() => setCurrentPage('news')}
                  className={`ghost-button ${currentPage === 'news' ? 'nav-active' : ''}`}
                  style={{minWidth:96}}
                >
                  财经新闻
                </button>
                <button
                  onClick={() => setCurrentPage('news-management')}
                  className={`ghost-button ${currentPage === 'news-management' ? 'nav-active' : ''}`}
                  style={{minWidth:96}}
                >
                  新闻管理
                </button>
                <button
                  onClick={() => setCurrentPage('deep-insight')}
                  className={`ghost-button ${currentPage === 'deep-insight' ? 'nav-active' : ''}`}
                  style={{minWidth:120}}
                >
                  深度行情
                </button>
                <button
                  onClick={() => { setStocksDetailSymbol(null); setCurrentPage('stocks-news') }}
                  className={`ghost-button ${currentPage === 'stocks-news' ? 'nav-active' : ''}`}
                  style={{minWidth:120}}
                >
                  股票资讯
                </button>
                <button
                  onClick={() => setCurrentPage('query-templates')}
                  className={`ghost-button ${currentPage === 'query-templates' ? 'nav-active' : ''}`}
                  style={{minWidth:120}}
                >
                  查询范式
                </button>
                <button
                  onClick={() => setCurrentPage('profile-manager')}
                  className={`ghost-button ${currentPage === 'profile-manager' ? 'nav-active' : ''}`}
                  style={{minWidth:120}}
                >
                  Profile 管理
                </button>
              </nav>
              <button
                onClick={runDaily}
                disabled={loading}
                className="primary-button"
                style={{opacity: loading ? 0.6 : 1, cursor: loading ? 'not-allowed' : 'pointer'}}
              >
                {loading ? '执行中…' : '手动执行当日训练'}
              </button>
            </div>
          </div>
        </div>

    {/* 页面内容 */}
    {currentPage === 'main' ? (
    <div>
    <div style={{display:'flex', gap:12, alignItems:'flex-start'}}>
      {/* 左侧：自选 + 图表 */}
      <div style={{flex:2, minWidth:0}}>
      <div style={{padding:12}}>

        {/* 自选实时看板 */}
        <FloatingModule
          title="自选实时看板（今日）"
          subtitle="每分钟自动刷新，帮助你快速洞察自选股票表现"
          rightActions={
            <button
              onClick={() => watchlistSnapshotRefresh?.()}
              className="soft-button"
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
            onReadyRefresh={(refresh) => setWatchlistSnapshotRefresh(() => refresh)}
          />
        </FloatingModule>

        <div style={{height:12}} />

  <div style={{display:'flex', gap:6, marginBottom:0, alignItems:'center'}}>
          <div style={{position: 'relative', display: 'flex', alignItems: 'center', flex: 1}}>
            <input
              placeholder='输入股票名称或代码进行搜索，按回车搜索...'
              value={name}
              onChange={e=>setName(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  console.log('Enter pressed, searching stocks')
                  e.preventDefault()
                  handleSearchStocks()
                }
              }}
              autoComplete="off"
              style={{
                width: '100%',
                background: searching ? '#f3f4f6' : '#fff',
                borderColor: searching ? '#3b82f6' : '#e5e7eb',
                border: '1px solid',
                borderRadius: '8px',
                padding: '12px 16px',
                paddingRight: searching ? '100px' : '16px',
                fontSize: '14px'
              }}
            />
            {searching && (
              <div style={{
                position: 'absolute',
                right: '16px',
                top: '50%',
                transform: 'translateY(-50%)',
                fontSize: '12px',
                color: '#3b82f6',
                pointerEvents: 'none',
                fontWeight: '500'
              }}>
                搜索中...
              </div>
            )}
          </div>
          {/* 已按需求移除“搜索后点击选择即可加入自选”提示文字 */}
        </div>
        {error && <div style={{color:'red', fontSize:'12px', marginBottom:12}}>{error}</div>}

        {/* 查询结果弹窗 */}
        {showSearchModal && (
          <div style={{position:'fixed',top:0,left:0,width:'100vw',height:'100vh',background:'rgba(0,0,0,0.15)',zIndex:999,display:'flex',alignItems:'center',justifyContent:'center'}} onClick={()=>setShowSearchModal(false)}>
            <div style={{background:'#fff',borderRadius:12,padding:24,minWidth:320,maxWidth:480,boxShadow:'0 2px 16px #0002'}} onClick={e=>e.stopPropagation()}>
              <div style={{fontWeight:600,fontSize:16,marginBottom:12}}>
                {searching ? '搜索中...' : searchResults.length > 0 ? '查询结果' : '未找到结果'}
              </div>
              
              {searching && (
                <div style={{display:'flex', alignItems:'center', justifyContent:'center', padding:'40px 0'}}>
                  <div style={{
                    width: '32px',
                    height: '32px',
                    border: '3px solid #f3f4f6',
                    borderTop: '3px solid #3b82f6',
                    borderRadius: '50%',
                    animation: 'spin 1s linear infinite'
                  }}></div>
                  <style>
                    {`
                      @keyframes spin {
                        0% { transform: rotate(0deg); }
                        100% { transform: rotate(360deg); }
                      }
                    `}
                  </style>
                  <span style={{marginLeft: '12px', color: '#6b7280'}}>正在搜索股票信息...</span>
                </div>
              )}
              
              {!searching && searchResults.length === 0 && (
                <div style={{textAlign:'center', padding:'40px 0', color:'#6b7280'}}>
                  <div style={{fontSize:'48px', marginBottom:'12px'}}>🔍</div>
                  <div>没有找到匹配的股票</div>
                  <div style={{fontSize:'12px', marginTop:'8px'}}>请尝试使用不同的关键词搜索</div>
                </div>
              )}
              
              {!searching && searchResults.length > 0 && (
                <div style={{maxHeight:320,overflowY:'auto'}}>
                  {searchResults.map(s => (
                    <div key={s.ts_code} style={{ padding: '8px 0', borderBottom: '1px solid #eee', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div>
                        <div style={{fontWeight:500}}>{s.name}</div>
                        <div style={{fontSize:'12px', color:'#888'}}>{s.ts_code} ({s.symbol}) - {s.market}</div>
                      </div>
                      <button
                        style={{ 
                          padding: '8px 16px', 
                          border: 'none', 
                          borderRadius: 6, 
                          background: '#10b981', 
                          color: '#fff',
                          cursor: 'pointer', 
                          fontSize:'12px',
                          fontWeight: '500'
                        }}
                        onClick={(e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          handleStockSelect(s)
                        }}>
                        + 加入自选
                      </button>
                    </div>
                  ))}
                </div>
              )}
              
              <button 
                style={{marginTop:16,padding:'6px 18px',border:'1px solid #e5e7eb',borderRadius:8,background:'#fff',cursor:'pointer'}} 
                onClick={()=>setShowSearchModal(false)}
                disabled={searching}
              >
                {searching ? '搜索中...' : '关闭'}
              </button>
            </div>
          </div>
        )}
  <div style={{display:'flex', gap:6, flexWrap:'wrap', marginTop:0, paddingTop:4, borderTop:'1px solid #f1f5f9', maxHeight:100, overflow:'hidden', alignItems:'center'}}>
          {watch.slice(0, 10).map(w => {
            const label = w.name && w.name.trim() ? `${w.name}(${w.symbol})` : w.symbol
            return (
              <div
                key={w.symbol}
                style={{
                  display:'flex',
                  alignItems:'center',
                  gap:4,
                  padding:'3px 8px',
                  border:'1px solid #e5e7eb',
                  borderRadius:999,
                  background: current===w.symbol?'#eef2ff':'#fff',
                  fontSize:12,
                  lineHeight:1.05
                }}
              >
                <button
                  onClick={()=>setCurrent(w.symbol)}
                  style={{border:'none', background:'transparent', cursor:'pointer', padding:0, color:'#111827'}}
                >
                  {label}
                </button>
                <button
                  onClick={async ()=>{
                    const stockDisplayName = w.name && w.name.trim() ? w.name : w.symbol
                    showConfirm(
                      `确定要删除 ${stockDisplayName} 吗？`,
                      async () => {
                        setLoading(true)
                        try{
                          await jfetch(`/watchlist/${w.symbol}`, { method:'DELETE' })
                          await loadWatch()
                          if(current===w.symbol) setCurrent(undefined)
                          showToast(`${stockDisplayName} 已删除`, 'success')
                        }catch(e){
                          showToast('删除失败', 'error')
                        }finally{
                          setLoading(false)
                        }
                      },
                      '确认删除'
                    )
                  }}
                  title="删除自选"
                  style={{
                    border:'none',
                    background:'transparent',
                    color:'#dc2626',
                    cursor:'pointer',
                    padding:0,
                    fontSize:12,
                    lineHeight:1
                  }}
                >
                  ×
                </button>
              </div>
            )
          })}
          {watch.length > 10 && (
            <button onClick={() => setWatchDrawerOpen(true)} 
              style={{padding:'4px 12px', border:'1px solid #3b82f6', borderRadius:999, background:'#eff6ff', color:'#1d4ed8', fontSize:12, fontWeight:500, cursor:'pointer'}}>
              管理全部 {watch.length} 只 →
            </button>
          )}
        </div>
        {/* 利用下方空白：可放置一个紧凑信息条或后续扩展模块 */}
        {/* 汇总统计条 */}
        {watch.length > 0 && (
          <WatchlistSummary watch={watch} current={current} />
        )}
        {watch.length === 0 && (
          <div style={{marginTop:10, padding:'6px 10px', background:'#f8fafc', border:'1px dashed #e2e8f0', borderRadius:8, fontSize:11, color:'#64748b'}}>
            暂无自选股票，请先搜索添加。添加后这里将显示自选整体统计（数量、上涨/下跌、平均涨幅、主力净流入合计）。
          </div>
        )}

      </div>
      {/* 图表卡片紧跟自选，去除中间空白 */}
      <FloatingModule style={{marginTop:12, padding:12, borderRadius:12}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12}}>
          <div style={{fontWeight:600}}>价格走势 & 预测区间</div>
          
          {/* 时间区间选择器 */}
          <div style={{display:'flex', alignItems:'center', gap:8}}>
            <span style={{fontSize:12, color:'#6b7280'}}>时间区间:</span>
            <div style={{display:'flex', gap:4}}>
              {[
                {key: '5d', label: '5日'},
                {key: '1m', label: '1月'},
                {key: '3m', label: '3月'},
                {key: '6m', label: '6月'},
                {key: '1y', label: '1年'},
                {key: 'all', label: '全部'}
              ].map(option => (
                <button
                  key={option.key}
                  onClick={() => setTimeRange(option.key as any)}
                  style={{
                    padding: '4px 8px',
                    border: '1px solid #e5e7eb',
                    borderRadius: 4,
                    background: timeRange === option.key ? '#3b82f6' : '#fff',
                    color: timeRange === option.key ? '#fff' : '#374151',
                    cursor: 'pointer',
                    fontSize: 12,
                    fontWeight: timeRange === option.key ? '500' : '400'
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        
        {loading? <div>加载中…</div> :
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={merged} margin={{ top: 10, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={24} />
              <YAxis tick={{ fontSize: 12 }} domain={['auto','auto']} />
              <Tooltip />
              <Legend />
              <Line 
                type="monotone" 
                dataKey="close" 
                name="收盘" 
                dot={false} 
                strokeWidth={2} 
                stroke="#2563eb"
                connectNulls={false}
              />
              <Line 
                type="monotone" 
                dataKey="yhat" 
                name="预测均值" 
                dot={false} 
                strokeWidth={2} 
                stroke="#8884d8" 
                strokeDasharray="5 5"
                connectNulls={false}
              />
              <Area 
                type="monotone" 
                dataKey="yu" 
                name="预测上界" 
                dot={false} 
                strokeWidth={1} 
                fillOpacity={0.1} 
                stroke="#8884d8"
                fill="#8884d8"
                strokeDasharray="3 3"
                connectNulls={false}
              />
              <Area 
                type="monotone" 
                dataKey="yl" 
                name="预测下界" 
                dot={false} 
                strokeWidth={1} 
                fillOpacity={0.1} 
                stroke="#8884d8"
                fill="#8884d8"
                strokeDasharray="3 3"
                connectNulls={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        }
      </FloatingModule>

      {/* 数据详情表格（放在左侧列，避免右侧更高导致出现大块空白） */}
      <FloatingModule style={{marginTop:12, padding:12, borderRadius:12}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12}}>
          <div style={{fontWeight:600}}>数据详情</div>
          <div style={{fontSize:12, color:'#6b7280'}}>
            显示区间: {timeRange === '5d' ? '最近5个工作日' : timeRange === '1m' ? '最近1个月' : timeRange === '3m' ? '最近3个月' : timeRange === '6m' ? '最近6个月' : timeRange === '1y' ? '最近1年' : '全部数据'} + 未来预测
          </div>
        </div>
        
        {merged.length > 0 ? (
          <div style={{maxHeight: 300, overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: 8}}>
            <table style={{width: '100%', borderCollapse: 'collapse', fontSize: 12}}>
              <thead style={{background: '#f9fafb', position: 'sticky', top: 0}}>
                <tr>
                  <th style={{padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #e5e7eb'}}>日期</th>
                  <th style={{padding: '8px 12px', textAlign: 'right', borderBottom: '1px solid #e5e7eb'}}>实际收盘</th>
                  <th style={{padding: '8px 12px', textAlign: 'right', borderBottom: '1px solid #e5e7eb'}}>预测均值</th>
                  <th style={{padding: '8px 12px', textAlign: 'right', borderBottom: '1px solid #e5e7eb'}}>预测下界</th>
                  <th style={{padding: '8px 12px', textAlign: 'right', borderBottom: '1px solid #e5e7eb'}}>预测上界</th>
                  <th style={{padding: '8px 12px', textAlign: 'center', borderBottom: '1px solid #e5e7eb'}}>类型</th>
                </tr>
              </thead>
              <tbody>
                {merged.map((row, idx) => {
                  const isHistorical = row.close !== undefined
                  const isFuture = row.yhat !== undefined
                  return (
                    <tr key={idx} style={{background: isFuture ? '#f0f9ff' : '#fff'}}>
                      <td style={{padding: '6px 12px', borderBottom: '1px solid #f3f4f6'}}>{row.date}</td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid #f3f4f6'}}>
                        {isHistorical ? Number(row.close).toFixed(2) : '-'}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid #f3f4f6'}}>
                        {isFuture ? Number(row.yhat).toFixed(2) : '-'}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid #f3f4f6'}}>
                        {isFuture && row.yl ? Number(row.yl).toFixed(2) : '-'}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'right', borderBottom: '1px solid #f3f4f6'}}>
                        {isFuture && row.yu ? Number(row.yu).toFixed(2) : '-'}
                      </td>
                      <td style={{padding: '6px 12px', textAlign: 'center', borderBottom: '1px solid #f3f4f6'}}>
                        <span style={{
                          padding: '2px 6px',
                          borderRadius: 4,
                          fontSize: 10,
                          background: isHistorical ? '#e5e7eb' : '#dbeafe',
                          color: isHistorical ? '#374151' : '#1e40af'
                        }}>
                          {isHistorical ? '历史' : '预测'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{fontSize:12, color:'#6b7280', textAlign: 'center', padding: 20}}>
            暂无数据显示
          </div>
        )}
      </FloatingModule>

      <FloatingModule style={{marginTop:12, padding:12, borderRadius:12}}>
        <div style={{fontWeight:600, marginBottom:8}}>预测复盘</div>
        <div style={{fontSize:12, color:'#6b7280'}}>当目标日期已过去，系统将用实际收盘与当日预测均值比对，计算误差（如 MAPE）。</div>
      </FloatingModule>

      {/* 近1-2周数据分析与建议 */}
      <div className="card-panel watchlist-analysis-card" style={{marginTop:12}}>
        <style>
          {`
            .watchlist-analysis-card > div {
              border: none !important;
              padding: 0 !important;
              border-radius: 0 !important;
            }
          `}
        </style>
        <WatchlistAnalysis />
      </div>

      <div style={{fontSize:12, color:'#6b7280', marginTop:12}}>
        仅供学习研究，不构成投资建议。
      </div>
      </div>
      {/* 右侧：模型计划 + 个股数据报表 */}
      <div style={{flex:1, display:'flex', flexDirection:'column', gap:12}}>
        <FloatingModule style={{padding:12, borderRadius:12}}>
          <div style={{fontWeight:600, marginBottom:8}}>模型与计划</div>
          <div style={{fontSize:12, color:'#6b7280', marginBottom:6}}>
            📅 每日 16:10 Asia/Taipei 自动训练（由后端 APScheduler 执行）
          </div>
            <div style={{fontSize:12, color:'#6b7280', marginBottom:8}}>
            🎯 点击右上角按钮可手动拉数/训练/生成
          </div>
          <div style={{fontSize:11, color:'#9ca3af', background:'#f9fafb', padding:8, borderRadius:6}}>
            <div style={{fontWeight:500, marginBottom:4}}>当日训练流程：</div>
            <div>• 📊 抓取最新股价数据</div>
            <div>• 🔍 计算技术指标与信号</div>
            <div>• 🤖 SARIMAX + Ridge 预测建模</div>
            <div>• 📈 生成5天价格预测</div>
            <div>• 📝 更新分析报告</div>
          </div>
          <div style={{marginTop:12}}>
            <FundFlowPanel variant="content" />
          </div>
        </FloatingModule>
        <FloatingModule style={{padding:12, borderRadius:12}}>
          <div style={{fontWeight:600, marginBottom:8}}>个股数据报表</div>
          {report?.latest ? (
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
              <Metric label="收盘价" value={Number(report.latest.close).toFixed(2)} />
              <Metric label="涨跌幅(%)" value={(Number(report.latest.pct_chg)>=0?'+':'')+Number(report.latest.pct_chg).toFixed(2)} />
              <Metric label="短均线" value={report.signal? Number(report.signal.ma_short).toFixed(2): '-'} />
              <Metric label="长均线" value={report.signal? Number(report.signal.ma_long).toFixed(2): '-'} />
              <Metric label="RSI" value={report.signal? Number(report.signal.rsi).toFixed(1): '-'} />
              <Metric label="MACD" value={report.signal? Number(report.signal.macd).toFixed(4): '-'} />
              <Metric label="打分" value={report.signal? Number(report.signal.signal_score).toFixed(1): '-'} />
              <Metric label="建议" value={report.signal? report.signal.action : '-'} />
            </div>
          ) : <div style={{fontSize:12, color:'#6b7280'}}>尚无报告，请先添加并选择股票。</div>}
        </FloatingModule>
      </div>
    </div>

    {/* Toast 消息组件 */}
    <Toast
      isVisible={toast.isVisible}
      message={toast.message}
      type={toast.type}
      onClose={closeToast}
    />

    {/* 自定义弹窗组件 */}
    <CustomDialog
      isOpen={dialog.isOpen}
      onClose={closeDialog}
      title={dialog.title}
      message={dialog.message}
      type={dialog.type}
      onConfirm={dialog.onConfirm}
    />
    </div>
    ) : currentPage === 'dashboard' ? (
      <div style={{padding: 12}}>
        <Dashboard />
      </div>
    ) : currentPage === 'daily-analysis' ? (
      <div style={{padding: 12}}>
        <DailyAnalysisPage />
      </div>
    ) : currentPage === 'macro-report' ? (
      <div style={{padding: '0', background: 'transparent', border: 'none'}}>
        <MacroReportPage />
      </div>
    ) : currentPage === 'news-management' ? (
      <div style={{background: 'transparent', padding: 0, border: 'none'}}>
        <NewsManagement />
      </div>
    ) : currentPage === 'deep-insight' ? (
      <div style={{padding:0, background:'transparent', border:'none'}}>
        <DeepMarketInsight />
      </div>
    ) : currentPage === 'stocks-news' ? (
      <div style={{background: 'transparent', padding: 0, border: 'none'}}>
        {stocksDetailSymbol ? (
          <StockNewsDetail symbol={stocksDetailSymbol} onBack={() => setStocksDetailSymbol(null)} />
        ) : (
          <StocksNewsIndex onOpen={(sym) => setStocksDetailSymbol(sym)} />
        )}
      </div>
    ) : currentPage === 'query-templates' ? (
      <div style={{background: 'transparent', padding: 0, border: 'none'}}>
        <QueryTemplateManager />
      </div>
    ) : currentPage === 'profile-manager' ? (
      <div style={{background: 'transparent', padding: 0, border: 'none'}}>
        <ProfileValidationManager />
      </div>
    ) : (
      <div style={{background: 'transparent', padding: 0, border: 'none'}}>
        <ModernNewsComponent />
      </div>
    )}
      </div>

      {/* 自选管理 Drawer */}
      {isWatchDrawerOpen && (
      <div 
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(15, 23, 42, 0.4)',
          display: 'flex',
          justifyContent: 'flex-end',
          zIndex: 2000,
        }}
        onClick={() => setWatchDrawerOpen(false)}
      >
        <div 
          style={{
            width: 440,
            maxWidth: '90vw',
            height: '100vh',
            background: '#fff',
            boxShadow: '-4px 0 24px rgba(15,23,42,0.15)',
            padding: 24,
            display: 'flex',
            flexDirection: 'column',
          }}
          onClick={e => e.stopPropagation()}
        >
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16}}>
            <div style={{fontSize:18, fontWeight:600}}>自选管理 · {filteredWatch.length} 只</div>
            <button 
              onClick={() => setWatchDrawerOpen(false)}
              style={{fontSize:24, border:'none', background:'transparent', cursor:'pointer', color:'#6b7280', lineHeight:1}}
            >
              ×
            </button>
          </div>
          
          <input 
            value={watchSearch} 
            onChange={e => setWatchSearch(e.target.value)} 
            placeholder="搜索名称或代码"
            style={{
              width:'100%',
              padding:'10px 12px',
              border:'1px solid #e5e7eb',
              borderRadius:8,
              fontSize:14,
              marginBottom:16
            }}
          />
          
          <div style={{flex:1, minHeight:0}}>
            <VirtualList
              height={window.innerHeight - 180}
              width="100%"
              itemSize={48}
              itemCount={filteredWatch.length}
              overscanCount={10}
            >
              {({ index, style }) => {
                const w = filteredWatch[index]
                const label = w.name && w.name.trim() ? `${w.name} (${w.symbol})` : w.symbol
                const isActive = current === w.symbol
                return (
                  <div 
                    style={{
                      ...style,
                      display:'flex',
                      alignItems:'center',
                      justifyContent:'space-between',
                      padding:'0 12px',
                      borderBottom:'1px solid #f3f4f6',
                      background: isActive ? '#eff6ff' : 'transparent'
                    }}
                  >
                    <button 
                      onClick={() => {
                        setCurrent(w.symbol)
                        setWatchDrawerOpen(false)
                      }}
                      style={{
                        flex:1,
                        textAlign:'left',
                        border:'none',
                        background:'transparent',
                        padding:'8px 4px',
                        fontSize:13,
                        cursor:'pointer',
                        color: isActive ? '#1d4ed8' : '#374151',
                        fontWeight: isActive ? 600 : 400
                      }}
                    >
                      {label}
                    </button>
                    <button 
                      onClick={() => {
                        const stockDisplayName = w.name && w.name.trim() ? w.name : w.symbol
                        showConfirm(
                          `确定要删除 ${stockDisplayName} 吗？`,
                          async () => {
                            setLoading(true)
                            try{
                              await jfetch(`/watchlist/${w.symbol}`, {method:'DELETE'})
                              await loadWatch()
                              if(current===w.symbol) setCurrent(undefined)
                              showToast(`${stockDisplayName} 已删除`, 'success')
                            }catch(e:any){
                              showToast('删除失败', 'error')
                            }finally{
                              setLoading(false)
                            }
                          },
                          '确认删除'
                        )
                      }}
                      style={{
                        padding:'4px 10px',
                        border:'1px solid #fecaca',
                        borderRadius:6,
                        background:'#fef2f2',
                        color:'#dc2626',
                        fontSize:11,
                        cursor:'pointer',
                        fontWeight:500
                      }}
                    >
                      删除
                    </button>
                  </div>
                )
              }}
            </VirtualList>
          </div>
        </div>
      </div>
      )}
    </div>
  )
}
