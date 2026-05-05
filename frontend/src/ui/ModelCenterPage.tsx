import React from 'react'
import {
  fetchIterationRecords,
  fetchModelCenter,
  fetchStrategyBacktest,
  type IterationRecordsResponse,
  type ModelCenterResponse,
  type StrategyBacktestResponse,
} from '../api/modelCenter'

function tone(status?: string | null) {
  if (!status) return '#94a3b8'
  if (['passed', 'candidate_allowed', 'ready', 'active', 'optimized'].includes(status)) return '#10b981'
  if (['blocked', 'failed', 'high', 'risk'].includes(status)) return '#ef4444'
  return '#f59e0b'
}

function fmt(value: number | null | undefined, suffix = '') {
  return value == null || !Number.isFinite(Number(value)) ? '-' : `${Number(value).toFixed(2)}${suffix}`
}

function Pill({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <span style={{display:'inline-flex', gap:6, alignItems:'center', padding:'4px 8px', border:'1px solid var(--border)', borderRadius:6, background:'rgba(255,255,255,0.025)', fontSize:12}}>
      <span style={{color:'var(--text-muted)'}}>{label}</span>
      <span style={{fontWeight:700, color: color || 'var(--text)'}}>{value}</span>
    </span>
  )
}

export default function ModelCenterPage({ initialSymbol }: { initialSymbol?: string }) {
  const [symbol, setSymbol] = React.useState(initialSymbol || '')
  const [querySymbol, setQuerySymbol] = React.useState(initialSymbol || '')
  const [center, setCenter] = React.useState<ModelCenterResponse | null>(null)
  const [records, setRecords] = React.useState<IterationRecordsResponse | null>(null)
  const [backtest, setBacktest] = React.useState<StrategyBacktestResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async (target?: string) => {
    setLoading(true)
    setError(null)
    const normalized = target?.trim().toUpperCase() || undefined
    try {
      const data = await fetchModelCenter(normalized, 20)
      setCenter(data)
      const selected = normalized || data.items[0]?.symbol || ''
      if (selected) {
        setSymbol(selected)
        setQuerySymbol(selected)
        const [recordData, replayData] = await Promise.all([
          fetchIterationRecords(selected, 8).catch(() => null),
          fetchStrategyBacktest(selected, 120).catch(() => null),
        ])
        setRecords(recordData)
        setBacktest(replayData)
      } else {
        setRecords(null)
        setBacktest(null)
      }
    } catch (exc: any) {
      setError(String(exc?.message || exc))
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => { load(initialSymbol) }, [initialSymbol, load])

  const summary = center?.summary
  const gate = backtest?.gate_result
  const latestReview = records?.agent_reviews?.[0]
  const latestFailure = records?.failure_analyses?.[0]
  const latestSnapshot = records?.feature_snapshots?.[0]

  return (
    <div style={{padding:12, display:'flex', flexDirection:'column', gap:12}}>
      <div style={{display:'flex', justifyContent:'space-between', gap:12, alignItems:'center', flexWrap:'wrap'}}>
        <div>
          <div style={{fontSize:22, fontWeight:700, color:'var(--text)'}}>模型中心</div>
          <div style={{fontSize:12, color:'var(--text-muted)', marginTop:4}}>自动核实、回放记录、策略回测与晋级门禁</div>
        </div>
        <div style={{display:'flex', gap:8, alignItems:'center'}}>
          <input
            value={querySymbol}
            onChange={event => setQuerySymbol(event.target.value.toUpperCase())}
            onKeyDown={event => { if (event.key === 'Enter') load(querySymbol) }}
            placeholder="输入股票代码"
            style={{height:34, minWidth:160, border:'1px solid var(--border)', borderRadius:6, background:'var(--surface-dark)', color:'var(--text)', padding:'0 10px'}}
          />
          <button className="dark-btn dark-btn-secondary" onClick={() => load(querySymbol)} disabled={loading} style={{height:34, cursor:'pointer'}}>
            {loading ? '加载中' : '刷新'}
          </button>
        </div>
      </div>

      {error && <div style={{border:'1px solid rgba(239,68,68,0.35)', color:'#ef4444', borderRadius:8, padding:'8px 10px', background:'rgba(239,68,68,0.06)', fontSize:12}}>{error}</div>}

      <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
        <Pill label="迁移" value={center?.migration_status.agent_iteration_ready ? '已就绪' : '待执行'} color={center?.migration_status.agent_iteration_ready ? '#10b981' : '#f59e0b'} />
        <Pill label="QE 模型" value={summary?.qe_model_count ?? 0} />
        <Pill label="生命周期" value={summary?.recent_lifecycle_count ?? 0} />
        <Pill label="复盘记录" value={summary?.recent_review_count ?? 0} />
        <Pill label="快照" value={summary?.feature_snapshot_count ?? 0} />
      </div>

      <div style={{display:'grid', gridTemplateColumns:'minmax(0, 1.35fr) minmax(320px, 0.85fr)', gap:12, alignItems:'start'}}>
        <div style={{border:'1px solid var(--border)', borderRadius:8, overflow:'hidden', background:'rgba(255,255,255,0.018)'}}>
          <div style={{padding:'9px 10px', borderBottom:'1px solid var(--border)', display:'flex', justifyContent:'space-between', alignItems:'center'}}>
            <div style={{fontWeight:700, color:'var(--text)'}}>模型与门禁队列</div>
            <div style={{fontSize:11, color:'var(--text-muted)'}}>当前：{symbol || '-'}</div>
          </div>
          <div style={{overflowX:'auto'}}>
            <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
              <thead style={{background:'rgba(255,255,255,0.025)'}}>
                <tr>
                  {['代码','模型','版本','失败','核实','门禁','更新时间'].map(item => (
                    <th key={item} style={{padding:'8px 10px', textAlign:item === '代码' ? 'left' : 'center', color:'var(--text-muted)', whiteSpace:'nowrap'}}>{item}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(center?.items || []).map(item => (
                  <tr key={item.symbol} onClick={() => load(item.symbol)} style={{borderTop:'1px solid rgba(255,255,255,0.04)', cursor:'pointer', background:item.symbol === symbol ? 'rgba(99,102,241,0.12)' : 'transparent'}}>
                    <td style={{padding:'8px 10px', color:'var(--text)', fontWeight:700}}>{item.symbol}</td>
                    <td style={{padding:'8px 10px', textAlign:'center', color:'var(--text-muted)'}}>{item.algo || '-'}</td>
                    <td style={{padding:'8px 10px', textAlign:'center', color:'var(--text)'}}>{item.active_version ?? '-'}</td>
                    <td style={{padding:'8px 10px', textAlign:'center', color:tone(item.failure_severity)}}>{item.failure_severity || '-'}</td>
                    <td style={{padding:'8px 10px', textAlign:'center', color:tone(item.verification_status)}}>{item.verification_status || '-'}</td>
                    <td style={{padding:'8px 10px', textAlign:'center', color:tone(item.gate_status)}}>{item.gate_status || '-'}</td>
                    <td style={{padding:'8px 10px', textAlign:'center', color:'var(--text-muted)', whiteSpace:'nowrap'}}>{item.updated_at?.slice(0, 19).replace('T', ' ') || '-'}</td>
                  </tr>
                ))}
                {!center?.items?.length && (
                  <tr><td colSpan={7} style={{padding:18, textAlign:'center', color:'var(--text-muted)'}}>暂无模型中心记录</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div style={{display:'flex', flexDirection:'column', gap:12}}>
          <div style={{border:'1px solid var(--border)', borderRadius:8, padding:10, background:'rgba(255,255,255,0.018)'}}>
            <div style={{display:'flex', justifyContent:'space-between', gap:8, marginBottom:8}}>
              <div style={{fontWeight:700, color:'var(--text)'}}>Promotion Gate</div>
              <div style={{fontSize:12, color:tone(gate?.status), fontWeight:700}}>{gate?.status || '-'}</div>
            </div>
            <div style={{display:'grid', gridTemplateColumns:'repeat(2, minmax(0, 1fr))', gap:8, marginBottom:8}}>
              <Pill label="收益" value={fmt(backtest?.metrics.total_return_pct, '%')} color={tone(gate?.status)} />
              <Pill label="胜率" value={fmt(backtest?.metrics.win_rate, '%')} />
              <Pill label="回撤" value={fmt(backtest?.metrics.max_drawdown_pct, '%')} color={backtest?.metrics.max_drawdown_pct != null && backtest.metrics.max_drawdown_pct > 12 ? '#ef4444' : undefined} />
              <Pill label="交易" value={backtest?.metrics.trade_count ?? '-'} />
            </div>
            {(gate?.checks || []).map(check => (
              <div key={check.name} style={{fontSize:11, color:tone(check.status), lineHeight:1.45, marginTop:4}}>
                {check.name}: {check.message}
              </div>
            ))}
          </div>

          <div style={{border:'1px solid var(--border)', borderRadius:8, padding:10, background:'rgba(255,255,255,0.018)'}}>
            <div style={{fontWeight:700, color:'var(--text)', marginBottom:8}}>最近复盘回放</div>
            <div style={{display:'flex', flexDirection:'column', gap:6, fontSize:12}}>
              <div style={{display:'flex', justifyContent:'space-between', gap:8}}><span style={{color:'var(--text-muted)'}}>特征快照</span><span style={{color:'var(--text)'}}>{latestSnapshot?.snapshot_id || '-'}</span></div>
              <div style={{display:'flex', justifyContent:'space-between', gap:8}}><span style={{color:'var(--text-muted)'}}>失败归因</span><span style={{color:tone(latestFailure?.severity)}}>{latestFailure?.severity || '-'}</span></div>
              <div style={{display:'flex', justifyContent:'space-between', gap:8}}><span style={{color:'var(--text-muted)'}}>Agent Review</span><span style={{color:tone(latestReview?.verification_status)}}>{latestReview?.verification_status || '-'}</span></div>
              <div style={{display:'flex', justifyContent:'space-between', gap:8}}><span style={{color:'var(--text-muted)'}}>落库状态</span><span style={{color:tone(records?.persistence_status)}}>{records?.persistence_status || '-'}</span></div>
            </div>
          </div>

          <div style={{border:'1px solid var(--border)', borderRadius:8, padding:10, background:'rgba(255,255,255,0.018)'}}>
            <div style={{fontWeight:700, color:'var(--text)', marginBottom:8}}>最近生命周期事件</div>
            {(center?.recent_lifecycle_events || []).slice(0, 5).map(event => (
              <div key={event.id} style={{display:'flex', justifyContent:'space-between', gap:8, fontSize:11, padding:'5px 0', borderTop:'1px solid rgba(255,255,255,0.04)'}}>
                <span style={{color:'var(--text)'}}>{event.event_type}</span>
                <span style={{color:'var(--text-muted)'}}>{event.created_at?.slice(0, 10) || '-'}</span>
              </div>
            ))}
            {!center?.recent_lifecycle_events?.length && <div style={{fontSize:12, color:'var(--text-muted)'}}>暂无生命周期事件</div>}
          </div>
        </div>
      </div>

      <div style={{fontSize:11, color:'var(--text-muted)', lineHeight:1.5}}>{center?.disclaimer || '模型中心仅用于模型复盘、自动核实和门禁观察，不构成投资建议。'}</div>
    </div>
  )
}