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

type FundFlowPanelProps = {
  variant?: 'card' | 'content'
}

export default function FundFlowPanel({ variant = 'card' }: FundFlowPanelProps){
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

  const body = (
    <>
      {loading ? (
        <div className="muted-text" style={{fontSize:13}}>加载中...</div>
      ) : error ? (
        <div style={{fontSize:13, color:'#ef4444'}}>加载失败：{error}</div>
      ) : rows.length === 0 ? (
        <div className="empty-state">暂无资金流向数据</div>
      ) : (
        <div className="section-grid two">
          <div style={{padding:18}}>
            <div className="card-panel-header" style={{marginBottom:12}}>
              <div className="card-panel-title" style={{fontSize:16}}>主力净流入 TOP5</div>
            </div>
            <div className="table-wrapper" style={{marginTop:6}}>
              <table className="table-beauty" style={{fontSize:12}}>
                <thead>
                  <tr>
                    <th>股票</th>
                    <th style={{textAlign:'right'}}>净额（万/亿）</th>
                    <th style={{textAlign:'right'}}>净占比(%)</th>
                  </tr>
                </thead>
                <tbody>
                  {topInflow.map((r)=> (
                    <tr key={`in-${r.symbol}`}>
                      <td>{r.symbol}</td>
                      <td style={{textAlign:'right'}}>{fmtWanYi(r.main_net)}</td>
                      <td style={{textAlign:'right'}}>{r.main_ratio!=null? r.main_ratio.toFixed(2) : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div style={{padding:18}}>
            <div className="card-panel-header" style={{marginBottom:12}}>
              <div className="card-panel-title" style={{fontSize:16}}>主力净流出 TOP5</div>
            </div>
            <div className="table-wrapper" style={{marginTop:6}}>
              <table className="table-beauty" style={{fontSize:12}}>
                <thead>
                  <tr>
                    <th>股票</th>
                    <th style={{textAlign:'right'}}>净额（万/亿）</th>
                    <th style={{textAlign:'right'}}>净占比(%)</th>
                  </tr>
                </thead>
                <tbody>
                  {topOutflow.map((r)=> (
                    <tr key={`out-${r.symbol}`}>
                      <td>{r.symbol}</td>
                      <td style={{textAlign:'right'}}>{fmtWanYi(r.main_net)}</td>
                      <td style={{textAlign:'right'}}>{r.main_ratio!=null? r.main_ratio.toFixed(2) : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  )

  if (variant === 'content') {
    return (
      <>
        <div style={{display:'flex', justifyContent:'flex-end', marginBottom:12}}>
          <div className="info-pill">{date ? `最新交易日：${date}` : '等待更新'}</div>
        </div>
        {body}
      </>
    )
  }

  return (
    <div className="card-panel">
      <div className="card-panel-header">
        <div>
          <div className="card-panel-title">大单资金流向榜</div>
          <div className="card-panel-subtitle">追踪主力资金动向，洞察市场资金侧重点</div>
        </div>
        <div className="info-pill">{date ? `最新交易日：${date}` : '等待更新'}</div>
      </div>
      {body}
    </div>
  )
}
