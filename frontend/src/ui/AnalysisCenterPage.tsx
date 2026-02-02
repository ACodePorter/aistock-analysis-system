import React, { useEffect, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { API_BASE, buildApiUrl } from '../config/api'

// 将JSON综合分析转换为可读Markdown
function formatComprehensiveAnalysis(rawAnalysis: string): string {
  if (!rawAnalysis) return '暂无分析报告'
  
  // 尝试解析JSON
  try {
    const data = JSON.parse(rawAnalysis)
    
    // 构建可读的Markdown报告
    let md = ''
    
    // 摘要部分
    if (data.summary) {
      const s = data.summary
      const sentimentMap: Record<string, string> = {
        'bullish': '🟢 偏多',
        'bearish': '🔴 偏空',
        'neutral': '🟡 中性'
      }
      md += `### 📊 市场概况\n\n`
      md += `- **市场情绪**: ${sentimentMap[s.market_sentiment] || s.market_sentiment}\n`
      md += `- **分析股票数**: ${s.total_analyzed || 0}只\n`
      md += `- **平均评分**: ${(s.average_score || 0).toFixed(1)}分\n`
      md += `- **推荐分布**: 买入 ${s.buy_recommendations || 0} / 持有 ${s.hold_recommendations || 0} / 卖出 ${s.sell_recommendations || 0}\n\n`
    }
    
    // 推荐买入股票 (过滤掉分析失败的)
    const validTopPicks = (data.top_picks || []).filter((s: any) => 
      s.recommendation !== 'unknown' && s.score > 0 && !s.llm_error
    )
    if (validTopPicks.length > 0) {
      md += `### 🔥 重点关注（Top Picks）\n\n`
      // 去重（按symbol）
      const seen = new Set<string>()
      validTopPicks.slice(0, 5).forEach((stock: any, idx: number) => {
        if (seen.has(stock.symbol)) return
        seen.add(stock.symbol)
        const pctStr = stock.price_change != null ? `${stock.price_change >= 0 ? '+' : ''}${stock.price_change.toFixed(2)}%` : ''
        md += `**${idx + 1}. ${stock.name || stock.symbol}** (${stock.symbol})\n`
        md += `   - 评分: ${stock.score}分 | 建议: ${stock.recommendation === 'buy' ? '买入' : stock.recommendation === 'hold' ? '持有' : '卖出'}${pctStr ? ` | 涨跌: ${pctStr}` : ''}\n`
        if (stock.key_reasons) {
          md += `   - 关键因素: ${stock.key_reasons}\n`
        }
        md += '\n'
      })
    }
    
    // 风险提示 (过滤掉分析失败的)
    const validRiskAlerts = (data.risk_alerts || []).filter((s: any) => 
      s.score > 0 && !s.llm_error && (s.risks?.length > 0 || s.risk_level === 'high')
    )
    if (validRiskAlerts.length > 0) {
      md += `### ⚠️ 风险提示\n\n`
      const seen = new Set<string>()
      validRiskAlerts.slice(0, 5).forEach((stock: any) => {
        if (seen.has(stock.symbol)) return
        seen.add(stock.symbol)
        md += `- **${stock.name || stock.symbol}** (${stock.symbol}): 评分${stock.score}分\n`
        if (stock.risks && stock.risks.length > 0) {
          md += `  - 风险因素: ${stock.risks.join(', ')}\n`
        }
      })
      md += '\n'
    }
    
    // 全部分析列表 (过滤掉分析失败的，去重)
    const validAnalyses = (data.all_analyses || []).filter((s: any) => 
      s.recommendation !== 'unknown' && s.score > 0 && !s.llm_error
    )
    if (validAnalyses.length > 0) {
      // 去重
      const uniqueAnalyses: any[] = []
      const seenSymbols = new Set<string>()
      validAnalyses.forEach((s: any) => {
        if (!seenSymbols.has(s.symbol)) {
          seenSymbols.add(s.symbol)
          uniqueAnalyses.push(s)
        }
      })
      
      md += `### 📋 全部分析（${uniqueAnalyses.length}只）\n\n`
      md += '| 股票 | 评分 | 建议 | 新闻情感 | 新闻数 |\n'
      md += '|------|------|------|----------|--------|\n'
      uniqueAnalyses.forEach((stock: any) => {
        const recMap: Record<string, string> = { 'buy': '✅买入', 'hold': '⏸️持有', 'sell': '🛑卖出' }
        const sentiment = stock.news_sentiment != null ? (stock.news_sentiment * 100).toFixed(0) + '%' : '-'
        md += `| ${stock.name || stock.symbol} | ${stock.score} | ${recMap[stock.recommendation] || stock.recommendation} | ${sentiment} | ${stock.news_count || 0} |\n`
      })
      md += '\n'
    }
    
    return md || '暂无详细分析数据'
    
  } catch (e) {
    // 如果不是JSON，可能已经是Markdown格式，直接返回
    if (rawAnalysis.includes('#') || rawAnalysis.includes('**') || rawAnalysis.length > 50) {
      return rawAnalysis
    }
    return rawAnalysis
  }
}

// 类型定义
interface ScoreBreakdown {
  technical: number
  fundamental: number
  sentiment: number
  fund_flow: number
  cycle: number
  total: number
}

interface StockAnalysis {
  symbol: string
  name: string | null
  sector: string | null
  analysis_date: string
  scores: ScoreBreakdown
  recommendation: string
  risk_level: string
  confidence: number
  close_price: number | null
  pct_change: number | null
  volume: number | null
  ma5: number | null
  ma20: number | null
  rsi: number | null
  macd: number | null
  news_count: number
  news_sentiment_avg: number | null
  analysis_summary: string
  key_factors: string[]
  risk_factors: string[]
}

interface DailyReport {
  report_date: string
  total_stocks: number
  buy_count: number
  hold_count: number
  sell_count: number
  market_sentiment: string
  market_summary: string
  buy_recommendations: any[]
  hold_recommendations: any[]
  sell_recommendations: any[]
  comprehensive_analysis: string
  risk_warnings: any[]
  opportunities: any[]
  sector_analysis: Record<string, any>
  generated_at: string | null
  generation_model: string | null
}

interface AnalysisHistoryItem {
  analysis_date: string
  total_stocks: number
  buy_count: number
  hold_count: number
  sell_count: number
  avg_score: number
  status: string
}

interface WatchlistItem {
  symbol: string
  name: string | null
  sector: string | null
  enabled: boolean
  source: string
  score: number | null
  investment_potential: number | null
  remove_suggested: boolean
  remove_reason: string | null
  added_at: string
  last_analysis_at: string | null
  observation_days: number
}

interface SchedulerStatus {
  analysis_enabled: boolean
  last_analysis_time: string | null
  last_report_time: string | null
  next_analysis_time: string
  analysis_cron: string
  jobs: { id: string; name: string; schedule: string; status: string }[]
}

interface PeriodReport {
  period_type: string
  start_date: string
  end_date: string
  total_trading_days: number
  market_trend: string
  avg_score: number
  score_change: number
  buy_signals_count: number
  sell_signals_count: number
  top_performers: any[]
  worst_performers: any[]
  sector_performance: Record<string, any>
  comprehensive_analysis: string
  key_insights: string[]
  risk_warnings: string[]
  generated_at: string
}

// API 调用函数
async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(path), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) }
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

// 评分徽章组件
function ScoreBadge({ score, size = 'normal' }: { score: number; size?: 'normal' | 'large' }) {
  const getColor = (s: number) => {
    if (s >= 70) return '#10b981'
    if (s >= 50) return '#f59e0b'
    return '#ef4444'
  }
  
  const baseStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 999,
    fontWeight: 600,
    color: '#fff',
    background: getColor(score),
    ...(size === 'large' 
      ? { width: 56, height: 56, fontSize: 18 }
      : { width: 36, height: 36, fontSize: 12 }
    )
  }
  
  return <div style={baseStyle}>{score.toFixed(0)}</div>
}

// 推荐标签组件
function RecommendationBadge({ type }: { type: string }) {
  const config: Record<string, { label: string; color: string; bg: string }> = {
    buy: { label: '买入', color: '#fff', bg: '#10b981' },
    hold: { label: '持有', color: '#fff', bg: '#3b82f6' },
    sell: { label: '卖出', color: '#fff', bg: '#ef4444' },
    watch: { label: '观望', color: '#9ca3af', bg: '#374151' }
  }
  
  const c = config[type] || config.watch
  
  return (
    <span style={{
      padding: '4px 10px',
      borderRadius: 4,
      fontSize: 12,
      fontWeight: 500,
      color: c.color,
      background: c.bg
    }}>
      {c.label}
    </span>
  )
}

// 风险标签组件
function RiskBadge({ level }: { level: string }) {
  const config: Record<string, { label: string; color: string }> = {
    low: { label: '低风险', color: '#10b981' },
    medium: { label: '中风险', color: '#f59e0b' },
    high: { label: '高风险', color: '#ef4444' }
  }
  
  const c = config[level] || config.medium
  
  return (
    <span style={{
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 11,
      color: c.color,
      border: `1px solid ${c.color}`
    }}>
      {c.label}
    </span>
  )
}

// 统计卡片组件
function StatCard({ title, value, subtitle, color }: { 
  title: string; 
  value: number | string; 
  subtitle?: string;
  color?: string 
}) {
  return (
    <div style={{
      background: 'var(--surface-dark)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      padding: 16,
      flex: 1,
      minWidth: 120
    }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 24, fontWeight: 600, color: color || 'var(--text)' }}>{value}</div>
      {subtitle && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{subtitle}</div>}
    </div>
  )
}

// 股票分析卡片组件
function StockAnalysisCard({ data, onClick }: { data: StockAnalysis; onClick?: () => void }) {
  const pctColor = (data.pct_change || 0) >= 0 ? 'var(--accent-lime)' : 'var(--accent-red)'
  const sentimentColor = (data.news_sentiment_avg || 0.5) >= 0.6 ? '#10b981' : (data.news_sentiment_avg || 0.5) < 0.4 ? '#ef4444' : '#f59e0b'
  
  return (
    <div 
      onClick={onClick}
      style={{
        background: 'var(--surface-dark)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: 16,
        cursor: onClick ? 'pointer' : 'default',
        transition: 'all 0.2s',
      }}
      onMouseEnter={(e) => {
        if (onClick) e.currentTarget.style.borderColor = 'var(--primary)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--border)'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 16 }}>{data.name || data.symbol}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{data.symbol}</div>
        </div>
        <ScoreBadge score={data.scores.total} />
      </div>
      
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <RecommendationBadge type={data.recommendation} />
        <RiskBadge level={data.risk_level} />
      </div>
      
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>收盘价</div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>¥{data.close_price?.toFixed(2) || '-'}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>涨跌幅</div>
          <div style={{ fontSize: 14, fontWeight: 500, color: pctColor }}>
            {data.pct_change != null ? `${data.pct_change >= 0 ? '+' : ''}${data.pct_change.toFixed(2)}%` : '-'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>置信度</div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>{(data.confidence * 100).toFixed(0)}%</div>
        </div>
      </div>
      
      {/* 新闻情报 */}
      {data.news_count > 0 && (
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: 8, 
          marginBottom: 12,
          padding: '6px 10px',
          background: 'rgba(255,255,255,0.03)',
          borderRadius: 6
        }}>
          <span style={{ fontSize: 12 }}>📰</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {data.news_count}篇相关新闻
          </span>
          {data.news_sentiment_avg != null && (
            <span style={{ 
              fontSize: 11, 
              color: sentimentColor,
              marginLeft: 'auto'
            }}>
              情感: {data.news_sentiment_avg >= 0.6 ? '😊 乐观' : data.news_sentiment_avg < 0.4 ? '😟 悲观' : '😐 中性'}
            </span>
          )}
        </div>
      )}
      
      {data.analysis_summary && (
        <div style={{ 
          fontSize: 12, 
          color: 'var(--text-muted)', 
          lineHeight: 1.5,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical'
        }}>
          {data.analysis_summary}
        </div>
      )}
    </div>
  )
}

// 主页面组件
export default function AnalysisCenterPage() {
  const [selectedDate, setSelectedDate] = useState<string>(new Date().toISOString().split('T')[0])
  const [analyses, setAnalyses] = useState<StockAnalysis[]>([])
  const [report, setReport] = useState<DailyReport | null>(null)
  const [history, setHistory] = useState<AnalysisHistoryItem[]>([])
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'overview' | 'watchlist' | 'history' | 'period'>('overview')
  const [filterRec, setFilterRec] = useState<string>('')
  
  // 股票详情弹窗状态
  const [selectedStock, setSelectedStock] = useState<StockAnalysis | null>(null)
  const [stockNews, setStockNews] = useState<any[]>([])
  const [newsLoading, setNewsLoading] = useState(false)
  
  // 调度状态
  const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null)
  
  // 阶段性报告
  const [periodType, setPeriodType] = useState<'weekly' | 'monthly' | 'quarterly' | 'yearly'>('weekly')
  const [periodReport, setPeriodReport] = useState<PeriodReport | null>(null)
  const [periodLoading, setPeriodLoading] = useState(false)

  // 加载股票相关新闻
  const loadStockNews = useCallback(async (symbol: string) => {
    setNewsLoading(true)
    try {
      const data = await fetchJSON<{ articles: any[], total_count: number }>(`/api/news/stock/${symbol}?limit=10`)
      setStockNews(data.articles || [])
    } catch (e) {
      console.error('Failed to load stock news:', e)
      setStockNews([])
    } finally {
      setNewsLoading(false)
    }
  }, [])

  // 打开股票详情弹窗
  const openStockDetail = useCallback((stock: StockAnalysis) => {
    setSelectedStock(stock)
    loadStockNews(stock.symbol)
  }, [loadStockNews])

  // 加载调度状态
  const loadSchedulerStatus = useCallback(async () => {
    try {
      const data = await fetchJSON<SchedulerStatus>('/api/analysis/scheduler/status')
      setSchedulerStatus(data)
    } catch (e) {
      console.error('Failed to load scheduler status:', e)
    }
  }, [])

  // 加载每日分析数据
  const loadDailyAnalysis = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [analysisData, reportData] = await Promise.all([
        fetchJSON<StockAnalysis[]>(`/api/analysis/daily/${selectedDate}${filterRec ? `?recommendation=${filterRec}` : ''}`),
        fetchJSON<DailyReport>(`/api/analysis/report/${selectedDate}`).catch(() => null)
      ])
      setAnalyses(analysisData)
      setReport(reportData)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [selectedDate, filterRec])

  // 加载历史记录
  const loadHistory = useCallback(async () => {
    try {
      const data = await fetchJSON<AnalysisHistoryItem[]>('/api/analysis/history?days=30')
      setHistory(data)
    } catch (e) {
      console.error('Failed to load history:', e)
    }
  }, [])

  // 加载观察列表
  const loadWatchlist = useCallback(async () => {
    try {
      const data = await fetchJSON<WatchlistItem[]>('/api/analysis/watchlist')
      setWatchlist(data)
    } catch (e) {
      console.error('Failed to load watchlist:', e)
    }
  }, [])

  // 加载阶段性报告
  const loadPeriodReport = useCallback(async () => {
    setPeriodLoading(true)
    try {
      const data = await fetchJSON<PeriodReport>(`/api/analysis/report/period/${periodType}`)
      setPeriodReport(data)
    } catch (e) {
      console.error('Failed to load period report:', e)
      setPeriodReport(null)
    } finally {
      setPeriodLoading(false)
    }
  }, [periodType])

  // 确认移除股票
  const confirmRemoval = async (symbol: string) => {
    if (!confirm(`确定要从观察列表中移除 ${symbol} 吗？`)) return
    try {
      await fetchJSON(`/api/analysis/watchlist/${symbol}/confirm-removal`, { method: 'POST' })
      loadWatchlist()
    } catch (e: any) {
      alert('移除失败: ' + e.message)
    }
  }

  useEffect(() => {
    loadDailyAnalysis()
    loadHistory()
    loadWatchlist()
    loadSchedulerStatus()
  }, [])

  useEffect(() => {
    loadDailyAnalysis()
  }, [selectedDate, filterRec])

  // 切换到阶段性报告时加载
  useEffect(() => {
    if (activeTab === 'period') {
      loadPeriodReport()
    }
  }, [activeTab, periodType])

  // 统计数据
  const stats = {
    total: analyses.length,
    buy: analyses.filter(a => a.recommendation === 'buy').length,
    hold: analyses.filter(a => a.recommendation === 'hold').length,
    sell: analyses.filter(a => a.recommendation === 'sell').length,
    avgScore: analyses.length > 0 
      ? analyses.reduce((sum, a) => sum + a.scores.total, 0) / analyses.length 
      : 0
  }

  return (
    <div style={{ padding: 20, maxWidth: 1400, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>📊 每日分析中心</h1>
          <p style={{ margin: '8px 0 0', color: 'var(--text-muted)', fontSize: 14 }}>
            智能分析观察列表股票，自动生成每日投资建议
          </p>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {/* 自动调度状态 */}
          {schedulerStatus && (
            <div style={{
              padding: '8px 14px',
              background: 'rgba(16, 185, 129, 0.1)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: 8,
              fontSize: 12
            }}>
              <div style={{ color: '#10b981', fontWeight: 500 }}>🤖 自动分析已启用</div>
              <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>
                下次分析: {new Date(schedulerStatus.next_analysis_time).toLocaleString('zh-CN', {
                  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                })}
              </div>
            </div>
          )}
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--surface-dark)',
              color: 'var(--text)',
              cursor: 'pointer'
            }}
          />
          <button
            onClick={() => loadDailyAnalysis()}
            style={{
              padding: '10px 20px',
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--surface-dark)',
              color: 'var(--text)',
              cursor: 'pointer',
              fontWeight: 500
            }}
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {/* 标签页 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid var(--border)', paddingBottom: 4 }}>
        {[
          { key: 'overview', label: '📈 今日概览' },
          { key: 'period', label: '📊 阶段报告' },
          { key: 'watchlist', label: '👁 观察列表' },
          { key: 'history', label: '📜 历史记录' }
        ].map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as any)}
            style={{
              padding: '10px 20px',
              border: 'none',
              background: activeTab === tab.key ? 'var(--primary)' : 'transparent',
              color: activeTab === tab.key ? '#fff' : 'var(--text-muted)',
              borderRadius: '8px 8px 0 0',
              cursor: 'pointer',
              fontWeight: 500
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          padding: 16,
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid #ef4444',
          borderRadius: 8,
          color: '#ef4444',
          marginBottom: 20
        }}>
          {error}
        </div>
      )}

      {/* 今日概览 */}
      {activeTab === 'overview' && (
        <>
          {/* 统计卡片 */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
            <StatCard title="分析股票数" value={stats.total} />
            <StatCard title="推荐买入" value={stats.buy} color="#10b981" />
            <StatCard title="建议持有" value={stats.hold} color="#3b82f6" />
            <StatCard title="建议卖出" value={stats.sell} color="#ef4444" />
            <StatCard title="平均评分" value={stats.avgScore.toFixed(1)} />
          </div>

          {/* 综合报告 */}
          {report && (
            <div style={{
              background: 'var(--surface-dark)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: 20,
              marginBottom: 24
            }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600 }}>📝 每日综合分析报告</h3>
              <div className="markdown-content" style={{ 
                fontSize: 14, 
                lineHeight: 1.8, 
                color: 'var(--text)'
              }}>
                <ReactMarkdown>
                  {formatComprehensiveAnalysis(report.comprehensive_analysis) || report.market_summary}
                </ReactMarkdown>
              </div>
              {report.generation_model && (
                <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
                  生成模型: {report.generation_model} | 生成时间: {report.generated_at}
                </div>
              )}
            </div>
          )}

          {/* 新闻情报汇总 */}
          {analyses.length > 0 && (
            <div style={{
              background: 'var(--surface-dark)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: 20,
              marginBottom: 24
            }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600 }}>📰 今日新闻情报汇总</h3>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                {/* 新闻统计 */}
                <div style={{ 
                  flex: 1, 
                  minWidth: 200,
                  padding: 12, 
                  background: 'rgba(255,255,255,0.03)', 
                  borderRadius: 8 
                }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>相关新闻总数</div>
                  <div style={{ fontSize: 24, fontWeight: 600 }}>
                    {analyses.reduce((sum, a) => sum + a.news_count, 0)} 篇
                  </div>
                </div>
                
                {/* 情感分布 */}
                <div style={{ 
                  flex: 1, 
                  minWidth: 200,
                  padding: 12, 
                  background: 'rgba(255,255,255,0.03)', 
                  borderRadius: 8 
                }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>平均新闻情感</div>
                  {(() => {
                    const withSentiment = analyses.filter(a => a.news_sentiment_avg != null)
                    const avgSentiment = withSentiment.length > 0
                      ? withSentiment.reduce((sum, a) => sum + (a.news_sentiment_avg || 0), 0) / withSentiment.length
                      : 0.5
                    const sentimentLabel = avgSentiment >= 0.6 ? '乐观' : avgSentiment < 0.4 ? '悲观' : '中性'
                    const sentimentEmoji = avgSentiment >= 0.6 ? '😊' : avgSentiment < 0.4 ? '😟' : '😐'
                    const sentimentColor = avgSentiment >= 0.6 ? '#10b981' : avgSentiment < 0.4 ? '#ef4444' : '#f59e0b'
                    return (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 24 }}>{sentimentEmoji}</span>
                        <span style={{ fontSize: 18, fontWeight: 600, color: sentimentColor }}>{sentimentLabel}</span>
                        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>({(avgSentiment * 100).toFixed(0)}%)</span>
                      </div>
                    )
                  })()}
                </div>

                {/* 有新闻覆盖的股票 */}
                <div style={{ 
                  flex: 1, 
                  minWidth: 200,
                  padding: 12, 
                  background: 'rgba(255,255,255,0.03)', 
                  borderRadius: 8 
                }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>新闻覆盖率</div>
                  <div style={{ fontSize: 24, fontWeight: 600 }}>
                    {analyses.filter(a => a.news_count > 0).length}/{analyses.length}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    ({((analyses.filter(a => a.news_count > 0).length / analyses.length) * 100).toFixed(0)}% 有新闻)
                  </div>
                </div>
              </div>

              {/* 新闻热点股票 */}
              {analyses.filter(a => a.news_count > 0).length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>📊 新闻热度排行</div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {analyses
                      .filter(a => a.news_count > 0)
                      .sort((a, b) => b.news_count - a.news_count)
                      .slice(0, 5)
                      .map(a => {
                        const sentimentColor = (a.news_sentiment_avg || 0.5) >= 0.6 ? '#10b981' : (a.news_sentiment_avg || 0.5) < 0.4 ? '#ef4444' : '#f59e0b'
                        return (
                          <div 
                            key={a.symbol}
                            style={{
                              padding: '6px 12px',
                              background: 'var(--surface)',
                              borderRadius: 6,
                              display: 'flex',
                              alignItems: 'center',
                              gap: 8
                            }}
                          >
                            <span style={{ fontWeight: 500 }}>{a.name || a.symbol}</span>
                            <span style={{ 
                              fontSize: 11, 
                              padding: '2px 6px', 
                              background: 'rgba(59, 130, 246, 0.2)', 
                              borderRadius: 4,
                              color: '#3b82f6'
                            }}>
                              {a.news_count}篇
                            </span>
                            {a.news_sentiment_avg != null && (
                              <span style={{ 
                                width: 8, 
                                height: 8, 
                                borderRadius: '50%', 
                                background: sentimentColor 
                              }} />
                            )}
                          </div>
                        )
                      })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 筛选器 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 14, lineHeight: '32px' }}>筛选:</span>
            {['', 'buy', 'hold', 'sell'].map(rec => (
              <button
                key={rec}
                onClick={() => setFilterRec(rec)}
                style={{
                  padding: '6px 14px',
                  borderRadius: 6,
                  border: filterRec === rec ? 'none' : '1px solid var(--border)',
                  background: filterRec === rec ? 'var(--primary)' : 'transparent',
                  color: filterRec === rec ? '#fff' : 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: 13
                }}
              >
                {rec === '' ? '全部' : rec === 'buy' ? '买入' : rec === 'hold' ? '持有' : '卖出'}
              </button>
            ))}
          </div>

          {/* 股票分析列表 */}
          {loading ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>加载中...</div>
          ) : analyses.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
              暂无分析数据。系统将于每日 18:00 自动执行分析任务。
              {schedulerStatus && (
                <div style={{ marginTop: 8, fontSize: 12 }}>
                  下次分析时间: {new Date(schedulerStatus.next_analysis_time).toLocaleString('zh-CN')}
                </div>
              )}
            </div>
          ) : (
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', 
              gap: 16 
            }}>
              {analyses.map(a => (
                <StockAnalysisCard key={a.symbol} data={a} onClick={() => openStockDetail(a)} />
              ))}
            </div>
          )}
        </>
      )}

      {/* 观察列表 */}
      {activeTab === 'watchlist' && (
        <div>
          {/* 建议移除提示 */}
          {watchlist.filter(w => w.remove_suggested).length > 0 && (
            <div style={{
              padding: 16,
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid #ef4444',
              borderRadius: 8,
              marginBottom: 20
            }}>
              <div style={{ fontWeight: 500, marginBottom: 8, color: '#ef4444' }}>
                ⚠️ 以下股票经长期分析，建议从观察列表中移除：
              </div>
              {watchlist.filter(w => w.remove_suggested).map(w => (
                <div key={w.symbol} style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center',
                  padding: '8px 0',
                  borderBottom: '1px solid rgba(239, 68, 68, 0.2)'
                }}>
                  <div>
                    <span style={{ fontWeight: 500 }}>{w.name || w.symbol}</span>
                    <span style={{ color: 'var(--text-muted)', marginLeft: 8, fontSize: 12 }}>
                      {w.remove_reason}
                    </span>
                  </div>
                  <button
                    onClick={() => confirmRemoval(w.symbol)}
                    style={{
                      padding: '4px 12px',
                      borderRadius: 4,
                      border: '1px solid #ef4444',
                      background: 'transparent',
                      color: '#ef4444',
                      cursor: 'pointer',
                      fontSize: 12
                    }}
                  >
                    确认移除
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 观察列表表格 */}
          <div style={{ 
            background: 'var(--surface-dark)', 
            border: '1px solid var(--border)', 
            borderRadius: 12, 
            overflow: 'hidden' 
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                  <th style={{ padding: '12px 16px', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>股票</th>
                  <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>评分</th>
                  <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>投资潜力</th>
                  <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>来源</th>
                  <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>观察天数</th>
                  <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>状态</th>
                </tr>
              </thead>
              <tbody>
                {watchlist.map(w => (
                  <tr key={w.symbol} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ fontWeight: 500 }}>{w.name || w.symbol}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{w.symbol}</div>
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      {w.score != null ? <ScoreBadge score={w.score} /> : '-'}
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      {w.investment_potential != null ? (
                        <span style={{ 
                          color: w.investment_potential >= 50 ? '#10b981' : '#ef4444',
                          fontWeight: 500
                        }}>
                          {w.investment_potential.toFixed(0)}
                        </span>
                      ) : '-'}
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 11,
                        background: w.source === 'manual' ? 'var(--primary)' : 'var(--surface)',
                        color: '#fff'
                      }}>
                        {w.source === 'manual' ? '手动' : w.source === 'top_movers' ? '涨跌榜' : '推荐'}
                      </span>
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      {w.observation_days} 天
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      {w.remove_suggested ? (
                        <span style={{ color: '#ef4444', fontSize: 12 }}>⚠️ 建议移除</span>
                      ) : w.enabled ? (
                        <span style={{ color: '#10b981', fontSize: 12 }}>✓ 观察中</span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>已禁用</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 历史记录 */}
      {activeTab === 'history' && (
        <div style={{ 
          background: 'var(--surface-dark)', 
          border: '1px solid var(--border)', 
          borderRadius: 12, 
          overflow: 'hidden' 
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                <th style={{ padding: '12px 16px', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>日期</th>
                <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>分析数</th>
                <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>买入</th>
                <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>持有</th>
                <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>卖出</th>
                <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>平均评分</th>
                <th style={{ padding: '12px 16px', textAlign: 'center', color: 'var(--text-muted)', fontWeight: 500, fontSize: 13 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                    暂无历史记录
                  </td>
                </tr>
              ) : (
                history.map(h => (
                  <tr key={h.analysis_date} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: '12px 16px', fontWeight: 500 }}>{h.analysis_date}</td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>{h.total_stocks}</td>
                    <td style={{ padding: '12px 16px', textAlign: 'center', color: '#10b981' }}>{h.buy_count}</td>
                    <td style={{ padding: '12px 16px', textAlign: 'center', color: '#3b82f6' }}>{h.hold_count}</td>
                    <td style={{ padding: '12px 16px', textAlign: 'center', color: '#ef4444' }}>{h.sell_count}</td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>{h.avg_score.toFixed(1)}</td>
                    <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                      <button
                        onClick={() => { setSelectedDate(h.analysis_date); setActiveTab('overview') }}
                        style={{
                          padding: '4px 12px',
                          borderRadius: 4,
                          border: '1px solid var(--primary)',
                          background: 'transparent',
                          color: 'var(--primary)',
                          cursor: 'pointer',
                          fontSize: 12
                        }}
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* 阶段性报告 */}
      {activeTab === 'period' && (
        <div>
          {/* 周期选择器 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            {[
              { key: 'weekly', label: '📅 本周报告' },
              { key: 'monthly', label: '📆 本月报告' },
              { key: 'quarterly', label: '📊 季度报告' },
              { key: 'yearly', label: '📈 年度报告' }
            ].map(p => (
              <button
                key={p.key}
                onClick={() => setPeriodType(p.key as any)}
                style={{
                  padding: '8px 16px',
                  borderRadius: 6,
                  border: periodType === p.key ? 'none' : '1px solid var(--border)',
                  background: periodType === p.key ? 'var(--primary)' : 'transparent',
                  color: periodType === p.key ? '#fff' : 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: 13
                }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {periodLoading ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>加载中...</div>
          ) : !periodReport ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
              暂无该周期的分析数据
            </div>
          ) : (
            <div>
              {/* 报告头部 */}
              <div style={{
                background: 'var(--surface-dark)',
                border: '1px solid var(--border)',
                borderRadius: 12,
                padding: 20,
                marginBottom: 20
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
                    {periodType === 'weekly' ? '本周' : periodType === 'monthly' ? '本月' : periodType === 'quarterly' ? '本季度' : '本年度'}行情总结
                  </h2>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {periodReport.start_date} ~ {periodReport.end_date}
                  </span>
                </div>
                
                {/* 统计卡片 */}
                <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
                  <StatCard title="交易日数" value={periodReport.total_trading_days} />
                  <StatCard title="平均评分" value={periodReport.avg_score.toFixed(1)} />
                  <StatCard 
                    title="评分变化" 
                    value={`${periodReport.score_change >= 0 ? '+' : ''}${periodReport.score_change.toFixed(1)}`}
                    color={periodReport.score_change >= 0 ? '#10b981' : '#ef4444'}
                  />
                  <StatCard title="买入信号" value={periodReport.buy_signals_count} color="#10b981" />
                  <StatCard title="卖出信号" value={periodReport.sell_signals_count} color="#ef4444" />
                </div>
                
                {/* 市场趋势 */}
                <div style={{ 
                  padding: 12, 
                  background: 'var(--surface)', 
                  borderRadius: 8,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12
                }}>
                  <span style={{ fontSize: 24 }}>
                    {periodReport.market_trend === '上升' ? '📈' : periodReport.market_trend === '下降' ? '📉' : '📊'}
                  </span>
                  <div>
                    <div style={{ fontWeight: 500 }}>市场趋势: {periodReport.market_trend}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      信号比 {periodReport.buy_signals_count}:{periodReport.sell_signals_count}
                    </div>
                  </div>
                </div>
              </div>

              {/* 关键洞察 */}
              {periodReport.key_insights.length > 0 && (
                <div style={{
                  background: 'var(--surface-dark)',
                  border: '1px solid var(--border)',
                  borderRadius: 12,
                  padding: 20,
                  marginBottom: 20
                }}>
                  <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>💡 关键洞察</h3>
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    {periodReport.key_insights.map((insight, i) => (
                      <li key={i} style={{ marginBottom: 8, lineHeight: 1.5 }}>{insight}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 风险警告 */}
              {periodReport.risk_warnings.length > 0 && (
                <div style={{
                  background: 'rgba(239, 68, 68, 0.05)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  borderRadius: 12,
                  padding: 20,
                  marginBottom: 20
                }}>
                  <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600, color: '#ef4444' }}>⚠️ 风险警告</h3>
                  <ul style={{ margin: 0, paddingLeft: 20, color: '#ef4444' }}>
                    {periodReport.risk_warnings.map((warning, i) => (
                      <li key={i} style={{ marginBottom: 8, lineHeight: 1.5 }}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 表现最佳/最弱 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
                <div style={{
                  background: 'var(--surface-dark)',
                  border: '1px solid var(--border)',
                  borderRadius: 12,
                  padding: 20
                }}>
                  <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600, color: '#10b981' }}>🏆 表现最佳</h3>
                  {periodReport.top_performers.map((p, i) => (
                    <div key={i} style={{ 
                      display: 'flex', 
                      justifyContent: 'space-between', 
                      padding: '8px 0',
                      borderBottom: i < periodReport.top_performers.length - 1 ? '1px solid var(--border)' : 'none'
                    }}>
                      <span>{p.name || p.symbol}</span>
                      <span style={{ color: '#10b981' }}>评分 {p.avg_score}</span>
                    </div>
                  ))}
                </div>
                <div style={{
                  background: 'var(--surface-dark)',
                  border: '1px solid var(--border)',
                  borderRadius: 12,
                  padding: 20
                }}>
                  <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600, color: '#ef4444' }}>📉 表现最弱</h3>
                  {periodReport.worst_performers.map((p, i) => (
                    <div key={i} style={{ 
                      display: 'flex', 
                      justifyContent: 'space-between', 
                      padding: '8px 0',
                      borderBottom: i < periodReport.worst_performers.length - 1 ? '1px solid var(--border)' : 'none'
                    }}>
                      <span>{p.name || p.symbol}</span>
                      <span style={{ color: '#ef4444' }}>评分 {p.avg_score}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* 综合分析 */}
              <div style={{
                background: 'var(--surface-dark)',
                border: '1px solid var(--border)',
                borderRadius: 12,
                padding: 20
              }}>
                <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>📝 综合分析</h3>
                <div style={{ 
                  whiteSpace: 'pre-wrap', 
                  lineHeight: 1.8,
                  fontSize: 14
                }}>
                  {periodReport.comprehensive_analysis}
                </div>
                <div style={{ marginTop: 16, fontSize: 11, color: 'var(--text-muted)' }}>
                  生成时间: {new Date(periodReport.generated_at).toLocaleString('zh-CN')}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 股票详情弹窗 */}
      {selectedStock && (
        <div 
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.7)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 1000,
            padding: 20
          }}
          onClick={() => setSelectedStock(null)}
        >
          <div 
            style={{
              background: 'var(--surface-dark)',
              borderRadius: 16,
              maxWidth: 800,
              maxHeight: '90vh',
              width: '100%',
              overflow: 'auto',
              padding: 24
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* 头部 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
              <div>
                <h2 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>
                  {selectedStock.name || selectedStock.symbol}
                </h2>
                <div style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 4 }}>
                  {selectedStock.symbol} · {selectedStock.sector || '未分类'}
                </div>
              </div>
              <button 
                onClick={() => setSelectedStock(null)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  fontSize: 24,
                  cursor: 'pointer',
                  color: 'var(--text-muted)'
                }}
              >
                ×
              </button>
            </div>

            {/* 评分和建议 */}
            <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 12,
                padding: 16,
                flex: 1,
                minWidth: 150
              }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>综合评分</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <ScoreBadge score={selectedStock.scores.total} size="large" />
                  <div>
                    <RecommendationBadge type={selectedStock.recommendation} />
                    <div style={{ marginTop: 6 }}>
                      <RiskBadge level={selectedStock.risk_level} />
                    </div>
                  </div>
                </div>
              </div>
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 12,
                padding: 16,
                flex: 1,
                minWidth: 150
              }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>价格信息</div>
                <div style={{ fontSize: 20, fontWeight: 600 }}>¥{selectedStock.close_price?.toFixed(2) || '-'}</div>
                <div style={{ 
                  color: (selectedStock.pct_change || 0) >= 0 ? '#10b981' : '#ef4444',
                  fontSize: 14, 
                  fontWeight: 500 
                }}>
                  {selectedStock.pct_change != null ? `${selectedStock.pct_change >= 0 ? '+' : ''}${selectedStock.pct_change.toFixed(2)}%` : '-'}
                </div>
              </div>
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 12,
                padding: 16,
                flex: 1,
                minWidth: 150
              }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>置信度说明</div>
                <div style={{ fontSize: 20, fontWeight: 600 }}>{(selectedStock.confidence * 100).toFixed(0)}%</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {selectedStock.confidence >= 0.7 ? '高置信度分析' : selectedStock.confidence >= 0.4 ? '中等置信度' : '低置信度，需谨慎'}
                </div>
              </div>
            </div>

            {/* 评分明细 */}
            <div style={{
              background: 'rgba(255,255,255,0.03)',
              borderRadius: 12,
              padding: 16,
              marginBottom: 20
            }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>📊 评分明细</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
                {[
                  { label: '技术面', value: selectedStock.scores.technical, desc: '趋势/动量/形态' },
                  { label: '基本面', value: selectedStock.scores.fundamental, desc: '财务/估值/成长' },
                  { label: '情绪面', value: selectedStock.scores.sentiment, desc: '新闻/舆情/热度' },
                  { label: '资金面', value: selectedStock.scores.fund_flow, desc: '资金流入/主力' },
                  { label: '周期性', value: selectedStock.scores.cycle, desc: '季节/行业周期' }
                ].map(item => (
                  <div key={item.label} style={{ 
                    padding: 10, 
                    background: 'var(--surface-dark)', 
                    borderRadius: 8,
                    border: '1px solid var(--border)'
                  }}>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{item.label}</div>
                    <div style={{ 
                      fontSize: 18, 
                      fontWeight: 600,
                      color: item.value >= 60 ? '#10b981' : item.value >= 40 ? '#f59e0b' : '#ef4444'
                    }}>
                      {item.value.toFixed(0)}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{item.desc}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* 分析摘要 */}
            {selectedStock.analysis_summary && (
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 12,
                padding: 16,
                marginBottom: 20
              }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>📝 分析摘要</div>
                <div style={{ fontSize: 14, lineHeight: 1.8, color: 'var(--text)' }}>
                  {selectedStock.analysis_summary}
                </div>
              </div>
            )}

            {/* 关键因素 */}
            {selectedStock.key_factors && selectedStock.key_factors.length > 0 && (
              <div style={{
                background: 'rgba(16, 185, 129, 0.1)',
                borderRadius: 12,
                padding: 16,
                marginBottom: 20
              }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: '#10b981' }}>✅ 核心看点</div>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {selectedStock.key_factors.map((factor, i) => (
                    <li key={i} style={{ fontSize: 14, lineHeight: 1.8, color: 'var(--text)' }}>{factor}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* 风险因素 */}
            {selectedStock.risk_factors && selectedStock.risk_factors.length > 0 && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)',
                borderRadius: 12,
                padding: 16,
                marginBottom: 20
              }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: '#ef4444' }}>⚠️ 风险提示</div>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {selectedStock.risk_factors.map((factor, i) => (
                    <li key={i} style={{ fontSize: 14, lineHeight: 1.8, color: 'var(--text)' }}>{factor}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* 相关新闻 */}
            <div style={{
              background: 'rgba(255,255,255,0.03)',
              borderRadius: 12,
              padding: 16
            }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
                📰 相关新闻 ({selectedStock.news_count}篇)
                {selectedStock.news_sentiment_avg != null && (
                  <span style={{ 
                    marginLeft: 12, 
                    fontSize: 12, 
                    color: selectedStock.news_sentiment_avg >= 0.6 ? '#10b981' : selectedStock.news_sentiment_avg < 0.4 ? '#ef4444' : '#f59e0b'
                  }}>
                    情绪: {selectedStock.news_sentiment_avg >= 0.6 ? '乐观' : selectedStock.news_sentiment_avg < 0.4 ? '悲观' : '中性'} ({(selectedStock.news_sentiment_avg * 100).toFixed(0)}%)
                  </span>
                )}
              </div>
              
              {newsLoading ? (
                <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>加载新闻中...</div>
              ) : stockNews.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {stockNews.map((news, i) => (
                    <div 
                      key={i}
                      style={{
                        padding: 12,
                        background: 'var(--surface-dark)',
                        borderRadius: 8,
                        border: '1px solid var(--border)'
                      }}
                    >
                      <a 
                        href={news.url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        style={{ 
                          color: 'var(--text)', 
                          textDecoration: 'none',
                          fontWeight: 500,
                          fontSize: 14
                        }}
                      >
                        {news.title}
                      </a>
                      <div style={{ 
                        display: 'flex', 
                        gap: 12, 
                        marginTop: 8, 
                        fontSize: 12, 
                        color: 'var(--text-muted)' 
                      }}>
                        <span>{news.source || '未知来源'}</span>
                        <span>{news.published_at ? new Date(news.published_at).toLocaleDateString('zh-CN') : ''}</span>
                        {news.sentiment_score != null && (
                          <span style={{ 
                            color: news.sentiment_score >= 0.6 ? '#10b981' : news.sentiment_score < 0.4 ? '#ef4444' : '#f59e0b'
                          }}>
                            情感: {(news.sentiment_score * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      {news.summary && (
                        <div style={{ 
                          fontSize: 13, 
                          color: 'var(--text-muted)', 
                          marginTop: 8,
                          lineHeight: 1.6
                        }}>
                          {news.summary.slice(0, 150)}...
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>
                  暂无相关新闻数据
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
