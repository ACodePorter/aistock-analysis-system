import React, { useEffect, useState } from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'

interface WatchlistAnalysisProps {
  pinnedOnly?: boolean
  symbols?: string[]
}

export default function WatchlistAnalysis({ pinnedOnly = true, symbols }: WatchlistAnalysisProps){
  const [items, setItems] = useState<any[]>([])
  const [days, setDays] = useState(10)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string|undefined>()

  async function load(){
    try{
      setLoading(true); setError(undefined)
      const body: any = { days, pinned_only: pinnedOnly }
      if (symbols && symbols.length) body.symbols = symbols
      const r = await fetch(buildApiUrl(API_ENDPOINTS.WATCHLIST_API.ANALYSIS), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      if(!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setItems(Array.isArray(data.items) ? data.items : [])
    }catch(e:any){ setError(String(e?.message||e)) }
    finally{ setLoading(false) }
  }

  useEffect(()=>{ load() }, [days, pinnedOnly, symbols?.join(',')])

  return (
    <div style={{padding:'10px 12px'}}>
      {/* 标题栏 */}
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:10}}>
        <div style={{fontSize:14, fontWeight:600, color:'var(--text)'}}>📊 近{days}日数据分析与建议</div>
        <div style={{display:'flex', gap:6, alignItems:'center'}}>
          <select value={days} onChange={e=>setDays(Number(e.target.value))} className="dark-select"
            style={{padding:'2px 6px', fontSize:12, borderRadius:4, background:'var(--surface-dark)', border:'1px solid var(--border)', color:'var(--text)'}}>
            {[7,10,14].map(d=> <option key={d} value={d}>{d}日</option>)}
          </select>
          <button onClick={load} className="dark-btn dark-btn-secondary"
            style={{padding:'2px 10px', fontSize:12, borderRadius:4, cursor:'pointer'}}>刷新</button>
        </div>
      </div>

      {loading ? (
        <div style={{fontSize:12, color:'var(--text-muted)', textAlign:'center', padding:16}}>加载中...</div>
      ) : error ? (
        <div style={{fontSize:12, color:'var(--accent-red)', padding:8}}>错误：{error}</div>
      ) : (
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          {items.map((it:any) => (
            <StockAnalysisCard key={it.symbol} item={it} />
          ))}
          {items.length === 0 && (
            <div style={{fontSize:12, color:'var(--text-muted)', textAlign:'center', padding:16}}>暂无置顶股票的分析数据</div>
          )}
        </div>
      )}
    </div>
  )
}

/* ─── 单个股票分析卡片 ─── */
function StockAnalysisCard({ item: it }: { item: any }) {
  if (!it.enough_data) {
    return (
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'6px 10px', borderRadius:6,
        background:'rgba(255,255,255,0.015)', border:'1px solid var(--border)',
      }}>
        <span style={{fontSize:13, fontWeight:500, color:'var(--text)'}}>{it.name||it.symbol} <span style={{fontSize:11, color:'var(--text-muted)'}}>({it.symbol})</span></span>
        <span style={{fontSize:11, color:'var(--text-muted)', fontStyle:'italic'}}>数据不足</span>
      </div>
    )
  }

  const r = it.radar || {}
  const metrics: { label: string; value: any; color?: string }[] = [
    { label: 'RSI', value: r.momentum, color: rsiColor(r.momentum) },
    { label: 'MA趋势', value: r.trend, color: trendColor(r.trend) },
    { label: '波动率', value: r.volatility },
    { label: 'MACD', value: r.macd, color: trendColor(r.macd) },
    { label: '收益%', value: r.recent_return, color: trendColor(r.recent_return) },
  ]

  return (
    <div style={{
      borderRadius:8, overflow:'hidden',
      border:'1px solid var(--border)', background:'var(--surface-dark)',
    }}>
      {/* 头部：股票名 + 指标行 */}
      <div style={{
        display:'flex', alignItems:'center', gap:12,
        padding:'7px 12px',
        background:'rgba(255,255,255,0.02)',
        borderBottom:'1px solid var(--border)',
      }}>
        {/* 股票名 */}
        <div style={{fontWeight:600, fontSize:13, color:'var(--text)', whiteSpace:'nowrap', minWidth:100}}>
          {it.name||it.symbol}
          <span style={{fontSize:11, color:'var(--text-muted)', fontWeight:400, marginLeft:4}}>({it.symbol})</span>
        </div>
        {/* 指标 */}
        <div style={{display:'flex', gap:2, flex:1, justifyContent:'flex-end', flexWrap:'wrap'}}>
          {metrics.map(m => (
            <div key={m.label} style={{
              display:'inline-flex', alignItems:'center', gap:3,
              padding:'2px 8px', borderRadius:4,
              background:'rgba(255,255,255,0.03)', fontSize:11,
            }}>
              <span style={{color:'var(--text-muted)'}}>{m.label}</span>
              <span style={{fontWeight:600, fontVariantNumeric:'tabular-nums', color: m.color || 'var(--text)'}}>
                {fmt(m.value)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 建议 + 风险 */}
      <div style={{display:'flex', padding:'6px 12px', gap:16, minHeight:28}}>
        {/* 建议 */}
        <div style={{flex:1, display:'flex', flexWrap:'wrap', gap:4, alignItems:'center'}}>
          <span style={{fontSize:11, color:'var(--text-muted)', marginRight:2}}>💡</span>
          {it.advice && it.advice.length ? it.advice.map((t:string, idx:number) => (
            <span key={idx} style={{
              fontSize:11, padding:'1px 6px', borderRadius:3,
              background:'rgba(59,130,246,0.1)', color:'#93c5fd',
            }}>{t}</span>
          )) : <span style={{fontSize:11, color:'var(--text-muted)'}}>暂无</span>}
        </div>
        {/* 风险 */}
        {it.risk && it.risk.length > 0 && (
          <div style={{display:'flex', flexWrap:'wrap', gap:4, alignItems:'center'}}>
            <span style={{fontSize:11, color:'var(--text-muted)', marginRight:2}}>⚠️</span>
            {it.risk.map((t:string, idx:number) => (
              <span key={idx} style={{
                fontSize:11, padding:'1px 6px', borderRadius:3,
                background:'rgba(239,68,68,0.1)', color:'#fca5a5',
              }}>{t}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ─── helpers ─── */
function fmt(v: any): string {
  if (v === null || v === undefined) return '-'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '-'
    return v.toFixed(2)
  }
  return String(v)
}

function rsiColor(v: any): string {
  if (v == null) return 'var(--text)'
  if (v > 70) return '#f87171'   // overbought red
  if (v > 60) return '#fb923c'   // warm
  if (v < 30) return '#34d399'   // oversold green
  if (v < 40) return '#60a5fa'   // cool
  return 'var(--text)'
}

function trendColor(v: any): string {
  if (v == null) return 'var(--text)'
  if (v > 0) return '#34d399'    // green
  if (v < 0) return '#f87171'    // red
  return 'var(--text)'
}
