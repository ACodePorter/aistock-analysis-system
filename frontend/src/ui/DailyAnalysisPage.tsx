import React from 'react'
import ReactMarkdown from 'react-markdown'
import { fetchLatestAgentReport, fetchStockPoolPage, fetchModelPrediction, StockPoolItem, runAgent, fetchAgentStatus, ensureNewsCounts } from '../api/dailyAnalysis'
import { fetchFullReport, FullReportResponse } from '../api/report'
import FloatingModule from './FloatingModule'

interface PredictionRow {
  symbol: string
  horizon: number
  yhat: number
  prob_up?: number
}

function SectionCard({ title, extra, children }: { title: string; extra?: React.ReactNode; children: React.ReactNode }) {
  return (
    <FloatingModule title={title} rightActions={extra}>
      {children}
    </FloatingModule>
  )
}

export default function DailyAnalysisPage() {
  const [loading, setLoading] = React.useState(true)
  const [agent, setAgent] = React.useState<any | null>(null)
  const [agentFSLoading, setAgentFSLoading] = React.useState(false)
  const [runningAgent, setRunningAgent] = React.useState(false)
  const [lastRunJobId, setLastRunJobId] = React.useState<string | null>(null)
  // In browser environment setInterval returns number
  const pollRef = React.useRef<number | null>(null)
  const [poolPage, setPoolPage] = React.useState<{ items: StockPoolItem[]; page: number; page_size: number; total: number } | null>(null)
  const [poolPageNum, setPoolPageNum] = React.useState(1)
  const [predictions, setPredictions] = React.useState<PredictionRow[]>([])
  const [selectedSymbols, setSelectedSymbols] = React.useState<string[]>([])
  const [predictLoading, setPredictLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [activeSymbol, setActiveSymbol] = React.useState<string | null>(null)
  const [reportRange, setReportRange] = React.useState<'5d'|'1m'|'3m'|'6m'|'1y'|'all'>('5d')
  const [reportData, setReportData] = React.useState<FullReportResponse | null>(null)
  const [reportLoading, setReportLoading] = React.useState(false)
  const [liveCounts, setLiveCounts] = React.useState<Record<string, number>>({})
  const [liveEnsuring, setLiveEnsuring] = React.useState(false)

  const pageSize = 30

  const loadAll = React.useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [agentLatest, pool] = await Promise.all([
        fetchLatestAgentReport(),
        fetchStockPoolPage({ page: poolPageNum, page_size: pageSize })
      ])
      setAgent(agentLatest)
      setPoolPage(pool)
    } catch (e: any) {
      setError(String(e.message || e))
    } finally { setLoading(false) }
  }, [poolPageNum])

  React.useEffect(() => { loadAll() }, [loadAll])

  // Auto-run agent if none exists on first load (one-shot)
  const autoRunRef = React.useRef(false)
  React.useEffect(() => {
    if (loading) return
    if (autoRunRef.current) return
    if (!agent) {
      autoRunRef.current = true
      ;(async () => {
        try {
          setRunningAgent(true)
            const resp = await runAgent(false)
            setLastRunJobId(resp.job_id)
            startPolling(resp.job_id)
        } catch(e) { console.warn('auto run agent failed', e) } finally { setRunningAgent(false) }
      })()
    }
  }, [loading, agent])

  function startPolling(jobId: string) {
  if (pollRef.current) clearInterval(pollRef.current)
  pollRef.current = window.setInterval(async () => {
      try {
        const st = await fetchAgentStatus(jobId)
        if (st.status === 'succeeded' || st.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          // give backend a small delay to flush file
          setTimeout(()=>{ loadAll() }, 1200)
        }
      } catch(e) {
        console.warn('poll status failed', e)
      }
    }, 2500)
  }

  React.useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  async function runPrediction() {
    if (selectedSymbols.length === 0) return
    setPredictLoading(true)
    try {
      const resp = await fetchModelPrediction({ symbols: selectedSymbols, horizons: [1, 5, 10] })
      const rows: PredictionRow[] = resp.predictions.map(p => ({ symbol: p.symbol, horizon: p.horizon, yhat: p.yhat, prob_up: p.prob_up }))
      setPredictions(rows)
    } catch (e) {
      console.warn('prediction failed', e)
    } finally { setPredictLoading(false) }
  }

  function toggleSymbol(symbol: string) {
    setSelectedSymbols(prev => prev.includes(symbol) ? prev.filter(s => s !== symbol) : [...prev, symbol])
  }

  const poolItems = poolPage?.items || []
  const totalPages = poolPage ? Math.ceil(poolPage.total / poolPage.page_size) : 1

  // 自动选择第一个股票进行展示
  React.useEffect(() => {
    if (!activeSymbol && poolItems.length > 0) {
      setActiveSymbol(poolItems[0].symbol)
    }
  }, [poolItems, activeSymbol])

  // 拉取报告数据（价格 + 预测）
  React.useEffect(() => {
    if (!activeSymbol) return
    let aborted = false
    ;(async () => {
      setReportLoading(true)
      try {
        const full = await fetchFullReport(activeSymbol, reportRange)
        if (aborted) return
        // 防御：有些情况下后端可能返回比请求更多的天数（例如多取 buffer），前端再做精确裁剪
        const sliced = { ...full }
        function sliceByRange<T extends { date: string }>(arr: T[]): T[] {
          if (!arr) return []
            const today = new Date()
            const isTradingDay = (d: Date) => d.getDay() !== 0 && d.getDay() !== 6
            if (reportRange === '5d') {
              // 取最近 5 个交易日（含缺失回补）
              const out: T[] = []
              for (let i = arr.length - 1; i >= 0 && out.length < 5; i--) {
                out.unshift(arr[i])
              }
              return out
            }
            // 其余区间由后端粗滤，前端仅针对 5d 做严格精确
            return arr
        }
        sliced.price_data = sliceByRange(full.price_data || [])
        setReportData(sliced)
      } catch (e) {
        if (!aborted) console.warn('fetchFullReport failed', e)
      } finally {
        if (!aborted) setReportLoading(false)
      }
    })()
    return () => { aborted = true }
  }, [activeSymbol, reportRange])

  const rangeBtns: { key: typeof reportRange; label: string }[] = [
    { key: '5d', label: '5日' },
    { key: '1m', label: '1月' },
    { key: '3m', label: '3月' },
    { key: '6m', label: '6月' },
    { key: '1y', label: '1年' },
    { key: 'all', label: '全部' },
  ]

  return (
    <div>
      <h2 style={{ margin: '4px 0 12px', fontSize: 24, color: 'var(--text)' }}>每日分析总览</h2>
      {error && <div style={{ color: 'var(--accent-red)', fontSize: 12, marginBottom: 8 }}>加载失败：{error}</div>}
      {loading && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>加载中...</div>}
      {!loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <SectionCard title='Agent 概览' extra={<div style={{ display: 'flex', gap: 6 }}>
            <button className="dark-btn dark-btn-secondary" onClick={loadAll}>刷新</button>
            <button className="dark-btn dark-btn-secondary" disabled={agentFSLoading} title='直接读取最新文件，绕过数据库缓存' onClick={async ()=>{
              try {
                setAgentFSLoading(true)
                const latest = await fetchLatestAgentReport({ forceFilesystem: true })
                setAgent(latest)
              } catch(e) {
                console.warn('hard refresh failed', e)
              } finally { setAgentFSLoading(false) }
            }}>{agentFSLoading ? '硬刷新中...' : '硬刷新(文件)'}</button>
            <button className="dark-btn dark-btn-secondary" disabled={liveEnsuring || !agent || !Array.isArray((agent as any)?.stock_reports)} title='逐个股票补齐并回读最新计数' onClick={async ()=>{
              if (!agent || !Array.isArray((agent as any)?.stock_reports)) return
              try {
                setLiveEnsuring(true)
                const symbols = (agent as any).stock_reports.map((sr:any)=>sr.symbol).filter((s:string)=>!!s)
                const resp = await ensureNewsCounts({ symbols, ensure_min: 5, wait_seconds: 3 })
                const map: Record<string, number> = {}
                resp.results.forEach(r => { map[r.symbol] = r.total_count })
                setLiveCounts(map)
              } catch(e) {
                console.warn('ensureNewsCounts failed', e)
              } finally { setLiveEnsuring(false) }
            }}>{liveEnsuring ? '校验中...' : '校验并补齐新闻数'}</button>
            <button className="dark-btn dark-btn-primary" disabled={runningAgent} onClick={async ()=>{
              if (runningAgent) return
              try {
                setRunningAgent(true)
                const resp = await runAgent(false)
                setLastRunJobId(resp.job_id)
                startPolling(resp.job_id)
              } catch(e) {
                console.warn('runAgent failed', e)
              } finally { setRunningAgent(false) }
            }}>{runningAgent ? '生成中...' : '生成报告'}</button>
          </div>}>
            {agent ? (
              <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                <div>生成时间：{agent.generated_at}</div>
                {agent.trade_date && <div>交易日：{agent.trade_date}</div>}
                {agent.top_symbols && agent.top_symbols.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    <div style={{ fontWeight: 500, marginBottom: 4 }}>Top20 股票：</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {(agent.top_stocks || agent.top_symbols.map((s:string)=>({ symbol:s }))).map((s: any) => {
                        const label = s?.name ? `${s.name} (${s.symbol})` : s.symbol
                        return <span key={s.symbol} className="dark-badge dark-badge-info">{label}</span>
                      })}
                    </div>
                  </div>
                )}
                {Array.isArray((agent as any)?.stock_reports) && (agent as any).stock_reports.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontWeight: 500, marginBottom: 4 }}>新闻计数（最新报告摘要{Object.keys(liveCounts).length>0 ? ' + 实时校验' : ''}）</div>
                    <div style={{ maxHeight: 160, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
                      <table className="dark-table" style={{ width: '100%' }}>
                        <thead>
                          <tr>
                            <th style={{ textAlign: 'left', padding: '4px 6px' }}>股票</th>
                            <th style={{ textAlign: 'right', padding: '4px 6px' }}>新闻数</th>
                            {Object.keys(liveCounts).length>0 && <th style={{ textAlign: 'right', padding: '4px 6px' }}>实时</th>}
                          </tr>
                        </thead>
                        <tbody>
                          {(agent as any).stock_reports.map((sr: any, idx: number) => (
                            <tr key={sr.symbol || idx}>
                              <td style={{ padding: '4px 6px' }}>{(sr.name ? `${sr.name} (${sr.symbol})` : sr.symbol) || '-'}</td>
                              <td style={{ padding: '4px 6px', textAlign: 'right', color: typeof sr.news_count === 'number' && sr.news_count < 5 ? 'var(--accent-red)' : 'var(--text)' }}>{typeof sr.news_count === 'number' ? sr.news_count : '-'}</td>
                              {Object.keys(liveCounts).length>0 && (
                                <td style={{ padding: '4px 6px', textAlign: 'right', color: (liveCounts[sr.symbol] ?? 0) < 5 ? 'var(--accent-red)' : 'var(--accent-lime)', fontWeight: 600 }}>
                                  {liveCounts[sr.symbol] ?? '-'}
                                </td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
                {agent.summary_markdown && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontWeight: 500, marginBottom: 4 }}>摘要：</div>
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: 8, borderRadius: 6, border: '1px solid var(--border)' }}>
                      <ReactMarkdown>{agent.summary_markdown}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                暂无最新分析结果。
                <div style={{ marginTop: 6 }}>
                  可点击“生成报告”启动一次分析，稍候自动刷新。{lastRunJobId && <span> (job: {lastRunJobId.slice(0,8)})</span>}
                </div>
              </div>
            )}
          </SectionCard>

          <SectionCard title='动态股票池' extra={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ fontSize: 11 }}>第 {poolPageNum} / {totalPages} 页</div>
            <button className="dark-btn dark-btn-secondary" disabled={poolPageNum <= 1} onClick={() => setPoolPageNum(p => Math.max(1, p - 1))}>上一页</button>
            <button className="dark-btn dark-btn-secondary" disabled={poolPageNum >= totalPages} onClick={() => setPoolPageNum(p => Math.min(totalPages, p + 1))}>下一页</button>
          </div>}>
            <div style={{ maxHeight: 320, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8 }}>
              <table className="dark-table" style={{ width: '100%', fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>选择</th>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>股票</th>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>行业</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>首次出现</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>最近出现</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>活跃天数</th>
                  </tr>
                </thead>
                <tbody>
                  {poolItems.map(it => (
                    <tr key={it.symbol} className={selectedSymbols.includes(it.symbol) ? 'selected-row' : ''}>
                      <td style={{ padding: '4px 6px' }}>
                        <input type='checkbox' checked={selectedSymbols.includes(it.symbol)} onChange={() => toggleSymbol(it.symbol)} />
                      </td>
                      <td style={{ padding: '4px 6px' }}>{it.symbol}</td>
                      <td style={{ padding: '4px 6px', color: 'var(--text-muted)' }}>{it.industry || '-'}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{it.first_seen?.slice(0, 10)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{it.last_seen?.slice(0, 10)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 500 }}>{it.days_active ?? '-'}</td>
                    </tr>
                  ))}
                  {poolItems.length === 0 && (
                    <tr><td colSpan={6} style={{ padding: 12, textAlign: 'center', color: 'var(--text-muted)' }}>暂无数据</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>共 {poolPage?.total ?? 0} 条</div>
              <button className="dark-btn dark-btn-primary" disabled={predictLoading || selectedSymbols.length === 0} onClick={runPrediction}>
                {predictLoading ? '预测中...' : `预测 (${selectedSymbols.length})`}
              </button>
            </div>
          </SectionCard>

          {activeSymbol && (
            <SectionCard
              title={`价格走势 & 预测 (${activeSymbol})`}
              extra={
                <div style={{ display: 'flex', gap: 4 }}>
                  {rangeBtns.map(r => (
                    <button key={r.key} onClick={() => setReportRange(r.key)} className={reportRange === r.key ? 'primary-button active' : 'soft-button'}>{r.label}</button>
                  ))}
                </div>
              }
            >
              {reportLoading && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>加载中...</div>}
              {!reportLoading && reportData && reportData.price_data && reportData.price_data.length > 0 && (
                <div style={{ fontSize: 12 }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                    {reportData.price_data.map(p => (
                      <span key={p.date} className="dark-badge dark-badge-info">
                        {p.date.slice(5)} {p.close != null ? p.close.toFixed(2) : '-'}
                      </span>
                    ))}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    显示 {reportData.price_data.length} 条价格数据{reportData.stale ? '（来自较早的缓存数据）' : ''}
                  </div>
                </div>
              )}
              {!reportLoading && (!reportData || !reportData.price_data || reportData.price_data.length === 0) && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>暂无价格数据</div>
              )}
            </SectionCard>
          )}

          <SectionCard title='预测结果'>
            {predictions.length > 0 ? (
              <table className="dark-table" style={{ width: '100%', fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>股票</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>周期</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>预测值</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>上涨概率</th>
                  </tr>
                </thead>
                <tbody>
                  {predictions.map((p, idx) => (
                    <tr key={idx}>
                      <td style={{ padding: '4px 6px' }}>{p.symbol}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{p.horizon}d</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{p.yhat.toFixed(2)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: p.prob_up != null ? (p.prob_up > 0.55 ? 'var(--accent-lime)' : p.prob_up < 0.45 ? 'var(--accent-red)' : 'var(--text-muted)') : 'var(--text-muted)' }}>{p.prob_up != null ? (p.prob_up * 100).toFixed(1) + '%' : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>尚未生成预测，请先选择股票并点击预测。</div>}
          </SectionCard>
        </div>
      )}
    </div>
  )
}
