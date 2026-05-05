import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { API_ENDPOINTS, buildApiUrl } from '../config/api'
import HelpTooltip from './components/HelpTooltip'
import { helpTips } from '../config/helpTips'

const SNAPSHOT_LIMIT = 200
const STREAM_BATCH = 20

/** AI signal data per symbol from quant engine */
type AISignalMap = Record<string, {
  action?: string | null
  score?: number | null
  risk_score?: number | null
  direction_prob_up?: number | null
  predicted_return?: number | null
  confidence?: number | null
  signal_date?: string | null
}>

const AI_ACTION_BADGE: Record<string, { text: string; bg: string; fg: string }> = {
  strong_buy:  { text: '强买', bg: 'var(--action-buy-bg)', fg: 'var(--action-buy-fg)' },
  buy:         { text: '买入', bg: 'var(--action-buy-bg)', fg: 'var(--action-buy-fg)' },
  hold:        { text: '观望', bg: 'var(--action-hold-bg)', fg: 'var(--action-hold-fg)' },
  sell:        { text: '卖出', bg: 'var(--action-sell-bg)', fg: 'var(--action-sell-fg)' },
  strong_sell: { text: '强卖', bg: 'var(--action-sell-bg)', fg: 'var(--action-sell-fg)' },
}

type OpportunityMode = 'ai' | 'flow' | 'risk'

const OPPORTUNITY_MODES: Array<{ id: OpportunityMode; label: string; hint: string }> = [
  { id: 'ai', label: 'AI关注', hint: 'AI 信号、预测收益、上涨概率优先' },
  { id: 'flow', label: '资金异动', hint: '主力净流入、量比、涨跌幅异动优先' },
  { id: 'risk', label: '风险预警', hint: '高风险分、下行概率和负向波动优先' },
]

type WatchlistSnapshotProps = {
  variant?: 'card' | 'content'
  onReadyRefresh?: (refresh: () => void) => void
  pinnedOnly?: boolean
  activeSymbol?: string
  onSelectSymbol?: (symbol: string) => void
}

export default function WatchlistSnapshot({ variant = 'card', onReadyRefresh, pinnedOnly = false, activeSymbol, onSelectSymbol }: WatchlistSnapshotProps){
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string|undefined>()
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [progress, setProgress] = useState<{loaded:number; total:number}|null>(null)
  const [aiSignals, setAiSignals] = useState<AISignalMap>({})
  const [showFullTable, setShowFullTable] = useState(false)
  const [opportunityMode, setOpportunityMode] = useState<OpportunityMode>('ai')
  const abortRef = useRef<AbortController|null>(null)

  const toNum = (value: any): number | null => {
    if (value === null || value === undefined || value === '') return null
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }

  const fmtPct = (value: any, digits = 2) => {
    const n = toNum(value)
    if (n == null) return '-'
    return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
  }

  const pctColor = (value: any) => {
    const n = toNum(value)
    if (n == null) return 'var(--text-muted)'
    return n > 0 ? 'var(--accent-lime)' : n < 0 ? 'var(--accent-red)' : 'var(--text-muted)'
  }

  const actionScore = (action?: string | null) => {
    switch (action) {
      case 'strong_buy': return 5
      case 'buy': return 4
      case 'hold': return 3
      case 'sell': return 2
      case 'strong_sell': return 1
      default: return 0
    }
  }

  const sellRiskScore = (action?: string | null) => {
    switch (action) {
      case 'strong_sell': return 5
      case 'sell': return 4
      case 'hold': return 2
      default: return 0
    }
  }

  /** Load AI quant signals for a batch of symbols (non-blocking) */
  const loadAiSignals = useCallback(async (symbols: string[]) => {
    if (!symbols.length) return
    try {
      const url = buildApiUrl(`/api/quant/signals/ranked?limit=${symbols.length}`)
      const resp = await fetch(url)
      if (!resp.ok) return
      const data = await resp.json()
      const items: any[] = Array.isArray(data) ? data : data.items || data.stocks || []
      const map: AISignalMap = {}
      for (const item of items) {
        const sym = item.symbol
        if (sym && symbols.includes(sym)) {
          map[sym] = {
            action: item.action,
            score: item.score,
            risk_score: item.risk_score,
            direction_prob_up: item.direction_prob_up,
            predicted_return: item.predicted_return,
            confidence: item.confidence,
            signal_date: item.signal_date,
          }
        }
      }
      setAiSignals(map)
    } catch { /* non-critical, silently ignore */ }
  }, [])

  const fmtWanYi = (v: any) => {
    if (v === null || v === undefined) return '-'
    const n = Number(v)
    if (!isFinite(n)) return '-'
    const wan = n / 1e4
    if (Math.abs(wan) >= 10000) return (wan/10000).toFixed(1) + '亿'
    return wan.toFixed(1) + '万'
  }

  const load = useCallback(async () => {
    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort()
    const ac = new AbortController()
    abortRef.current = ac

    try {
      setLoading(true); setError(undefined); setProgress(null)

      // ---- Try NDJSON streaming endpoint first ----
      const streamUrl = `${buildApiUrl(API_ENDPOINTS.WATCHLIST_API.SNAPSHOT_STREAM)}?limit=${SNAPSHOT_LIMIT}&batch_size=${STREAM_BATCH}${pinnedOnly ? '&pinned_only=true' : ''}`
      const resp = await fetch(streamUrl, { signal: ac.signal })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      if (!resp.body) throw new Error('ReadableStream not supported')

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let allRows: any[] = []

      const processChunk = (chunk: any) => {
        if (chunk.error) { setError(chunk.error); return }
        // Update progress from any chunk (including meta chunk with rows=[])
        if (chunk.total != null) {
          setProgress({ loaded: chunk.progress ?? allRows.length, total: chunk.total })
        }
        if (Array.isArray(chunk.rows) && chunk.rows.length > 0) {
          allRows = [...allRows, ...chunk.rows]
          setRows([...allRows])
        }
      }

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''
        for (const line of lines) {
          if (!line.trim()) continue
          try { processChunk(JSON.parse(line)) } catch { /* skip malformed line */ }
        }
      }
      // Remaining buffer
      if (buf.trim()) {
        try { processChunk(JSON.parse(buf)) } catch { /* skip */ }
      }

      setLastUpdated(new Date().toLocaleTimeString('zh-CN'))
      ;(window as any).__watchlistSnapshotRows = allRows
      // Fetch AI signal overlay for loaded symbols (fire-and-forget)
      loadAiSignals(allRows.map((r: any) => r.symbol).filter(Boolean))
    } catch (e: any) {
      if (e.name === 'AbortError') return
      // ---- Fallback to regular endpoint ----
      try {
        const url = `${buildApiUrl(API_ENDPOINTS.WATCHLIST_API.SNAPSHOT)}?limit=${SNAPSHOT_LIMIT}${pinnedOnly ? '&pinned_only=true' : ''}`
        const r = await fetch(url, { signal: ac.signal })
        if (!r.ok) throw new Error(await r.text())
        const data = await r.json()
        const rd = Array.isArray(data.rows) ? data.rows : []
        setRows(rd)
        setLastUpdated(new Date().toLocaleTimeString('zh-CN'))
        ;(window as any).__watchlistSnapshotRows = rd
        loadAiSignals(rd.map((r: any) => r.symbol).filter(Boolean))
      } catch (fe: any) {
        if (fe.name !== 'AbortError') setError(String(fe?.message || fe))
      }
    } finally {
      setLoading(false); setProgress(null)
    }
  }, [pinnedOnly])

  useEffect(() => {
    load()
    const t = setInterval(load, 60 * 1000)
    return () => { clearInterval(t); abortRef.current?.abort() }
  }, [load])

  const onReadyRefreshRef = useRef(onReadyRefresh)
  onReadyRefreshRef.current = onReadyRefresh

  useEffect(() => {
    onReadyRefreshRef.current?.(() => { void load() })
  }, [load])

  const opportunityRows = useMemo(() => {
    return rows
      .map((row: any) => {
        const ai = aiSignals[row.symbol] || {}
        const score = toNum(ai.score)
        const predictedReturn = toNum(ai.predicted_return)
        const directionProbUp = toNum(ai.direction_prob_up)
        const riskScore = toNum(ai.risk_score)
        const pctChange = toNum(row.pct_change)
        const mainNet = toNum(row.main_net)
        const volumeRatio = toNum(row.volume_ratio)
        const flowStrength = mainNet == null ? 0 : Math.min(Math.abs(mainNet) / 1e7, 80)
        const pctAbs = pctChange == null ? 0 : Math.min(Math.abs(pctChange), 12)
        let priority = 0

        if (opportunityMode === 'flow') {
          priority = flowStrength * 10
            + (mainNet != null && mainNet > 0 ? 80 : 0)
            + (volumeRatio ?? 0) * 12
            + pctAbs * 8
            + actionScore(ai.action) * 60
        } else if (opportunityMode === 'risk') {
          priority = (riskScore ?? 0) * 10
            + sellRiskScore(ai.action) * 120
            + (directionProbUp != null ? (1 - directionProbUp) * 120 : 0)
            + (predictedReturn != null && predictedReturn < 0 ? Math.abs(predictedReturn) * 35 : 0)
            + (pctChange != null && pctChange < 0 ? Math.abs(pctChange) * 10 : 0)
        } else {
          priority = actionScore(ai.action) * 1000
            + (score ?? 0) * 6
            + (predictedReturn ?? 0) * 30
            + (directionProbUp != null ? directionProbUp * 100 : 0)
            + (mainNet != null && mainNet > 0 ? Math.min(mainNet / 1e7, 25) : 0)
            + (pctChange ?? 0)
            - (riskScore ?? 0) * 1.8
        }

        return { row, ai, priority, score, predictedReturn, directionProbUp, riskScore, pctChange, mainNet, volumeRatio }
      })
      .sort((a, b) => b.priority - a.priority)
      .slice(0, 5)
  }, [rows, aiSignals, opportunityMode])

  const OpportunityQueue = () => {
    if (!rows.length && (loading || progress)) {
      return (
        <div style={{border:'1px solid var(--border)', borderRadius:8, padding:12, color:'var(--text-muted)', fontSize:12, marginBottom:10}}>
          正在加载自选机会队列{progress ? ` ${progress.loaded}/${progress.total}` : ''}...
        </div>
      )
    }

    if (!opportunityRows.length) return null

    const activeCount = rows.length
    const risingCount = rows.filter((row: any) => toNum(row.pct_change) != null && Number(row.pct_change) > 0).length
    const buySignalCount = rows.filter((row: any) => ['strong_buy', 'buy'].includes(String(aiSignals[row.symbol]?.action || ''))).length
    const highRiskCount = rows.filter((row: any) => {
      const ai = aiSignals[row.symbol]
      return toNum(ai?.risk_score) != null && Number(ai?.risk_score) >= 70
    }).length
    const currentMode = OPPORTUNITY_MODES.find(item => item.id === opportunityMode) || OPPORTUNITY_MODES[0]

    return (
      <div style={{border:'1px solid var(--border)', borderRadius:8, background:'rgba(255,255,255,0.018)', padding:10, marginBottom:10}}>
        <div style={{display:'flex', justifyContent:'space-between', gap:10, alignItems:'center', marginBottom:8}}>
          <div>
            <div style={{fontSize:13, fontWeight:700, color:'var(--text)'}}>机会队列</div>
            <div style={{fontSize:11, color:'var(--text-muted)', marginTop:2}}>{currentMode.hint}，仅作辅助观察</div>
          </div>
          <div style={{display:'flex', gap:6, flexWrap:'wrap', justifyContent:'flex-end'}}>
            <span style={{fontSize:10, color:'var(--text-muted)', border:'1px solid var(--border)', borderRadius:4, padding:'2px 6px'}}>自选 {activeCount}</span>
            <span style={{fontSize:10, color:'var(--accent-lime)', border:'1px solid rgba(110,231,183,0.25)', borderRadius:4, padding:'2px 6px'}}>上涨 {risingCount}</span>
            <span style={{fontSize:10, color:'var(--primary)', border:'1px solid var(--primary-border)', borderRadius:4, padding:'2px 6px'}}>AI关注 {buySignalCount}</span>
            <span style={{fontSize:10, color:'#f59e0b', border:'1px solid rgba(245,158,11,0.25)', borderRadius:4, padding:'2px 6px'}}>风险 {highRiskCount}</span>
          </div>
        </div>
        <div role="tablist" aria-label="机会队列排序视角" style={{display:'flex', gap:6, flexWrap:'wrap', marginBottom:8}}>
          {OPPORTUNITY_MODES.map(item => {
            const active = opportunityMode === item.id
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setOpportunityMode(item.id)}
                style={{
                  border:`1px solid ${active ? 'var(--primary)' : 'var(--border)'}`,
                  borderRadius:6,
                  background:active ? 'rgba(17,101,116,0.18)' : 'rgba(255,255,255,0.02)',
                  color:active ? 'var(--text)' : 'var(--text-muted)',
                  padding:'4px 8px',
                  fontSize:11,
                  fontWeight:700,
                  cursor:'pointer',
                }}
              >
                {item.label}
              </button>
            )
          })}
        </div>
        {opportunityMode === 'risk' && (
          <div style={{fontSize:10, color:'#f59e0b', lineHeight:1.45, marginBottom:8}}>
            风险预警用于提示需要复核的异常，不代表卖出建议或自动交易信号。
          </div>
        )}
        <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:8}}>
          {opportunityRows.map(({ row, ai, score, predictedReturn, directionProbUp, riskScore, pctChange, mainNet, volumeRatio }) => {
            const aiBadge = ai?.action ? AI_ACTION_BADGE[ai.action] : null
            const selected = activeSymbol === row.symbol
            const riskColor = riskScore == null ? 'var(--text-muted)' : riskScore >= 70 ? '#ef4444' : riskScore >= 45 ? '#f59e0b' : '#10b981'
            return (
              <button
                key={row.symbol}
                type="button"
                onClick={() => onSelectSymbol?.(row.symbol)}
                style={{
                  textAlign:'left',
                  border:`1px solid ${selected ? 'var(--primary)' : 'var(--border)'}`,
                  borderRadius:8,
                  background:selected ? 'rgba(17,101,116,0.16)' : 'rgba(255,255,255,0.02)',
                  padding:10,
                  cursor:onSelectSymbol ? 'pointer' : 'default',
                  color:'var(--text)',
                  display:'flex',
                  flexDirection:'column',
                  gap:8,
                  minHeight:118,
                }}
              >
                <span style={{display:'flex', justifyContent:'space-between', gap:8, alignItems:'flex-start'}}>
                  <span style={{minWidth:0}}>
                    <span style={{display:'block', fontSize:13, fontWeight:700, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{row.name || row.symbol}</span>
                    <span style={{display:'block', fontSize:10, color:'var(--text-muted)', marginTop:2}}>{row.symbol}</span>
                  </span>
                  {aiBadge ? (
                    <span style={{fontSize:10, fontWeight:700, padding:'2px 6px', borderRadius:4, background:aiBadge.bg, color:aiBadge.fg, whiteSpace:'nowrap'}}>{aiBadge.text}</span>
                  ) : (
                    <span style={{fontSize:10, color:'var(--text-muted)', whiteSpace:'nowrap'}}>观察</span>
                  )}
                </span>
                <span style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap:6, fontSize:11}}>
                  <span><span style={{color:'var(--text-muted)'}}>涨幅 </span><span style={{color:pctColor(pctChange), fontWeight:700}}>{fmtPct(pctChange)}</span></span>
                  <span><span style={{color:'var(--text-muted)'}}>评分 </span><span style={{fontWeight:700}}>{score != null ? score.toFixed(0) : '-'}</span></span>
                  <span><span style={{color:'var(--text-muted)'}}>预测 </span><span style={{color:pctColor(predictedReturn), fontWeight:700}}>{fmtPct(predictedReturn)}</span></span>
                  <span><span style={{color:'var(--text-muted)'}}>概率 </span><span style={{fontWeight:700}}>{directionProbUp != null ? `${(directionProbUp * 100).toFixed(0)}%` : '-'}</span></span>
                  <span><span style={{color:'var(--text-muted)'}}>风险 </span><span style={{color:riskColor, fontWeight:700}}>{riskScore != null ? riskScore.toFixed(0) : '-'}</span></span>
                  <span><span style={{color:'var(--text-muted)'}}>主力 </span><span style={{color:mainNet != null && mainNet > 0 ? 'var(--accent-lime)' : mainNet != null && mainNet < 0 ? 'var(--accent-red)' : 'var(--text-muted)', fontWeight:700}}>{fmtWanYi(mainNet)}</span></span>
                  {opportunityMode === 'flow' && <span><span style={{color:'var(--text-muted)'}}>量比 </span><span style={{fontWeight:700}}>{volumeRatio != null ? volumeRatio.toFixed(2) : '-'}</span></span>}
                </span>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  const fullTableInDrawer = showFullTable && rows.length > 0 && !loading && !progress

  const content = (
    <>
      {!!error && (
        <div style={{fontSize:12, color:'var(--accent-red)', marginBottom:8}}>错误：{error}</div>
      )}
      <OpportunityQueue />
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', gap:8, marginBottom:6}}>
        <div style={{fontSize:11, color:'var(--text-muted)'}}>完整行情表已移入详情抽屉，首页保留机会队列和关键入口。</div>
        <button
          type="button"
          onClick={() => setShowFullTable(true)}
          className="dark-btn dark-btn-secondary"
          style={{padding:'4px 8px', fontSize:11, whiteSpace:'nowrap'}}
        >
          查看完整表
        </button>
      </div>
      {(showFullTable || rows.length === 0 || loading || progress) && <div
        role={fullTableInDrawer ? 'dialog' : undefined}
        aria-modal={fullTableInDrawer ? true : undefined}
        aria-label={fullTableInDrawer ? '完整自选行情表' : undefined}
        onClick={fullTableInDrawer ? () => setShowFullTable(false) : undefined}
        style={fullTableInDrawer ? {
          position:'fixed',
          inset:0,
          zIndex:10000,
          background:'rgba(0,0,0,0.55)',
          display:'flex',
          justifyContent:'flex-end',
        } : {position:'relative'}}
      >
        <div
          onClick={fullTableInDrawer ? (event) => event.stopPropagation() : undefined}
          style={fullTableInDrawer ? {
            width:'min(1180px, 92vw)',
            height:'100vh',
            background:'var(--background-dark)',
            borderLeft:'1px solid var(--border)',
            boxShadow:'-24px 0 60px rgba(0,0,0,0.35)',
            padding:18,
            display:'flex',
            flexDirection:'column',
            gap:12,
          } : undefined}
        >
        {fullTableInDrawer && (
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:12}}>
            <div>
              <div style={{fontSize:16, fontWeight:700, color:'var(--text)'}}>完整自选行情表</div>
              <div style={{fontSize:12, color:'var(--text-muted)', marginTop:4}}>横向核对全部行情字段；点击行仍可切换当前个股。</div>
            </div>
            <button
              type="button"
              onClick={() => setShowFullTable(false)}
              className="dark-btn dark-btn-secondary"
              style={{padding:'5px 10px', fontSize:12}}
            >
              关闭
            </button>
          </div>
        )}
        {/* Progress bar (replaces blocking overlay) */}
        {progress && progress.total > 0 && (
          <div style={{height:3, background:'var(--bg-tertiary, #333)', borderRadius:2, marginBottom:4, overflow:'hidden'}}>
            <div style={{
              height:'100%', background:'var(--accent-blue, #60a5fa)',
              width:`${(progress.loaded / progress.total) * 100}%`,
              transition:'width 0.3s ease', borderRadius:2,
            }}/>
          </div>
        )}
        <div className="table-wrapper" style={{maxHeight: fullTableInDrawer ? 'calc(100vh - 112px)' : 360, overflowY: 'auto', transition:'opacity 0.2s ease'}}>
          <table className="table-beauty" style={{fontSize:12}}>
            <thead>
              <tr>
                <th>名称(代码)</th>
                <th style={{textAlign:'center', minWidth:36}}>AI</th>
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
              {rows.length === 0 && !loading && !progress ? (
                <tr><td colSpan={24} className="empty-state">暂无数据</td></tr>
              ) : rows.length === 0 && (loading || progress) ? (
                <tr><td colSpan={24} className="empty-state" style={{color:'var(--text-muted)'}}>
                  {progress ? `加载中 ${progress.loaded}/${progress.total}...` : '加载中...'}
                </td></tr>
              ) : (
                rows.map((r:any)=>{
                  const name = r.name || r.symbol
                  const mcap = r.total_market_cap!=null ? (Number(r.total_market_cap)/1e8).toFixed(2) : '-'
                  const isActive = activeSymbol === r.symbol
                  const ai = aiSignals[r.symbol]
                  const aiBadge = ai?.action ? AI_ACTION_BADGE[ai.action] : null
                  // Anomaly highlight: high risk or extreme probability
                  const isAnomaly = ai && ((ai.risk_score != null && ai.risk_score > 70) || (ai.direction_prob_up != null && (ai.direction_prob_up > 0.8 || ai.direction_prob_up < 0.2)))
                  const rowStyle: React.CSSProperties = isActive
                    ? {background:'rgba(99, 102, 241, 0.18)', boxShadow:'inset 3px 0 0 var(--primary, #6366f1)'}
                    : isAnomaly
                    ? {background:'rgba(251, 191, 36, 0.08)', boxShadow:'inset 3px 0 0 #f59e0b'}
                    : {}
                  return (
                    <tr key={r.symbol} style={rowStyle} onClick={() => onSelectSymbol?.(r.symbol)}>
                      <td>{name} ({r.symbol})</td>
                      <td style={{textAlign:'center'}}>
                        {aiBadge ? (
                          <HelpTooltip {...helpTips.compositeScore} content={`AI评分:${ai?.score?.toFixed(0) ?? '-'}，上涨概率:${ai?.direction_prob_up != null ? (ai.direction_prob_up*100).toFixed(0)+'%' : '-'}。该信号仅作排序和观察参考，不构成投资建议。`}>
                            <span style={{fontSize:10, fontWeight:600, padding:'1px 5px', borderRadius:3, background:aiBadge.bg, color:aiBadge.fg, whiteSpace:'nowrap', cursor:'help'}}>
                              {aiBadge.text}
                            </span>
                          </HelpTooltip>
                        ) : <span style={{fontSize:10,color:'var(--text-muted)'}}>-</span>}
                      </td>
                      <td style={{textAlign:'right'}}>{r.price!=null? Number(r.price).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.change!=null? Number(r.change).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right', color: r.pct_change>0?'var(--accent-lime)': r.pct_change<0?'var(--accent-red)':'var(--text)'}}>{r.pct_change!=null? Number(r.pct_change).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.speed!=null? Number(r.speed).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.since_watch_pct!=null? Number(r.since_watch_pct).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.chg_3d_pct!=null? Number(r.chg_3d_pct).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.chg_20d_pct!=null? Number(r.chg_20d_pct).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.chg_ytd_pct!=null? Number(r.chg_ytd_pct).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{fmtWanYi(r.main_net)}</td>
                      <td style={{textAlign:'right'}}>{r.amount!=null? (Number(r.amount)/1e4).toFixed(0) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.turnover_rate!=null? Number(r.turnover_rate).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.volume_ratio!=null? Number(r.volume_ratio).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.amplitude!=null? Number(r.amplitude).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.last_volume!=null? r.last_volume : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.high!=null? Number(r.high).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.low!=null? Number(r.low).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.open!=null? Number(r.open).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.pre_close!=null? Number(r.pre_close).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.order_ratio!=null? Number(r.order_ratio).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.pe_ttm!=null? Number(r.pe_ttm).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{r.pb!=null? Number(r.pb).toFixed(2) : '-'}</td>
                      <td style={{textAlign:'right'}}>{mcap}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
        </div>
      </div>}
      <div style={{fontSize:11, color:'var(--text-muted)', marginTop:6, textAlign:'right'}}>
        {progress ? `加载中 ${progress.loaded}/${progress.total}...` : `最多展示 ${SNAPSHOT_LIMIT} 只`} · 最近刷新 {lastUpdated ?? '—'}
      </div>
    </>
  )

  if (variant === 'content') return content

  return (
    <div className="card-panel">
      <div className="card-panel-header">
        <div>
          <div className="card-panel-title">自选实时看板（今日）</div>
          <div className="card-panel-subtitle">每分钟自动刷新，帮助你快速洞察自选股票表现</div>
        </div>
        <button onClick={load} className="dark-btn dark-btn-secondary" disabled={loading}>
          {loading ? (progress ? `${progress.loaded}/${progress.total}` : '刷新中...') : '刷新'}
        </button>
      </div>
      {content}
    </div>
  )
}
