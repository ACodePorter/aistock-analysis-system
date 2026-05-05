import React from 'react'
import {
  approveOpportunityCandidate,
  discoverOpportunities,
  fetchOpportunityCandidates,
  type OpportunityCandidate,
} from '../../api/opportunities'
import {
  createUserTrade,
  deleteUserTrade,
  fetchUserPositions,
  fetchUserTrades,
  type TradeInput,
  type TradeSide,
  type UserPosition,
  type UserTrade,
} from '../../api/userPortfolio'

type Props = {
  selectedSymbol?: string
  onSelectSymbol: (symbol: string) => void
  onRefreshPlaybook: () => void
}

type TradeFormState = {
  symbol: string
  side: TradeSide
  trade_date: string
  price: string
  quantity: string
  fees: string
  tax: string
  notes: string
}

const today = () => new Date().toISOString().slice(0, 10)

const emptyForm = (symbol?: string): TradeFormState => ({
  symbol: symbol || '',
  side: 'buy',
  trade_date: today(),
  price: '',
  quantity: '',
  fees: '0',
  tax: '0',
  notes: '',
})

function money(value?: number | null, digits = 2) {
  if (value == null || Number.isNaN(value)) return '-'
  return value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function pct(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function PanelCard({ children, title, extra }: Readonly<{ children: React.ReactNode; title: string; extra?: React.ReactNode }>) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', minWidth: 0, overflow: 'hidden' }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
        <div style={{ color: 'var(--text)', fontSize: 14, fontWeight: 850 }}>{title}</div>
        {extra}
      </div>
      <div style={{ padding: 14 }}>{children}</div>
    </div>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 0 }}>
      <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{label}</span>
      {children}
    </label>
  )
}

const inputStyle: React.CSSProperties = {
  height: 34,
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'rgba(15,23,42,0.74)',
  color: 'var(--text)',
  padding: '0 10px',
  outline: 'none',
  minWidth: 0,
}

function PositionTable({ positions, onSelectSymbol }: Readonly<{ positions: UserPosition[]; onSelectSymbol: (symbol: string) => void }>) {
  if (!positions.length) {
    return <div style={{ color: 'var(--text-muted)', border: '1px dashed var(--border)', borderRadius: 8, padding: 12 }}>暂无真实持仓，先录入一笔买入流水。</div>
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
        <thead>
          <tr style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'left' }}>
            <th style={{ padding: '0 8px 8px 0' }}>股票</th>
            <th style={{ padding: '0 8px 8px' }}>数量</th>
            <th style={{ padding: '0 8px 8px' }}>成本</th>
            <th style={{ padding: '0 8px 8px' }}>现价</th>
            <th style={{ padding: '0 8px 8px' }}>市值</th>
            <th style={{ padding: '0 8px 8px' }}>浮盈亏</th>
            <th style={{ padding: '0 0 8px 8px' }}>权重</th>
          </tr>
        </thead>
        <tbody>
          {positions.map(item => {
            const pnlTone = (item.unrealized_pnl ?? 0) >= 0 ? '#16a34a' : '#ef4444'
            return (
              <tr key={item.symbol} style={{ borderTop: '1px solid var(--border)', color: 'var(--text)', fontSize: 13 }}>
                <td style={{ padding: '9px 8px 9px 0' }}>
                  <button type="button" onClick={() => onSelectSymbol(item.symbol)} style={{ color: '#93c5fd', background: 'transparent', border: 0, padding: 0, cursor: 'pointer', fontWeight: 850 }}>{item.symbol}</button>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{item.name || item.industry || '-'}</div>
                </td>
                <td style={{ padding: '9px 8px' }}>{item.quantity}</td>
                <td style={{ padding: '9px 8px' }}>{money(item.avg_cost, 3)}</td>
                <td style={{ padding: '9px 8px' }}>{money(item.current_price, 3)}</td>
                <td style={{ padding: '9px 8px' }}>{money(item.market_value)}</td>
                <td style={{ padding: '9px 8px', color: pnlTone, fontWeight: 850 }}>{money(item.unrealized_pnl)} / {pct(item.unrealized_pnl_pct)}</td>
                <td style={{ padding: '9px 0 9px 8px' }}>{pct(item.weight_pct)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function confidenceText(value?: number | null) {
  return value == null ? '-' : pct(value * 100)
}

function CandidateList({ candidates, onSelectSymbol, onApprove }: Readonly<{ candidates: OpportunityCandidate[]; onSelectSymbol: (symbol: string) => void; onApprove: (symbol: string) => void }>) {
  if (!candidates.length) {
    return <div style={{ color: 'var(--text-muted)', border: '1px dashed var(--border)', borderRadius: 8, padding: 12 }}>暂无候选，可先运行一次机会发现。</div>
  }
  return (
    <div style={{ display: 'grid', gap: 9 }}>
      {candidates.slice(0, 8).map(item => (
        <div key={`${item.symbol}-${item.discoveredAt}`} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'rgba(255,255,255,0.02)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
            <button type="button" onClick={() => onSelectSymbol(item.symbol)} style={{ color: '#93c5fd', background: 'transparent', border: 0, padding: 0, cursor: 'pointer', fontWeight: 850, textAlign: 'left' }}>
              {item.symbol} {item.name || ''}
            </button>
            <span style={{ border: '1px solid rgba(147,197,253,0.35)', color: '#bfdbfe', borderRadius: 999, padding: '3px 8px', fontSize: 12 }}>{item.status}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 8, marginTop: 8, color: 'var(--text)', fontSize: 12 }}>
            <span>机会分 {money(item.opportunityScore, 1)}</span>
            <span>置信 {confidenceText(item.confidence)}</span>
            <span>风险 {item.riskLevel || '-'}</span>
          </div>
          {item.rationale && <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5, marginTop: 8 }}>{item.rationale}</div>}
          {!item.autoPinned && (
            <div style={{ marginTop: 9 }}>
              <button type="button" className="dark-btn dark-btn-secondary" onClick={() => onApprove(item.symbol)}>确认置顶</button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default function UserPortfolioOpportunityPanel({ selectedSymbol, onSelectSymbol, onRefreshPlaybook }: Readonly<Props>) {
  const [positions, setPositions] = React.useState<UserPosition[]>([])
  const [trades, setTrades] = React.useState<UserTrade[]>([])
  const [candidates, setCandidates] = React.useState<OpportunityCandidate[]>([])
  const [form, setForm] = React.useState<TradeFormState>(() => emptyForm(selectedSymbol))
  const [loading, setLoading] = React.useState(false)
  const [discovering, setDiscovering] = React.useState(false)
  const [message, setMessage] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (selectedSymbol && !form.symbol) setForm(prev => ({ ...prev, symbol: selectedSymbol }))
  }, [form.symbol, selectedSymbol])

  const loadAll = React.useCallback(async () => {
    setLoading(true)
    try {
      const [positionResp, tradeResp, candidateResp] = await Promise.all([
        fetchUserPositions(),
        fetchUserTrades(),
        fetchOpportunityCandidates(),
      ])
      setPositions(positionResp.positions || [])
      setTrades(tradeResp.trades || [])
      setCandidates(candidateResp.candidates || [])
    } catch (err: any) {
      setMessage(err?.message || '持仓数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadAll()
  }, [loadAll])

  const updateForm = (key: keyof TradeFormState, value: string) => setForm(prev => ({ ...prev, [key]: value }))

  const submitTrade = async () => {
    const payload: TradeInput = {
      symbol: form.symbol.trim(),
      side: form.side,
      trade_date: form.trade_date,
      price: Number(form.price),
      quantity: Number(form.quantity),
      fees: Number(form.fees || 0),
      tax: Number(form.tax || 0),
      source: 'manual',
      notes: form.notes.trim() || null,
    }
    if (!payload.symbol || !payload.price || !payload.quantity) {
      setMessage('请填写股票代码、成交价和数量。')
      return
    }
    setLoading(true)
    try {
      await createUserTrade(payload)
      setForm(emptyForm(payload.symbol))
      setMessage('交易流水已保存，持仓已重算。')
      await loadAll()
      onRefreshPlaybook()
    } catch (err: any) {
      setMessage(err?.message || '保存交易流水失败')
    } finally {
      setLoading(false)
    }
  }

  const removeTrade = async (id: number) => {
    if (!globalThis.confirm('确认删除这笔交易流水？')) return
    setLoading(true)
    try {
      await deleteUserTrade(id)
      setMessage('交易流水已删除，持仓已重算。')
      await loadAll()
      onRefreshPlaybook()
    } catch (err: any) {
      setMessage(err?.message || '删除交易流水失败')
    } finally {
      setLoading(false)
    }
  }

  const runDiscovery = async () => {
    setDiscovering(true)
    try {
      const result = await discoverOpportunities({ scan_limit: 160, max_candidates: 20, auto_pin: true })
      setCandidates(result.candidates || [])
      setMessage(`机会发现完成：自动置顶 ${result.autoPinnedCount} 个，待确认 ${result.pendingCount} 个。`)
      onRefreshPlaybook()
    } catch (err: any) {
      setMessage(err?.message || '机会发现失败')
    } finally {
      setDiscovering(false)
    }
  }

  const approve = async (symbol: string) => {
    setDiscovering(true)
    try {
      await approveOpportunityCandidate(symbol, '用户在首页确认置顶')
      setMessage(`${symbol} 已确认置顶。`)
      await loadAll()
      onRefreshPlaybook()
    } catch (err: any) {
      setMessage(err?.message || '确认置顶失败')
    } finally {
      setDiscovering(false)
    }
  }

  return (
    <section style={{ padding: '0 12px 12px' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'linear-gradient(135deg, rgba(15,23,42,0.98), rgba(30,41,59,0.88))', padding: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 850 }}>我的持仓与机会发现</div>
            <h2 style={{ color: 'var(--text)', margin: '5px 0 0', fontSize: 22, lineHeight: 1.18 }}>交易剧本会使用真实成本价生成买卖处理方案</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="dark-btn dark-btn-secondary" onClick={loadAll} disabled={loading}>{loading ? '刷新中' : '刷新'}</button>
            <button type="button" className="dark-btn" onClick={runDiscovery} disabled={discovering}>{discovering ? '扫描中' : '发现潜力股'}</button>
          </div>
        </div>
        {message && <div style={{ border: '1px solid rgba(147,197,253,0.28)', background: 'rgba(59,130,246,0.08)', color: '#bfdbfe', borderRadius: 8, padding: 10, marginBottom: 12, fontSize: 13 }}>{message}</div>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 360px), 1fr))', gap: 12, alignItems: 'start' }}>
          <PanelCard title="当前持仓">
            <PositionTable positions={positions} onSelectSymbol={onSelectSymbol} />
          </PanelCard>
          <PanelCard title="录入交易流水">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 96px', gap: 9 }}>
              <Field label="股票代码"><input style={inputStyle} value={form.symbol} onChange={event => updateForm('symbol', event.target.value.toUpperCase())} placeholder="600519.SH" /></Field>
              <Field label="方向">
                <select style={inputStyle} value={form.side} onChange={event => updateForm('side', event.target.value as TradeSide)}>
                  <option value="buy">买入</option>
                  <option value="sell">卖出</option>
                </select>
              </Field>
              <Field label="日期"><input style={inputStyle} type="date" value={form.trade_date} onChange={event => updateForm('trade_date', event.target.value)} /></Field>
              <Field label="成交价"><input style={inputStyle} type="number" min="0" step="0.001" value={form.price} onChange={event => updateForm('price', event.target.value)} /></Field>
              <Field label="数量"><input style={inputStyle} type="number" min="1" step="100" value={form.quantity} onChange={event => updateForm('quantity', event.target.value)} /></Field>
              <Field label="费用"><input style={inputStyle} type="number" min="0" step="0.01" value={form.fees} onChange={event => updateForm('fees', event.target.value)} /></Field>
              <Field label="税费"><input style={inputStyle} type="number" min="0" step="0.01" value={form.tax} onChange={event => updateForm('tax', event.target.value)} /></Field>
              <Field label="备注"><input style={inputStyle} value={form.notes} onChange={event => updateForm('notes', event.target.value)} /></Field>
            </div>
            <button type="button" className="dark-btn" style={{ marginTop: 10, width: '100%' }} onClick={submitTrade} disabled={loading}>{loading ? '保存中' : '保存流水并重算持仓'}</button>
            <div style={{ marginTop: 12, display: 'grid', gap: 7, maxHeight: 170, overflow: 'auto' }}>
              {trades.slice(0, 5).map(item => (
                <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, color: 'var(--text-muted)', fontSize: 12, borderTop: '1px solid var(--border)', paddingTop: 7 }}>
                  <span>{item.trade_date} {item.symbol} {item.side === 'buy' ? '买入' : '卖出'} {item.quantity} 股 @ {money(item.price, 3)}</span>
                  <button type="button" onClick={() => removeTrade(item.id)} style={{ color: '#fca5a5', background: 'transparent', border: 0, cursor: 'pointer' }}>删除</button>
                </div>
              ))}
            </div>
          </PanelCard>
          <PanelCard title="机会候选" extra={<span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{candidates.length} 个</span>}>
            <CandidateList candidates={candidates} onSelectSymbol={onSelectSymbol} onApprove={approve} />
          </PanelCard>
        </div>
      </div>
    </section>
  )
}