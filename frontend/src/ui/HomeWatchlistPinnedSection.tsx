import React from 'react'
import HelpTooltip from './components/HelpTooltip'
import { helpTips } from '../config/helpTips'

type WatchItem = {
  symbol: string
  name?: string
  sector?: string
  enabled?: boolean
  pinned?: boolean
}

type HomeWatchlistPinnedSectionProps = {
  watch: WatchItem[]
  current?: string
  onSelectSymbol: (symbol: string) => void
  onOpenManager: () => void
  onUnpin: (item: WatchItem) => Promise<void> | void
  onDelete: (item: WatchItem) => Promise<void> | void
}

function WatchlistSummary({ watch, current }: { watch: WatchItem[]; current?: string }) {
  const [stats, setStats] = React.useState({ up:0, down:0, flat:0, avgPct:0, totalNet:0 })

  React.useEffect(() => {
    const rows: any = (window as any).__watchlistSnapshotRows
    if (!Array.isArray(rows)) return
    if (rows.length === 0) {
      setStats({up:0, down:0, flat:0, avgPct:0, totalNet:0})
      return
    }

    let up = 0
    let down = 0
    let flat = 0
    let sum = 0
    let totalNet = 0
    rows.forEach((row: any) => {
      const pct = Number(row.pct_change)
      if (!isNaN(pct)) sum += pct
      if (pct > 0) up += 1
      else if (pct < 0) down += 1
      else flat += 1
      const mainNet = Number(row.main_net)
      if (!isNaN(mainNet)) totalNet += mainNet
    })
    setStats({up, down, flat, avgPct: sum / rows.length, totalNet})
  }, [watch, current])

  const pillStyle: React.CSSProperties = {
    padding:'4px 10px',
    background:'var(--surface-dark)',
    borderRadius:999,
    fontSize:11,
    display:'flex',
    alignItems:'center',
    gap:4,
    whiteSpace:'nowrap',
    border:'1px solid var(--border)',
    color:'var(--text-muted)',
  }

  return (
    <div style={{marginTop:10, display:'flex', flexWrap:'wrap', gap:6}}>
      <div style={pillStyle}>自选 {watch.length} 只</div>
      <div style={pillStyle}>↑ {stats.up}</div>
      <div style={pillStyle}>↓ {stats.down}</div>
      {stats.flat > 0 && <div style={pillStyle}>→ {stats.flat}</div>}
      <div style={pillStyle}>平均涨幅 {stats.avgPct.toFixed(2)}%</div>
      <div style={pillStyle}>主力净流入 {(stats.totalNet / 1e8).toFixed(2)} 亿</div>
    </div>
  )
}

export default function HomeWatchlistPinnedSection({
  watch,
  current,
  onSelectSymbol,
  onOpenManager,
  onUnpin,
  onDelete,
}: HomeWatchlistPinnedSectionProps) {
  const pinnedWatch = watch.filter(item => item.pinned)

  return (
    <>
      <div style={{display:'flex', gap:6, flexWrap:'wrap', marginTop:0, paddingTop:4, borderTop:'1px solid var(--border)', maxHeight:100, overflow:'hidden', alignItems:'center'}}>
        {pinnedWatch.slice(0, 10).map(item => {
          const label = item.name && item.name.trim() ? `${item.name}(${item.symbol})` : item.symbol
          const isActive = current === item.symbol
          return (
            <div
              key={item.symbol}
              style={{
                display:'flex',
                alignItems:'center',
                gap:4,
                padding:'3px 8px',
                border:'1px solid var(--border)',
                borderRadius:999,
                background: isActive ? 'rgba(99, 102, 241, 0.25)' : 'var(--surface-dark)',
                borderColor: isActive ? 'var(--primary, #6366f1)' : 'var(--border)',
                boxShadow: isActive ? '0 0 0 1px var(--primary, #6366f1)' : 'none',
                fontSize:12,
                lineHeight:1.05,
              }}
            >
              <button
                onClick={() => onSelectSymbol(item.symbol)}
                style={{border:'none', background:'transparent', cursor:'pointer', padding:0, color:'var(--text)'}}
              >
                {label}
              </button>
              <HelpTooltip {...helpTips.pinStock} content="取消置顶后，这只股票仍在股票池中，但不会优先显示在首页顶部。">
                <button
                  onClick={() => onUnpin(item)}
                  aria-label={`取消置顶 ${label}`}
                  style={{border:'none', background:'transparent', color:'#f59e0b', cursor:'pointer', padding:0, fontSize:13, lineHeight:1}}
                >
                  📌
                </button>
              </HelpTooltip>
              <HelpTooltip {...helpTips.deleteStock}>
                <button
                  onClick={() => onDelete(item)}
                  aria-label={`删除 ${label}`}
                  style={{border:'none', background:'transparent', color:'#dc2626', cursor:'pointer', padding:0, fontSize:12, lineHeight:1}}
                >
                  ×
                </button>
              </HelpTooltip>
            </div>
          )
        })}
        {pinnedWatch.length === 0 && watch.length > 0 && (
          <span style={{fontSize:11, color:'var(--text-muted)'}}>没有置顶股票，请在管理抽屉中点击 📌 置顶</span>
        )}
        {watch.length > 0 && (
          <HelpTooltip {...helpTips.manageStockPool}>
            <button
              onClick={onOpenManager}
              style={{padding:'4px 12px', border:'1px solid var(--primary-border)', borderRadius:999, background:'var(--primary-light)', color:'var(--text)', fontSize:12, fontWeight:500, cursor:'pointer'}}
            >
              管理全部 {watch.length} 只 →
            </button>
          </HelpTooltip>
        )}
      </div>

      {watch.length > 0 ? (
        <WatchlistSummary watch={watch} current={current} />
      ) : (
        <div style={{marginTop:10, padding:'6px 10px', background:'rgba(255,255,255,0.02)', border:'1px dashed var(--border)', borderRadius:8, fontSize:11, color:'var(--text-muted)'}}>
          暂无自选股票，请先搜索添加。添加后这里将显示自选整体统计（数量、上涨/下跌、平均涨幅、主力净流入合计）。
        </div>
      )}
    </>
  )
}