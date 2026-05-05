import React from 'react'
import { fetchTradePlaybook, type StockTradePlaybookResponse } from '../../api/tradePlaybook'
import { TradePlaybookCard } from './TradePlaybookCard'

type Props = {
  symbol?: string
  fallback?: React.ReactNode
  onLoaded?: (response: StockTradePlaybookResponse | null) => void
}

export default function StockTradePlaybookPanel({ symbol, fallback, onLoaded }: Props) {
  const [data, setData] = React.useState<StockTradePlaybookResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    if (!symbol) {
      setData(null)
      onLoaded?.(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const response = await fetchTradePlaybook(symbol)
      setData(response)
      onLoaded?.(response)
    } catch (err: any) {
      setError(err?.message || '个股交易剧本加载失败')
      setData(null)
      onLoaded?.(null)
    } finally {
      setLoading(false)
    }
  }, [symbol, onLoaded])

  React.useEffect(() => {
    load()
  }, [load])

  if (!symbol) return null

  return (
    <section style={{ padding: 12 }}>
      {error ? (
        <div style={{ border: '1px solid rgba(248,113,113,0.35)', background: 'rgba(248,113,113,0.08)', color: '#fecaca', borderRadius: 8, padding: 12, fontSize: 13 }}>
          个股交易剧本暂不可用，保留原短线决策卡作为回退。{error.slice(0, 160)}
          {fallback && <div style={{ marginTop: 12 }}>{fallback}</div>}
        </div>
      ) : data ? (
        <TradePlaybookCard response={data} onRefresh={load} loading={loading} />
      ) : (
        <div style={{ border: '1px solid var(--border)', background: 'rgba(255,255,255,0.025)', borderRadius: 8, padding: 18, color: 'var(--text-muted)', fontSize: 13 }}>
          {loading ? '正在生成个股交易剧本...' : '等待个股交易剧本。'}
        </div>
      )}
    </section>
  )
}