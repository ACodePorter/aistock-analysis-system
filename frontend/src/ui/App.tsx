
import React, { useEffect, useMemo, useState, useRef } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Area, ComposedChart, Legend } from 'recharts'
import Dashboard from './Dashboard'
import FundFlowPanel from './FundFlowPanel'
import WatchlistSnapshot from './WatchlistSnapshot'
import WatchlistAnalysis from './WatchlistAnalysis'
import ModernNewsComponent from './ModernNewsComponent'
import NewsManagement from './NewsManagement'
import { API_BASE, buildApiUrl } from '../config/api'

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

export default function App(){
  const [currentPage, setCurrentPage] = useState<'main' | 'dashboard' | 'news' | 'news-management'>('main')
  const [watch, setWatch] = useState<WatchItem[]>([])
  const [current, setCurrent] = useState<string | undefined>(undefined)
  const [report, setReport] = useState<ReportResp | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

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

  const merged = useMemo(()=>{
    const m:any[] = []
    
    // 使用新API的数据格式 - 后端已经根据timeRange参数返回了正确的数据
    if (report?.price_data && report?.predictions) {
      // 添加历史价格数据（后端已根据timeRange过滤）
      report.price_data.forEach(p => m.push({
        date: p.date, 
        close: p.close,
        type: 'historical'
      }))
      
      // 添加连接点：从历史最后一个点到预测三个点建立连接
      if (report.price_data.length > 0 && report.predictions.length > 0) {
        const lastHistorical = report.price_data[report.price_data.length - 1]
        const firstPrediction = report.predictions[0]
        
        // 添加历史数据最后一个点的扩展，包含预测数据的三个值
        m.push({
          date: lastHistorical.date,
          close: lastHistorical.close,
          yhat: lastHistorical.close, // 历史收盘价作为预测均值的起点
          yl: lastHistorical.close,   // 历史收盘价作为下界的起点
          yu: lastHistorical.close,   // 历史收盘价作为上界的起点
          type: 'historical_extended'
        })
        
        // 添加所有预测数据
        report.predictions.forEach(pred => m.push({
          date: pred.date,
          yhat: pred.predicted_price,
          yl: pred.lower_bound,
          yu: pred.upper_bound,
          type: 'prediction'
        }))
      }
    } else {
      // 保持向后兼容的旧格式
      const filteredPrices = prices || []
      filteredPrices.forEach(p=>m.push({date:p.trade_date, close:p.close}))
      report?.forecast?.forEach(f=>m.push({date:f.target_date, yhat:f.yhat, yl:f.yl, yu:f.yu}))
    }
    
    return m.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
  },[prices,report,timeRange])

  return <div style={{maxWidth:1180, margin:'20px auto', padding:'0 12px'}}>
    {/* 导航栏 */}
    <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12, borderBottom: '1px solid #e5e7eb', paddingBottom: 12}}>
      <div style={{display:'flex', alignItems:'center', gap:16}}>
        <h2 style={{margin:0}}>A 股 AI 助手</h2>
        <nav style={{display:'flex', gap:16}}>
          <button 
            onClick={() => setCurrentPage('main')}
            style={{
              padding:'8px 16px', 
              border:'none', 
              borderRadius:6, 
              background: currentPage === 'main' ? '#3b82f6' : 'transparent',
              color: currentPage === 'main' ? '#fff' : '#6b7280',
              cursor:'pointer',
              fontWeight: currentPage === 'main' ? '500' : 'normal'
            }}
          >
            股票分析
          </button>
          <button 
            onClick={() => setCurrentPage('dashboard')}
            style={{
              padding:'8px 16px', 
              border:'none', 
              borderRadius:6, 
              background: currentPage === 'dashboard' ? '#3b82f6' : 'transparent',
              color: currentPage === 'dashboard' ? '#fff' : '#6b7280',
              cursor:'pointer',
              fontWeight: currentPage === 'dashboard' ? '500' : 'normal'
            }}
          >
            任务监控
          </button>
          <button 
            onClick={() => setCurrentPage('news')}
            style={{
              padding:'8px 16px', 
              border:'none', 
              borderRadius:6, 
              background: currentPage === 'news' ? '#3b82f6' : 'transparent',
              color: currentPage === 'news' ? '#fff' : '#6b7280',
              cursor:'pointer',
              fontWeight: currentPage === 'news' ? '500' : 'normal'
            }}
          >
            财经新闻
          </button>
          <button 
            onClick={() => setCurrentPage('news-management')}
            style={{
              padding:'8px 16px', 
              border:'none', 
              borderRadius:6, 
              background: currentPage === 'news-management' ? '#3b82f6' : 'transparent',
              color: currentPage === 'news-management' ? '#fff' : '#6b7280',
              cursor:'pointer',
              fontWeight: currentPage === 'news-management' ? '500' : 'normal'
            }}
          >
            新闻管理
          </button>
        </nav>
      </div>
      <button 
        onClick={runDaily} 
        disabled={loading}
        style={{
          padding:'8px 12px', 
          border:'1px solid #e5e7eb', 
          borderRadius:8, 
          background: loading ? '#f3f4f6' : '#fff',
          color: loading ? '#9ca3af' : '#374151',
          cursor: loading ? 'not-allowed' : 'pointer',
          opacity: loading ? 0.6 : 1
        }}
      >
        {loading ? '执行中...' : '手动执行当日训练'}
      </button>
    </div>

    {/* 页面内容 */}
    {currentPage === 'main' ? (
    <div>
    <div style={{display:'grid', gridTemplateColumns:'2fr 1fr', gap:12}}>
      <div style={{padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>

        {/* 自选实时看板 */}
        <WatchlistSnapshot />

        <div style={{height:12}} />

        <div style={{display:'flex', gap:8, marginBottom:20, alignItems:'center'}}>
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
          <div style={{color:'#6b7280', fontSize:'12px', whiteSpace:'nowrap'}}>
            搜索后点击选择即可加入自选
          </div>
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
        <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
          {watch.map(w => (
            <div key={w.symbol} style={{display:'flex',alignItems:'center',gap:2}}>
              <button onClick={()=>setCurrent(w.symbol)}
                style={{padding:'6px 10px', border:'1px solid #e5e7eb', borderRadius:999, background: current===w.symbol?'#eef2ff':'#fff'}}>
                {w.name && w.name.trim() ? `${w.name}(${w.symbol})` : w.symbol}
              </button>
              <button onClick={()=>{
                const stockDisplayName = w.name && w.name.trim() ? w.name : w.symbol
                showConfirm(
                  `确定要删除 ${stockDisplayName} 吗？删除后需要重新添加。`,
                  async () => {
                    setLoading(true)
                    try{
                      await jfetch(`/watchlist/${w.symbol}`, {method:'DELETE'})
                      await loadWatch()
                      if(current===w.symbol) setCurrent(undefined)
                      showToast(`${stockDisplayName} 已从自选列表中删除`, 'success')
                    }catch(e:any){
                      setError(String(e?.message||e))
                      showToast('删除失败，请检查后端服务或网络连接', 'error')
                    }finally{
                      setLoading(false)
                    }
                  },
                  '确认删除'
                )
              }}
                style={{marginLeft:2,padding:'2px 6px',border:'1px solid #e5e7eb',borderRadius:6,background:'#fff',color:'#d32f2f',fontSize:12}}>删除</button>
            </div>
          ))}
        </div>
    {/* 保留空白区域，无提示 */}
      </div>

      <div style={{padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
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
          <FundFlowPanel />
        </div>
      </div>
    </div>

    <div style={{display:'grid', gridTemplateColumns:'2fr 1fr', gap:12, marginTop:12}}>
      <div style={{padding:12, height:420, border:'1px solid #e5e7eb', borderRadius:12}}>
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
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={merged} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
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
      </div>

      <div style={{padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
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
      </div>
    </div>

    {/* 数据详情表格 */}
    <div style={{marginTop:12, padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
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
    </div>

    <div style={{marginTop:12, padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
      <div style={{fontWeight:600, marginBottom:8}}>预测复盘</div>
      <div style={{fontSize:12, color:'#6b7280'}}>当目标日期已过去，系统将用实际收盘与当日预测均值比对，计算误差（如 MAPE）。</div>
    </div>

    {/* 近1-2周数据分析与建议 */}
    <div style={{marginTop:12}}>
      <WatchlistAnalysis />
    </div>

    <div style={{fontSize:12, color:'#6b7280', marginTop:12}}>
      仅供学习研究，不构成投资建议。
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
      <div style={{padding: '12px', border: '1px solid #e5e7eb', borderRadius: 12, background: '#fff'}}>
        <Dashboard />
      </div>
    ) : currentPage === 'news-management' ? (
      <div style={{background: 'transparent', padding: 0, border: 'none'}}>
        <NewsManagement />
      </div>
    ) : (
      <div style={{background: 'transparent', padding: 0, border: 'none'}}>
        <ModernNewsComponent />
      </div>
    )}
  </div>
}
