import React, { useEffect, useState } from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'

interface FundFlowRow {
  symbol: string
  trade_date: string
  main_net: number | null
  main_ratio: number | null
  super_net: number | null
  super_ratio: number | null
  large_net: number | null
  large_ratio: number | null
  medium_net: number | null
  medium_ratio: number | null
  small_net: number | null
  small_ratio: number | null
}

export default function FundFlowPanel(){
  const [rows, setRows] = useState<FundFlowRow[]>([])
  const [date, setDate] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Assume backend provides raw amount in 元; format to 万/亿 with 1 decimal
  const fmtWanYi = (v: any) => {
    if (v === null || v === undefined) return '-'
    const n = Number(v)
    if (!isFinite(n)) return '-'
    const wan = n / 1e4
    if (Math.abs(wan) >= 10000) return (wan/10000).toFixed(1) + '亿' // >= 1亿
    return wan.toFixed(1) + '万'
  }

  async function load(){
    try{
      setLoading(true); setError(null)
      const r = await fetch(buildApiUrl(API_ENDPOINTS.FUNDFLOW.LATEST))
      if(!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setRows(Array.isArray(data.rows) ? data.rows : [])
      setDate(data.date || null)
    }catch(e:any){
      setError(String(e?.message||e))
    }finally{
      setLoading(false)
    }
  }

  useEffect(()=>{ load(); const t = setInterval(load, 5*60*1000); return ()=>clearInterval(t) }, [])

  const topInflow = [...rows].sort((a,b)=> (b.main_net??0) - (a.main_net??0)).slice(0,5)
  const topOutflow = [...rows].sort((a,b)=> (a.main_net??0) - (b.main_net??0)).slice(0,5)

  return (
    <div style={{padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8}}>
        <div style={{fontWeight:600}}>大单资金流向榜</div>
        <div style={{fontSize:12, color:'#6b7280'}}>{date ? `最新交易日：${date}` : '暂无数据'}</div>
      </div>
      {loading ? (
        <div style={{fontSize:12, color:'#6b7280'}}>加载中...</div>
      ) : error ? (
        <div style={{fontSize:12, color:'#ef4444'}}>加载失败：{error}</div>
      ) : rows.length === 0 ? (
        <div style={{fontSize:12, color:'#6b7280'}}>暂无资金流向数据</div>
      ) : (
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
          <div>
            <div style={{fontWeight:600, marginBottom:6}}>主力净流入 TOP5</div>
            <div style={{border:'1px solid #e5e7eb', borderRadius:8, overflow:'hidden'}}>
              <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
                <thead style={{background:'#f9fafb'}}>
                  <tr>
                    <th style={{padding:'6px 8px', textAlign:'left'}}>股票</th>
                    <th style={{padding:'6px 8px', textAlign:'right'}}>净额（万/亿）</th>
                    <th style={{padding:'6px 8px', textAlign:'right'}}>净占比(%)</th>
                  </tr>
                </thead>
                <tbody>
                  {topInflow.map((r)=> (
                    <tr key={`in-${r.symbol}`}>
                      <td style={{padding:'6px 8px', borderTop:'1px solid #f3f4f6'}}>{r.symbol}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{fmtWanYi(r.main_net)}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.main_ratio!=null? r.main_ratio.toFixed(2) : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <div style={{fontWeight:600, marginBottom:6}}>主力净流出 TOP5</div>
            <div style={{border:'1px solid #e5e7eb', borderRadius:8, overflow:'hidden'}}>
              <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
                <thead style={{background:'#f9fafb'}}>
                  <tr>
                    <th style={{padding:'6px 8px', textAlign:'left'}}>股票</th>
                    <th style={{padding:'6px 8px', textAlign:'right'}}>净额（万/亿）</th>
                    <th style={{padding:'6px 8px', textAlign:'right'}}>净占比(%)</th>
                  </tr>
                </thead>
                <tbody>
                  {topOutflow.map((r)=> (
                    <tr key={`out-${r.symbol}`}>
                      <td style={{padding:'6px 8px', borderTop:'1px solid #f3f4f6'}}>{r.symbol}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{fmtWanYi(r.main_net)}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.main_ratio!=null? r.main_ratio.toFixed(2) : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
