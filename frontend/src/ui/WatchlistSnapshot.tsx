import React, { useCallback, useEffect, useState } from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'

const SNAPSHOT_LIMIT = 200

type WatchlistSnapshotProps = {
  variant?: 'card' | 'content'
  onReadyRefresh?: (refresh: () => void) => void
}

export default function WatchlistSnapshot({ variant = 'card', onReadyRefresh }: WatchlistSnapshotProps){
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string|undefined>()
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  // Assume backend provides raw amount in 元; format to 万/亿 with 1 decimal
  const fmtWanYi = (v: any) => {
    if (v === null || v === undefined) return '-'
    const n = Number(v)
    if (!isFinite(n)) return '-'
    const wan = n / 1e4
    if (Math.abs(wan) >= 10000) return (wan/10000).toFixed(1) + '亿' // >= 1亿
    return wan.toFixed(1) + '万'
  }

  const load = useCallback(async () => {
    try{
      setLoading(true); setError(undefined)
      const url = `${buildApiUrl(API_ENDPOINTS.WATCHLIST_API.SNAPSHOT)}?limit=${SNAPSHOT_LIMIT}`
      const r = await fetch(url)
      if(!r.ok) throw new Error(await r.text())
      const data = await r.json()
      const rowsData = Array.isArray(data.rows) ? data.rows : []
      setRows(rowsData)
      setLastUpdated(new Date().toLocaleTimeString('zh-CN'))
      ;(window as any).__watchlistSnapshotRows = rowsData
    }catch(e:any){ setError(String(e?.message||e)) }
    finally{ setLoading(false) }
  }, [])

  useEffect(() => {
    load();
    const t=setInterval(load, 60*1000);
    return ()=>clearInterval(t)
  }, [load])

  useEffect(() => {
    if (!onReadyRefresh) return
    onReadyRefresh(() => { void load() })
  }, [onReadyRefresh, load])

  const content = (
    <>
      {!!error && (
        <div style={{fontSize:12, color:'var(--accent-red)', marginBottom:8}}>错误：{error}</div>
      )}
      <div style={{position:'relative'}}>
        {loading && (
          <div style={{position:'absolute', inset:0, background:'rgba(0,0,0,0.65)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:12, color:'var(--text-muted)', zIndex:1}}>
            刷新中...
          </div>
        )}
        <div className="table-wrapper" style={{maxHeight: 360, overflowY: 'auto', opacity: loading ? 0.65 : 1, transition:'opacity 0.2s ease'}}>
          <table className="table-beauty" style={{fontSize:12}}>
            <thead>
              <tr>
                <th>名称(代码)</th>
                <th style={{textAlign:'right'}}>现价</th>
                <th style={{textAlign:'right'}}>涨跌</th>
                <th style={{textAlign:'right'}}>涨幅%</th>
                <th style={{textAlign:'right'}}>涨速%</th>
                <th style={{textAlign:'right'}}>自选以来%</th>
                <th style={{textAlign:'right'}}>近3日%</th>
                <th style={{textAlign:'right'}}>近20日%</th>
                <th style={{textAlign:'right'}}>YTD%</th>
                <th style={{textAlign:'right'}}>主力净流入（万/亿）</th>
                <th style={{textAlign:'right'}}>成交额(万)</th>
                <th style={{textAlign:'right'}}>换手率%</th>
                <th style={{textAlign:'right'}}>量比</th>
                <th style={{textAlign:'right'}}>振幅%</th>
                <th style={{textAlign:'right'}}>现量</th>
                <th style={{textAlign:'right'}}>最高</th>
                <th style={{textAlign:'right'}}>最低</th>
                <th style={{textAlign:'right'}}>今开</th>
                <th style={{textAlign:'right'}}>昨收</th>
                <th style={{textAlign:'right'}}>委比</th>
                <th style={{textAlign:'right'}}>市盈率TTM</th>
                <th style={{textAlign:'right'}}>市净率</th>
                <th style={{textAlign:'right'}}>总市值(亿)</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={23} className="empty-state">暂无数据</td>
                </tr>
              ) : (
                rows.map((r:any)=>{
                  const name = r.name || r.symbol
                  const mcap = r.total_market_cap!=null ? (Number(r.total_market_cap)/1e8).toFixed(2) : '-'
                  return (
                    <tr key={r.symbol}>
                      <td>{name} ({r.symbol})</td>
                      <td style={{textAlign:'right'}}>{r.price!=null? r.price.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.change!=null? r.change.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right', color: r.pct_change>0?'var(--accent-lime)': r.pct_change<0?'var(--accent-red)':'var(--text)'}}>{r.pct_change!=null? r.pct_change.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.speed!=null? Number(r.speed).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.since_watch_pct!=null? r.since_watch_pct.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.chg_3d_pct!=null? r.chg_3d_pct.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.chg_20d_pct!=null? r.chg_20d_pct.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.chg_ytd_pct!=null? r.chg_ytd_pct.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{fmtWanYi(r.main_net)}</td>
                      <td style={{textAlign:'right'}}>{r.amount!=null? (Number(r.amount)/1e4).toFixed(0) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.turnover_rate!=null? r.turnover_rate.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.volume_ratio!=null? r.volume_ratio.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.amplitude!=null? r.amplitude.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.last_volume!=null? r.last_volume : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.high!=null? r.high.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.low!=null? r.low.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.open!=null? r.open.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.pre_close!=null? r.pre_close.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.order_ratio!=null? r.order_ratio.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.pe_ttm!=null? r.pe_ttm.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.pb!=null? r.pb.toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{mcap}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div style={{fontSize:11, color:'var(--text-muted)', marginTop:6, textAlign:'right'}}>
        最多展示 {SNAPSHOT_LIMIT} 只 · 最近刷新 {lastUpdated ?? '—'}
      </div>
    </>
  )

  if (variant === 'content') {
    return content
  }

  return (
    <div className="card-panel">
      <div className="card-panel-header">
        <div>
          <div className="card-panel-title">自选实时看板（今日）</div>
          <div className="card-panel-subtitle">每分钟自动刷新，帮助你快速洞察自选股票表现</div>
        </div>
        <button onClick={load} className="dark-btn dark-btn-secondary">刷新</button>
      </div>
      {content}
    </div>
  )
}
