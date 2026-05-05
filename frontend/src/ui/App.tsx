import React, { useEffect, useMemo, useState } from 'react'
import { sliceByTimeRange } from './utils/rangeSlice'
import { mergePriceAndPredictions } from './utils/mergePriceAndPredictions'
import { Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ComposedChart, Legend } from 'recharts'
import Dashboard from './Dashboard'
import DarkLayout from './DarkLayout'
import DailyAnalysisPage from './DailyAnalysisPage'
import MacroReportPage from './MacroReportPage'
import ModernNewsComponent from './ModernNewsComponent'
import NewsManagement from './NewsManagement'
import QueryTemplateManager from './QueryTemplateManager'
import StocksNewsIndex from './StocksNewsIndex'
import StockNewsDetail from './StockNewsDetail'
import ProfileValidationManager from './ProfileValidationManager'
import AnalysisCenterPage from './AnalysisCenterPage'
import ModelCenterPage from './ModelCenterPage'
import NewsListPage from './NewsListPage'
import PipelineDiagnosticsDrawer from './PipelineDiagnosticsDrawer'
import AgentChatPage from './agent/AgentChatPage'
import AgentSkillManagementPage from './agent/AgentSkillManagementPage'
import AgentLogsPage from './agent/AgentLogsPage'
import HomeDecisionWorkspace from './home/HomeDecisionWorkspace'
import WatchlistManagerDrawer from './home/WatchlistManagerDrawer'
import { useHomeWatchlistControls } from './home/useHomeWatchlistControls'
import { fetchPredictionHistory, fetchStockInsight, type PredictionHistoryResponse, type StockInsightResponse } from '../api/report'
import { buildApiUrl } from '../config/api'

// MOVERS endpoints centralization removed; using API_ENDPOINTS.MOVERS now

async function jfetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = init?.headers ? { 'Content-Type': 'application/json', ...init.headers } : { 'Content-Type': 'application/json' }
  const r = await fetch(buildApiUrl(path), {
    ...init,
    headers,
  })
  if(!r.ok) throw new Error(await r.text())
  return r.json()
}

type PriceRow = { trade_date: string; close: number; open?: number; high?: number; low?: number; vol?: number }
type DialogType = 'alert' | 'confirm'
type ToastType = 'success' | 'error' | 'info'

type CustomDialogProps = Readonly<{
  isOpen: boolean
  onClose: () => void
  title?: string
  message: string
  type?: DialogType
  onConfirm?: () => void
}>

type ToastProps = Readonly<{
  isVisible: boolean
  message: string
  type?: ToastType
  onClose: () => void
}>

type LiveMoverRow = {
  symbol: string
  name?: string | null
  pct_chg?: number | null
  price?: number | null
}

type LiveInsightPayload = {
  provider?: string | null
  mock?: boolean
  universe_size?: number
  generated_at?: string
  gainers: LiveMoverRow[]
  losers: LiveMoverRow[]
}

type LiveSeriesPayload = {
  rows: Array<Record<string, unknown>>
}

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
    status?: string
    direction_snr?: number
    direction_grade?: 'strong' | 'moderate' | 'neutral'
    signal_level?: 'strong_bullish' | 'weak_bullish' | 'neutral' | 'weak_bearish' | 'strong_bearish'
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

function predictionHistoryLookbackDays(timeRange: string): number {
  switch (timeRange) {
    case '5d': return 30
    case '1m': return 60
    case '3m': return 120
    case '6m': return 210
    case '1y': return 365
    case 'all': return 365
    default: return 60
  }
}

// 自定义弹窗组件
function CustomDialog({ 
  isOpen, 
  onClose, 
  title, 
  message, 
  type = 'alert',
  onConfirm 
}: CustomDialogProps) {
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
        background: 'var(--surface-dark)',
        borderRadius: 12,
        padding: 24,
        minWidth: 320,
        maxWidth: 480,
        boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
        border: '1px solid var(--border)'
      }}>
        {title && (
          <div style={{
            fontWeight: 600,
            fontSize: 18,
            marginBottom: 16,
            color: type === 'confirm' ? 'var(--accent-red)' : 'var(--primary)'
          }}>
            {title}
          </div>
        )}
        
        <div style={{
          fontSize: 14,
          color: 'var(--text-muted)',
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
              className="dark-btn dark-btn-secondary"
              style={{ cursor: 'pointer' }}
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
}: ToastProps) {
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

// 深度行情页面（占位版）
function DeepMarketInsight(){
  const [live, setLive] = React.useState<LiveInsightPayload | null>(null)
  const [exchange, setExchange] = React.useState<string>('ALL')
  const [selectedSymbol, setSelectedSymbol] = React.useState<string|undefined>()
  const [series, setSeries] = React.useState<LiveSeriesPayload | null>(null)
  const [loadingSeries, setLoadingSeries] = React.useState(false)
  const [error, setError] = React.useState<string|undefined>()
  const [autoRefresh, setAutoRefresh] = React.useState<boolean>(true)
  const [refreshIntervalMs, setRefreshIntervalMs] = React.useState<number>(15000)
  const timerRef = React.useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchJSON = async <T,>(endpointOrFull:string): Promise<T> => {
    const url = endpointOrFull.startsWith('http') ? endpointOrFull : buildApiUrl(endpointOrFull)
    const r = await fetch(url)
    if(!r.ok) throw new Error(await r.text())
    return r.json() as Promise<T>
  }
  const loadLive = React.useCallback(()=>{
    fetchJSON<LiveInsightPayload>(`/api/movers/live_insight?exchange=${exchange}&limit=20`).then(d=>{
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
    fetchJSON<LiveSeriesPayload>(`/api/movers/live_series/${selectedSymbol}?days=60`).then(d=>{ setSeries(d); setLoadingSeries(false) }).catch(e=>{ setError(String(e)); setLoadingSeries(false) })
  },[selectedSymbol])

  const renderTable = (title:string, rows: LiveMoverRow[]) => (
    <div style={{flex:1, minWidth:0}}>
      <div style={{fontWeight:600, marginBottom:6, color:'var(--text)'}}>{title}</div>
      <div style={{border:'1px solid var(--border)', borderRadius:8, overflow:'hidden'}}>
        <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
          <thead style={{background:'rgba(255,255,255,0.03)'}}>
            <tr>
              <th style={{textAlign:'left', padding:'6px 8px', color:'var(--text-muted)'}}>代码</th>
              <th style={{textAlign:'left', padding:'6px 8px', color:'var(--text-muted)'}}>名称</th>
              <th style={{textAlign:'right', padding:'6px 8px', color:'var(--text-muted)'}}>涨跌幅%</th>
              <th style={{textAlign:'right', padding:'6px 8px', color:'var(--text-muted)'}}>价格</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r=> (
              <tr key={r.symbol}>
                <td style={{padding:'6px 8px', borderTop:'1px solid var(--border)', color:'var(--text)'}}>
                  <button
                    type="button"
                    onClick={() => setSelectedSymbol(r.symbol)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'inherit',
                      cursor: 'pointer',
                      font: 'inherit',
                      padding: 0,
                      textAlign: 'left'
                    }}
                  >
                    {r.symbol}
                  </button>
                </td>
                <td style={{padding:'6px 8px', borderTop:'1px solid var(--border)', color:'var(--text-muted)'}}>{r.name||'-'}</td>
                <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid var(--border)', color: (r.pct_chg ?? 0)>0?'var(--accent-lime)':'var(--accent-red)'}}>{r.pct_chg == null ? '-' : Number(r.pct_chg).toFixed(2)}</td>
                <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid var(--border)', color:'var(--text)'}}>{r.price == null ? '-' : Number(r.price).toFixed(2)}</td>
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
          <label htmlFor="deep-market-exchange" style={{fontSize:12, color:'#64748b'}}>交易所:</label>
          <select id="deep-market-exchange" value={exchange} onChange={e=> setExchange(e.target.value)} style={{fontSize:12, padding:'4px 6px'}}>
            <option value="ALL">全部 A 股</option>
            <option value="SH">上证 (SH)</option>
            <option value="SZ">深证 (SZ)</option>
          </select>
        </div>
        <button onClick={()=> loadLive()} className="dark-btn dark-btn-secondary" style={{padding:'4px 10px', fontSize:12, cursor:'pointer'}}>手动刷新</button>
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
        {live && <div style={{fontSize:12, marginTop:4, color:'var(--text-muted)', background:'rgba(255,255,255,0.02)', borderRadius:4, padding:'6px 10px', maxWidth:600, border:'1px dashed var(--border)'}}>
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
  const [currentPage, setCurrentPage] = useState<'main' | 'dashboard' | 'daily-analysis' | 'macro-report' | 'news' | 'news-management' | 'news-list' | 'deep-insight' | 'query-templates' | 'stocks-news' | 'profile-manager' | 'analysis-center' | 'strategy' | 'agent-chat' | 'agent-skills' | 'agent-logs'>('main')
  // Helper: allowed pages
  const validPages = new Set(['main','dashboard','daily-analysis','macro-report','news','news-management','news-list','deep-insight','query-templates','stocks-news','profile-manager','analysis-center','strategy','agent-chat','agent-skills','agent-logs'])

  const normalizeHash = (h: string) => h.replace(/^#\/?/, '')
  const pageFromHash = (h: string) => normalizeHash(h).split('?')[0]

  const navigateToPage = (p: string) => {
    if (!validPages.has(p)) return
    setCurrentPage(p as any)
    const target = `#${p}`
    if (globalThis.location.hash !== target) {
      try { globalThis.history.pushState({}, '', target) } catch { globalThis.location.hash = target }
    }
  }

  // Initialize from URL hash and keep in sync with browser navigation
  useEffect(() => {
    const init = pageFromHash(globalThis.location.hash)
    if (init && validPages.has(init)) {
      setCurrentPage(init as any)
    } else {
      // ensure URL reflects initial page
      const currentHash = pageFromHash(globalThis.location.hash)
      if (currentHash !== ('' + currentPage)) {
        try { globalThis.history.replaceState({}, '', `#${currentPage}`) } catch { globalThis.location.hash = `#${currentPage}` }
      }
    }

    const onHashChange = () => {
      const h = pageFromHash(globalThis.location.hash)
      if (h && validPages.has(h)) setCurrentPage(h as any)
    }
    globalThis.addEventListener('hashchange', onHashChange)
    return () => globalThis.removeEventListener('hashchange', onHashChange)
  }, [])
  const [stocksDetailSymbol, setStocksDetailSymbol] = useState<string | null>(null)
  const [current, setCurrent] = useState<string | undefined>(undefined)
  const [report, setReport] = useState<ReportResp | undefined>(undefined)
  const [insight, setInsight] = useState<StockInsightResponse | null>(null)
  const [insightLoading, setInsightLoading] = useState(false)
  const [predictionHistory, setPredictionHistory] = useState<PredictionHistoryResponse | null>(null)
  const [predictionHistoryLoading, setPredictionHistoryLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)
  const [watchlistSnapshotRefresh, setWatchlistSnapshotRefresh] = useState<(() => void) | null>(null)

  const [prices, setPrices] = useState<PriceRow[]>([])

  // 时间区间选择状态
  const [timeRange, setTimeRange] = useState<'5d' | '1m' | '3m' | '6m' | '1y' | 'all'>('5d')

  // 数据管道诊断抽屉状态
  const [pipelineDrawerSymbol, setPipelineDrawerSymbol] = useState<string | null>(null)

  // 自定义弹窗状态
  const [dialog, setDialog] = useState({
    isOpen: false,
    title: '',
    message: '',
    type: 'alert' as DialogType,
    onConfirm: undefined as (() => void) | undefined
  })

  // Toast 状态
  const [toast, setToast] = useState({
    isVisible: false,
    message: '',
    type: 'success' as ToastType
  })

  // 显示 Toast 消息
  const showToast = (message: string, type: ToastType = 'success') => {
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

  const {
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
  } = useHomeWatchlistControls({
    current,
    setCurrent,
    watchlistSnapshotRefresh,
    jfetch,
    showToast,
  })

  useEffect(()=>{
    if(!current) return

    const loadReport = async () => {
      try{
        setLoading(true)
        setError(undefined)
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
    }

    const loadInsight = async () => {
      try{
        setInsightLoading(true)
        const ins = await fetchStockInsight(current)
        setInsight(ins)
      }catch{
        setInsight(null)
      }finally{ setInsightLoading(false) }
    }

    const loadPredictionHistory = async () => {
      try{
        setPredictionHistoryLoading(true)
        const hist = await fetchPredictionHistory(current, {
          lookbackDays: predictionHistoryLookbackDays(timeRange),
        })
        setPredictionHistory(hist)
      }catch{
        setPredictionHistory(null)
      }finally{ setPredictionHistoryLoading(false) }
    }

    void loadReport()
    void loadInsight()
    void loadPredictionHistory()
  },[current, timeRange])

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
        try {
          const hist = await fetchPredictionHistory(current, {
            lookbackDays: predictionHistoryLookbackDays(timeRange),
          })
          setPredictionHistory(hist)
        } catch {
          setPredictionHistory(null)
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
  // 合并历史 + 预测的纯函数已抽离到 utils/mergePriceAndPredictions.ts 并配套单测，
  // 用于避免 "桥接行写入 yhat=close 导致 tooltip/legend 显示预测均值=收盘价" 的回归。
  const merged = useMemo(()=>{
    if (report?.price_data && report?.predictions) {
      const hist = sliceByTimeRange(report.price_data, timeRange)
      return mergePriceAndPredictions(hist as any, report.predictions as any, predictionHistory?.rows as any)
    }
    const m:any[] = []
    const filteredPrices = prices || []
    filteredPrices.forEach(p=>m.push({date:p.trade_date, close:p.close, type:'historical'}))
    report?.forecast?.forEach(f=>m.push({date:f.target_date, yhat:f.yhat, yl:f.yl, yu:f.yu, type:'prediction'}))
    return m.sort((a, b) => a.date.localeCompare(b.date))
  },[prices,report,timeRange,predictionHistory])

  const chartSeries = useMemo(() => ({
    hasHistoryD1: merged.some((row: any) => row.history_d1_yhat != null),
    hasHistoryD1Band: merged.some((row: any) => row.history_d1_yl != null && row.history_d1_yu != null),
    hasHistoryD5: merged.some((row: any) => row.history_d5_yhat != null),
    hasForecast: merged.some((row: any) => row.forecastMean != null),
    hasForecastBand: merged.some((row: any) => row.forecastLower != null && row.forecastUpper != null),
    hasExpiredForecast: merged.some((row: any) => row.forecastMeanExpired != null),
    hasExpiredForecastBand: merged.some((row: any) => row.forecastLowerExpired != null && row.forecastUpperExpired != null),
  }), [merged])

  // Map currentPage to DarkLayout navigation IDs
  const getNavPage = () => {
    switch (currentPage) {
      case 'main': return 'dashboard'
      case 'dashboard': return 'dashboard'
      case 'daily-analysis': return 'analysis'
      case 'deep-insight': return 'analysis'
      case 'analysis-center': return 'analysis'
      case 'macro-report': return 'daily'
      case 'news-management': return 'monitor'
      case 'news-list': return 'monitor'
      case 'stocks-news': return 'monitor'
      case 'query-templates': return 'settings'
      case 'profile-manager': return 'settings'
      case 'strategy': return 'strategy'
      case 'agent-chat': return 'agent-chat'
      case 'agent-skills': return 'agent-skills'
      case 'agent-logs': return 'agent-logs'
      default: return 'dashboard'
    }
  }

  const handleNavigate = (navId: string) => {
    switch (navId) {
      case 'dashboard': navigateToPage('main'); break
      case 'analysis': navigateToPage('analysis-center'); break
      case 'strategy': navigateToPage('strategy'); break
      case 'monitor': navigateToPage('stocks-news'); break
      case 'daily': navigateToPage('macro-report'); break
      case 'settings': navigateToPage('query-templates'); break
      case 'agent-chat': navigateToPage('agent-chat'); break
      case 'agent-skills': navigateToPage('agent-skills'); break
      case 'agent-logs': navigateToPage('agent-logs'); break
    }
  }

  const renderCurrentPage = () => {
    if (currentPage === 'main') {
      return (
        <HomeDecisionWorkspace
          current={current}
          watch={watch}
          watchlistSnapshotRefresh={watchlistSnapshotRefresh}
          name={name}
          searching={searching}
          error={error}
          searchResults={searchResults}
          showSearchModal={showSearchModal}
          timeRange={timeRange}
          predictionHistory={predictionHistory}
          predictionHistoryLoading={predictionHistoryLoading}
          loading={loading}
          merged={merged}
          chartSeries={chartSeries}
          insight={insight}
          insightLoading={insightLoading}
          report={report}
          jfetch={jfetch}
          loadWatch={loadWatch}
          runDaily={runDaily}
          setCurrent={setCurrent}
          setWatchlistSnapshotRefresh={setWatchlistSnapshotRefresh}
          setName={setName}
          setShowSearchModal={setShowSearchModal}
          setWatchDrawerOpen={setWatchDrawerOpen}
          setTimeRange={setTimeRange}
          setPipelineDrawerSymbol={setPipelineDrawerSymbol}
          setLoading={setLoading}
          handleSearchStocks={handleSearchStocks}
          handleStockSelect={handleStockSelect}
          showToast={showToast}
          showConfirm={showConfirm}
        />
      )
    }

    switch (currentPage) {
      case 'dashboard': return <Dashboard />
      case 'daily-analysis': return <DailyAnalysisPage />
      case 'analysis-center': return <AnalysisCenterPage />
      case 'strategy': return <ModelCenterPage initialSymbol={current} />
      case 'news-list': return <NewsListPage />
      case 'macro-report': return <MacroReportPage />
      case 'news-management': return <NewsManagement />
      case 'deep-insight': return <DeepMarketInsight />
      case 'stocks-news': return stocksDetailSymbol ? <StockNewsDetail symbol={stocksDetailSymbol} onBack={() => setStocksDetailSymbol(null)} /> : <StocksNewsIndex onOpen={(sym) => setStocksDetailSymbol(sym)} />
      case 'query-templates': return <QueryTemplateManager />
      case 'profile-manager': return <ProfileValidationManager />
      case 'agent-chat': return <AgentChatPage selectedStockCode={current} />
      case 'agent-skills': return <AgentSkillManagementPage />
      case 'agent-logs': return <AgentLogsPage />
      default: return <ModernNewsComponent />
    }
  }

  return (
    <DarkLayout 
      currentPage={getNavPage()} 
      onNavigate={handleNavigate}
      title="AI 股票监控"
      subtitle="A-Share Intelligence"
    >
      {renderCurrentPage()}

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

      <WatchlistManagerDrawer
        open={isWatchDrawerOpen}
        filteredWatch={filteredWatch}
        current={current}
        watchSearch={watchSearch}
        externalResults={externalResults}
        searchingExternal={searchingExternal}
        jfetch={jfetch}
        loadWatch={loadWatch}
        watchlistSnapshotRefresh={watchlistSnapshotRefresh}
        setCurrent={setCurrent}
        setWatchDrawerOpen={setWatchDrawerOpen}
        setWatchSearch={setWatchSearch}
        setExternalResults={setExternalResults}
        setLoading={setLoading}
        showToast={showToast}
        showConfirm={showConfirm}
      />
      <PipelineDiagnosticsDrawer
        symbol={pipelineDrawerSymbol}
        open={!!pipelineDrawerSymbol}
        onClose={() => setPipelineDrawerSymbol(null)}
      />
    </DarkLayout>
  )
}
