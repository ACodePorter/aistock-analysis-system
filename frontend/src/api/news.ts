/**
 * 新闻相关 API
 */
import { API_BASE } from '../config/api'

export interface NewsArticle {
  id: number
  title: string
  url: string
  summary: string
  content?: string
  published_at: string | null
  source: string | null
  category: string | null
  sentiment_type: 'positive' | 'negative' | 'neutral' | null
  sentiment_score: number | null
  relevance_score: number | null
  related_stocks: string[] | null
  keywords: string[] | null
}

export interface NewsListResponse {
  articles: NewsArticle[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface NewsSector {
  sector: string
  stock_count: number
  news_count: number
  sentiment_distribution: {
    positive: number
    negative: number
    neutral: number
  }
  dominant_sentiment: string
}

export interface NewsSectorsResponse {
  period_days: number
  sectors: NewsSector[]
  total_sectors: number
}

export interface NewsStatsResponse {
  total_articles: number
  today_articles: number
  positive_sentiment: number
  negative_sentiment: number
  neutral_sentiment: number
  top_sources: { source: string; count: number }[]
  top_stocks: { stock: string; count: number }[]
}

export interface NewsListParams {
  category?: string
  sentiment?: string
  symbol?: string
  sector?: string
  keyword?: string
  limit?: number
  offset?: number
  days?: number
  start_date?: string
  end_date?: string
  sort_by?: 'time' | 'relevance' | 'sentiment'
  sort_order?: 'asc' | 'desc'
  include_content?: boolean
}

async function fetchJSON<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Accept': 'application/json' }
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API Error ${res.status}: ${text}`)
  }
  return res.json()
}

/**
 * 获取新闻文章列表
 */
export async function fetchNewsArticles(params: NewsListParams = {}): Promise<NewsListResponse> {
  const queryParams = new URLSearchParams()
  
  if (params.category) queryParams.append('category', params.category)
  if (params.sentiment) queryParams.append('sentiment', params.sentiment)
  if (params.symbol) queryParams.append('symbol', params.symbol)
  if (params.sector) queryParams.append('sector', params.sector)
  if (params.keyword) queryParams.append('keyword', params.keyword)
  if (params.limit) queryParams.append('limit', String(params.limit))
  if (params.offset) queryParams.append('offset', String(params.offset))
  if (params.days) queryParams.append('days', String(params.days))
  if (params.start_date) queryParams.append('start_date', params.start_date)
  if (params.end_date) queryParams.append('end_date', params.end_date)
  if (params.sort_by) queryParams.append('sort_by', params.sort_by)
  if (params.sort_order) queryParams.append('sort_order', params.sort_order)
  if (params.include_content) queryParams.append('include_content', 'true')
  
  const queryString = queryParams.toString()
  return fetchJSON<NewsListResponse>(`/api/news/articles${queryString ? `?${queryString}` : ''}`)
}

/**
 * 获取新闻行业分布
 */
export async function fetchNewsSectors(days: number = 7): Promise<NewsSectorsResponse> {
  return fetchJSON<NewsSectorsResponse>(`/api/news/sectors?days=${days}`)
}

/**
 * 获取新闻统计
 */
export async function fetchNewsStats(): Promise<NewsStatsResponse> {
  return fetchJSON<NewsStatsResponse>('/api/news/stats')
}
