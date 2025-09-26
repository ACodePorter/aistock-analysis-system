import React, { useEffect, useState } from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'

export default function WatchlistSnapshot(){
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string|undefined>()
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
      setLoading(true); setError(undefined)
      const r = await fetch(buildApiUrl(API_ENDPOINTS.WATCHLIST_API.SNAPSHOT))
      if(!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setRows(Array.isArray(data.rows) ? data.rows : [])
    }catch(e:any){ setError(String(e?.message||e)) }
    finally{ setLoading(false) }
  }

  useEffect(()=>{ load(); const t=setInterval(load, 60*1000); return ()=>clearInterval(t) }, [])

  return (
    <div style={{padding:12, border:'1px solid #e5e7eb', borderRadius:12}}>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8}}>
        <div style={{fontWeight:600}}>自选实时看板（今日）</div>
        <button onClick={load} style={{padding:'4px 8px', border:'1px solid #e5e7eb', borderRadius:6, background:'#fff'}}>刷新</button>
      </div>
      {!!error && (
        <div style={{fontSize:12, color:'#ef4444', marginBottom:8}}>错误：{error}</div>
      )}
      <div style={{position:'relative'}}>
        {loading && (
          <div style={{position:'absolute', inset:0, background:'rgba(255,255,255,0.65)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:12, color:'#6b7280', zIndex:1}}>
            刷新中...
          </div>
        )}
        <div style={{overflowX:'auto', opacity: loading ? 0.65 : 1, transition:'opacity 0.2s ease'}}>
          <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
            <thead style={{background:'#f9fafb'}}>
              <tr>
                <th style={{padding:'6px 8px', textAlign:'left'}}>名称(代码)</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>现价</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>涨跌</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>涨幅%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>涨速%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>自选以来%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>近3日%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>近20日%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>YTD%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>主力净流入（万/亿）</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>成交额(万)</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>换手率%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>量比</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>振幅%</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>现量</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>最高</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>最低</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>今开</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>昨收</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>委比</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>市盈率TTM</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>市净率</th>
                <th style={{padding:'6px 8px', textAlign:'right'}}>总市值(亿)</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={23} style={{padding:'18px', textAlign:'center', color:'#9ca3af', borderTop:'1px solid #f3f4f6'}}>暂无数据</td>
                </tr>
              ) : (
                rows.map((r:any)=>{
                  const name = r.name || r.symbol
                  const mcap = r.total_market_cap!=null ? (Number(r.total_market_cap)/1e8).toFixed(2) : '-'
                  return (
                    <tr key={r.symbol}>
                      <td style={{padding:'6px 8px', borderTop:'1px solid #f3f4f6'}}>{name} ({r.symbol})</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.price!=null? r.price.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.change!=null? r.change.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', color: r.pct_change>0?'#16a34a': r.pct_change<0?'#dc2626':'#374151', borderTop:'1px solid #f3f4f6'}}>{r.pct_change!=null? r.pct_change.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.speed!=null? Number(r.speed).toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.since_watch_pct!=null? r.since_watch_pct.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.chg_3d_pct!=null? r.chg_3d_pct.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.chg_20d_pct!=null? r.chg_20d_pct.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.chg_ytd_pct!=null? r.chg_ytd_pct.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{fmtWanYi(r.main_net)}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.amount!=null? (Number(r.amount)/1e4).toFixed(0) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.turnover_rate!=null? r.turnover_rate.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.volume_ratio!=null? r.volume_ratio.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.amplitude!=null? r.amplitude.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.last_volume!=null? r.last_volume : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.high!=null? r.high.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.low!=null? r.low.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.open!=null? r.open.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.pre_close!=null? r.pre_close.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.order_ratio!=null? r.order_ratio.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.pe_ttm!=null? r.pe_ttm.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{r.pb!=null? r.pb.toFixed(2) : '-'}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', borderTop:'1px solid #f3f4f6'}}>{mcap}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
