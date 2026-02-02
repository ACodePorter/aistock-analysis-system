/**
 * 新闻中心页面
 * 
 * 功能：
 * - 展示每日抓取的新闻列表
 * - 支持按时间、行业、情绪筛选
 * - 支持关键词搜索
 * - 支持多种排序方式
 */
import React, { useState, useEffect, useCallback } from 'react'
import { 
  fetchNewsArticles, 
  fetchNewsSectors, 
  fetchNewsStats,
  NewsArticle, 
  NewsListParams,
  NewsSector,
  NewsStatsResponse 
} from '../api/news'

// 情绪标签组件
function SentimentBadge({ type }: { type: string | null }) {
  const config: Record<string, { label: string; color: string; bg: string }> = {
    positive: { label: '利好', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' },
    negative: { label: '利空', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' },
    neutral: { label: '中性', color: '#6b7280', bg: 'rgba(107, 114, 128, 0.15)' }
  }
  
  const c = type && config[type] ? config[type] : config.neutral
  
  return (
    <span style={{
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 500,
      color: c.color,
      background: c.bg
    }}>
      {c.label}
    </span>
  )
}

// 统计卡片组件
function StatCard({ title, value, color }: { title: string; value: string | number; color?: string }) {
  return (
    <div style={{
      background: 'var(--surface-dark)',
      border: '1px solid var(--border)',
      borderRadius: 8,
      padding: '12px 16px',
      minWidth: 100,
      textAlign: 'center'
    }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: color || 'var(--text)' }}>{value}</div>
    </div>
  )
}

// 新闻卡片组件
function NewsCard({ article, onClick }: { article: NewsArticle; onClick?: () => void }) {
  const publishedDate = article.published_at 
    ? new Date(article.published_at).toLocaleDateString('zh-CN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      })
    : '未知时间'
  
  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--surface-dark)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 16,
        cursor: onClick ? 'pointer' : 'default',
        transition: 'border-color 0.2s'
      }}
      onMouseEnter={e => {
        if (onClick) e.currentTarget.style.borderColor = 'var(--primary)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = 'var(--border)'
      }}
    >
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <h3 style={{ 
          margin: 0, 
          fontSize: 14, 
          fontWeight: 500, 
          lineHeight: 1.4,
          flex: 1,
          marginRight: 12,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical'
        }}>
          {article.title}
        </h3>
        <SentimentBadge type={article.sentiment_type} />
      </div>
      
      {/* 摘要 */}
      {article.summary && (
        <p style={{
          margin: '0 0 12px',
          fontSize: 12,
          color: 'var(--text-muted)',
          lineHeight: 1.5,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical'
        }}>
          {article.summary}
        </p>
      )}
      
      {/* 元信息 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: 'var(--text-muted)' }}>
        <div style={{ display: 'flex', gap: 12 }}>
          <span>{article.source || '未知来源'}</span>
          <span>{publishedDate}</span>
        </div>
        {article.related_stocks && article.related_stocks.length > 0 && (
          <div style={{ display: 'flex', gap: 4 }}>
            {article.related_stocks.slice(0, 3).map(s => (
              <span 
                key={s} 
                style={{ 
                  padding: '1px 6px', 
                  background: 'var(--surface)', 
                  borderRadius: 4,
                  fontSize: 10
                }}
              >
                {s}
              </span>
            ))}
            {article.related_stocks.length > 3 && (
              <span style={{ fontSize: 10 }}>+{article.related_stocks.length - 3}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// 筛选器组件
function FilterBar({
  sectors,
  selectedSector,
  selectedSentiment,
  selectedDays,
  keyword,
  sortBy,
  onSectorChange,
  onSentimentChange,
  onDaysChange,
  onKeywordChange,
  onSortChange
}: {
  sectors: NewsSector[]
  selectedSector: string
  selectedSentiment: string
  selectedDays: number
  keyword: string
  sortBy: string
  onSectorChange: (v: string) => void
  onSentimentChange: (v: string) => void
  onDaysChange: (v: number) => void
  onKeywordChange: (v: string) => void
  onSortChange: (v: string) => void
}) {
  const selectStyle: React.CSSProperties = {
    padding: '6px 10px',
    borderRadius: 6,
    border: '1px solid var(--border)',
    background: 'var(--surface-dark)',
    color: 'var(--text)',
    fontSize: 13,
    cursor: 'pointer'
  }
  
  const inputStyle: React.CSSProperties = {
    padding: '6px 10px',
    borderRadius: 6,
    border: '1px solid var(--border)',
    background: 'var(--surface-dark)',
    color: 'var(--text)',
    fontSize: 13,
    width: 180
  }
  
  return (
    <div style={{ 
      display: 'flex', 
      flexWrap: 'wrap', 
      gap: 12, 
      padding: 16,
      background: 'var(--surface)',
      borderRadius: 8,
      marginBottom: 16
    }}>
      {/* 关键词搜索 */}
      <input
        type="text"
        placeholder="搜索关键词..."
        value={keyword}
        onChange={e => onKeywordChange(e.target.value)}
        style={inputStyle}
      />
      
      {/* 行业筛选 */}
      <select value={selectedSector} onChange={e => onSectorChange(e.target.value)} style={selectStyle}>
        <option value="">全部行业</option>
        {sectors.map(s => (
          <option key={s.sector} value={s.sector}>
            {s.sector} ({s.news_count})
          </option>
        ))}
      </select>
      
      {/* 情绪筛选 */}
      <select value={selectedSentiment} onChange={e => onSentimentChange(e.target.value)} style={selectStyle}>
        <option value="">全部情绪</option>
        <option value="positive">利好</option>
        <option value="negative">利空</option>
        <option value="neutral">中性</option>
      </select>
      
      {/* 时间范围 */}
      <select value={selectedDays} onChange={e => onDaysChange(Number(e.target.value))} style={selectStyle}>
        <option value={1}>今天</option>
        <option value={3}>近3天</option>
        <option value={7}>近7天</option>
        <option value={14}>近14天</option>
        <option value={30}>近30天</option>
      </select>
      
      {/* 排序方式 */}
      <select value={sortBy} onChange={e => onSortChange(e.target.value)} style={selectStyle}>
        <option value="time">按时间</option>
        <option value="relevance">按相关性</option>
        <option value="sentiment">按情绪</option>
      </select>
    </div>
  )
}

// 主页面组件
export default function NewsListPage() {
  const [articles, setArticles] = useState<NewsArticle[]>([])
  const [sectors, setSectors] = useState<NewsSector[]>([])
  const [stats, setStats] = useState<NewsStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  // 筛选状态
  const [selectedSector, setSelectedSector] = useState('')
  const [selectedSentiment, setSelectedSentiment] = useState('')
  const [selectedDays, setSelectedDays] = useState(7)
  const [keyword, setKeyword] = useState('')
  const [sortBy, setSortBy] = useState('time')
  
  // 分页状态
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(true)
  const [total, setTotal] = useState(0)
  const limit = 20
  
  // 详情弹窗
  const [selectedArticle, setSelectedArticle] = useState<NewsArticle | null>(null)
  
  // 加载行业列表和统计
  useEffect(() => {
    Promise.all([
      fetchNewsSectors(30),
      fetchNewsStats()
    ]).then(([sectorsData, statsData]) => {
      setSectors(sectorsData.sectors)
      setStats(statsData)
    }).catch(console.error)
  }, [])
  
  // 加载新闻列表
  const loadArticles = useCallback(async (reset: boolean = false) => {
    setLoading(true)
    setError(null)
    
    const currentOffset = reset ? 0 : offset
    
    const params: NewsListParams = {
      limit,
      offset: currentOffset,
      days: selectedDays,
      sort_by: sortBy as any,
      sort_order: 'desc'
    }
    
    if (selectedSector) params.sector = selectedSector
    if (selectedSentiment) params.sentiment = selectedSentiment
    if (keyword.trim()) params.keyword = keyword.trim()
    
    try {
      const result = await fetchNewsArticles(params)
      
      if (reset) {
        setArticles(result.articles)
        setOffset(limit)
      } else {
        setArticles(prev => [...prev, ...result.articles])
        setOffset(currentOffset + limit)
      }
      
      setTotal(result.total)
      setHasMore(result.has_more)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [selectedSector, selectedSentiment, selectedDays, keyword, sortBy, offset])
  
  // 筛选变化时重新加载
  useEffect(() => {
    loadArticles(true)
  }, [selectedSector, selectedSentiment, selectedDays, sortBy])
  
  // 关键词搜索延迟
  useEffect(() => {
    const timer = setTimeout(() => {
      if (keyword !== undefined) {
        loadArticles(true)
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [keyword])
  
  return (
    <div style={{ padding: 20, maxWidth: 1200, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>📰 新闻中心</h1>
        <p style={{ margin: '8px 0 0', color: 'var(--text-muted)', fontSize: 14 }}>
          实时追踪市场新闻动态，按行业、情绪筛选分析
        </p>
      </div>
      
      {/* 统计卡片 */}
      {stats && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
          <StatCard title="今日新闻" value={stats.today_articles} />
          <StatCard title="总新闻数" value={stats.total_articles} />
          <StatCard title="利好占比" value={`${stats.positive_sentiment}%`} color="#10b981" />
          <StatCard title="利空占比" value={`${stats.negative_sentiment}%`} color="#ef4444" />
          <StatCard title="中性占比" value={`${stats.neutral_sentiment}%`} color="#6b7280" />
        </div>
      )}
      
      {/* 筛选器 */}
      <FilterBar
        sectors={sectors}
        selectedSector={selectedSector}
        selectedSentiment={selectedSentiment}
        selectedDays={selectedDays}
        keyword={keyword}
        sortBy={sortBy}
        onSectorChange={v => setSelectedSector(v)}
        onSentimentChange={v => setSelectedSentiment(v)}
        onDaysChange={v => setSelectedDays(v)}
        onKeywordChange={v => setKeyword(v)}
        onSortChange={v => setSortBy(v)}
      />
      
      {/* 结果统计 */}
      <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--text-muted)' }}>
        共 {total} 条新闻
        {selectedSector && ` · 行业: ${selectedSector}`}
        {selectedSentiment && ` · 情绪: ${selectedSentiment === 'positive' ? '利好' : selectedSentiment === 'negative' ? '利空' : '中性'}`}
      </div>
      
      {/* 错误提示 */}
      {error && (
        <div style={{
          padding: 16,
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid #ef4444',
          borderRadius: 8,
          color: '#ef4444',
          marginBottom: 16
        }}>
          {error}
        </div>
      )}
      
      {/* 新闻列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {articles.map(article => (
          <NewsCard
            key={article.id}
            article={article}
            onClick={() => setSelectedArticle(article)}
          />
        ))}
      </div>
      
      {/* 加载中 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>
          加载中...
        </div>
      )}
      
      {/* 加载更多 */}
      {!loading && hasMore && (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <button
            onClick={() => loadArticles(false)}
            style={{
              padding: '10px 24px',
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: 'var(--surface-dark)',
              color: 'var(--text)',
              cursor: 'pointer',
              fontSize: 14
            }}
          >
            加载更多
          </button>
        </div>
      )}
      
      {/* 没有更多 */}
      {!loading && !hasMore && articles.length > 0 && (
        <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)', fontSize: 13 }}>
          已加载全部新闻
        </div>
      )}
      
      {/* 空状态 */}
      {!loading && articles.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
          暂无符合条件的新闻
        </div>
      )}
      
      {/* 新闻详情弹窗 */}
      {selectedArticle && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 20
          }}
          onClick={() => setSelectedArticle(null)}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: 'var(--surface)',
              borderRadius: 12,
              maxWidth: 700,
              maxHeight: '80vh',
              overflow: 'auto',
              padding: 24,
              position: 'relative'
            }}
          >
            {/* 关闭按钮 */}
            <button
              onClick={() => setSelectedArticle(null)}
              style={{
                position: 'absolute',
                top: 12,
                right: 12,
                background: 'none',
                border: 'none',
                fontSize: 20,
                cursor: 'pointer',
                color: 'var(--text-muted)'
              }}
            >
              ✕
            </button>
            
            {/* 标题 */}
            <h2 style={{ margin: '0 0 16px', fontSize: 18, fontWeight: 600, paddingRight: 32 }}>
              {selectedArticle.title}
            </h2>
            
            {/* 元信息 */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, fontSize: 13, color: 'var(--text-muted)' }}>
              <span>{selectedArticle.source || '未知来源'}</span>
              <span>
                {selectedArticle.published_at 
                  ? new Date(selectedArticle.published_at).toLocaleString('zh-CN')
                  : '未知时间'
                }
              </span>
              <SentimentBadge type={selectedArticle.sentiment_type} />
            </div>
            
            {/* 关联股票 */}
            {selectedArticle.related_stocks && selectedArticle.related_stocks.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)', marginRight: 8 }}>关联股票:</span>
                {selectedArticle.related_stocks.map(s => (
                  <span
                    key={s}
                    style={{
                      display: 'inline-block',
                      padding: '2px 8px',
                      background: 'var(--surface-dark)',
                      borderRadius: 4,
                      fontSize: 12,
                      marginRight: 6,
                      marginBottom: 4
                    }}
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}
            
            {/* 摘要 */}
            <div style={{ 
              padding: 16, 
              background: 'var(--surface-dark)', 
              borderRadius: 8, 
              marginBottom: 16,
              lineHeight: 1.6
            }}>
              {selectedArticle.summary}
            </div>
            
            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 12 }}>
              <a
                href={selectedArticle.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  padding: '8px 16px',
                  borderRadius: 6,
                  background: 'var(--primary)',
                  color: '#fff',
                  textDecoration: 'none',
                  fontSize: 13
                }}
              >
                查看原文 →
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
