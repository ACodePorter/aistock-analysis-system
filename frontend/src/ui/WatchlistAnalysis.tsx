import React, { useEffect, useState } from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'

export default function WatchlistAnalysis(){
  const [items, setItems] = useState<any[]>([])
  const [days, setDays] = useState(10)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string|undefined>()

  async function load(){
    try{
      setLoading(true); setError(undefined)
      const r = await fetch(buildApiUrl(API_ENDPOINTS.WATCHLIST_API.ANALYSIS), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days })
      })
      if(!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setItems(Array.isArray(data.items) ? data.items : [])
    }catch(e:any){ setError(String(e?.message||e)) }
    finally{ setLoading(false) }
  }

  useEffect(()=>{ load() }, [days])

  return (
    <div style={{padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8}}>
        <div style={{fontWeight:600}}>近{days}日数据分析与建议</div>
        <div style={{display:'flex', gap:8, alignItems:'center'}}>
          <span style={{fontSize:12, color:'#6b7280'}}>区间:</span>
          <select value={days} onChange={e=>setDays(Number(e.target.value))} style={{padding:'4px 8px', border:'1px solid #e5e7eb', borderRadius:6}}>
            {[7,10,14].map(d=> <option key={d} value={d}>{d}日</option>)}
          </select>
          <button onClick={load} style={{padding:'4px 8px', border:'1px solid #e5e7eb', borderRadius:6, background:'#fff'}}>刷新</button>
        </div>
      </div>
      {loading? <div style={{fontSize:12, color:'#6b7280'}}>加载中...</div> : error? <div style={{fontSize:12, color:'#ef4444'}}>错误：{error}</div> : (
        <div style={{display:'grid', gridTemplateColumns:'1fr', gap:12}}>
          {items.map((it:any)=> (
            <div key={it.symbol} style={{border:'1px solid #e5e7eb', borderRadius:8}}>
              <div style={{padding:'8px 12px', background:'#f9fafb', display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                <div style={{fontWeight:600}}>{it.name || it.symbol} ({it.symbol})</div>
                {!it.enough_data && <div style={{fontSize:12, color:'#9ca3af'}}>数据不足</div>}
              </div>
              {it.enough_data && (
                <div style={{padding:'10px 12px', display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:8}}>
                  <Metric label="动量(RSI)" value={fmt(it.radar?.momentum)} />
                  <Metric label="趋势差(MA短-长)" value={fmt(it.radar?.trend)} />
                  <Metric label="波动率%" value={fmt(it.radar?.volatility)} />
                  <Metric label="MACD均值" value={fmt(it.radar?.macd)} />
                  <Metric label="区间收益%" value={fmt(it.radar?.recent_return)} />
                </div>
              )}
              <div style={{padding:'10px 12px', display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                <div>
                  <div style={{fontWeight:600, marginBottom:6}}>建议</div>
                  {it.advice && it.advice.length? it.advice.map((t:string,idx:number)=> <li key={idx} style={{fontSize:12}}>{t}</li>) : <div style={{fontSize:12, color:'#9ca3af'}}>暂无</div>}
                </div>
                <div>
                  <div style={{fontWeight:600, marginBottom:6}}>风险</div>
                  {it.risk && it.risk.length? it.risk.map((t:string,idx:number)=> <li key={idx} style={{fontSize:12}}>{t}</li>) : <div style={{fontSize:12, color:'#9ca3af'}}>暂无</div>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string|number|null|undefined }){
  return <div style={{padding:'8px 10px', border:'1px solid #e5e7eb', borderRadius:8}}>
    <div style={{fontSize:11, color:'#6b7280'}}>{label}</div>
    <div style={{fontSize:16, fontWeight:600}}>{value??'-'}</div>
  </div>
}

function fmt(v:any){
  if(v===null || v===undefined) return '-'
  if(typeof v === 'number'){
    const n = Number(v)
    if(!Number.isFinite(n)) return '-'
    return n.toFixed(2)
  }
  return String(v)
}
