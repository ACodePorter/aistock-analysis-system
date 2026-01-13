import React, { useState, useEffect } from 'react'
import { API_BASE, buildApiUrl, API_ENDPOINTS } from '../config/api'

interface StockProfile {
  symbol: string
  company_name: string
  industry: string
  sub_industry?: string
  products?: string
  competitors?: string
  risk_factors?: string
  business_summary?: string
  strategic_keywords?: string
  market_cap?: number
  pe_ratio?: number
  pb_ratio?: number
  roe?: number
  last_refreshed?: string
}

interface CompanyMetrics {
  totalProducts: number
  competitorCount: number
  riskFactorCount: number
  industryRank?: string
  marketPosition?: string
}

interface StockProfileCardProps {
  symbol: string
  onRefresh?: () => void
}

export default function StockProfileCard({ symbol, onRefresh }: StockProfileCardProps) {
  const [profile, setProfile] = useState<StockProfile | null>(null)
  const [metrics, setMetrics] = useState<CompanyMetrics | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadProfile = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const url = buildApiUrl(API_ENDPOINTS.STOCK_POOL.PROFILE(symbol))
      const response = await fetch(url)
      
      if (response.status === 404) {
        setProfile(null)
        setError('Profile not found')
        return
      }
      
      if (!response.ok) {
        throw new Error(`Failed to fetch profile: ${response.statusText}`)
      }
      
      const data = await response.json()
      setProfile(data)
      
      // Calculate metrics
      const compMetrics: CompanyMetrics = {
        totalProducts: data.products ? data.products.split(/[,，;；、]/).filter((p: string) => p.trim()).length : 0,
        competitorCount: data.competitors ? data.competitors.split(/[,，;；、]/).filter((c: string) => c.trim()).length : 0,
        riskFactorCount: data.risk_factors ? data.risk_factors.split(/[,，;；、]/).filter((r: string) => r.trim()).length : 0,
      }
      setMetrics(compMetrics)
    } catch (e: any) {
      setError(e.message || 'Failed to load profile')
      console.error('Profile loading error:', e)
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    loadProfile()
  }, [loadProfile])

  const handleRefresh = async () => {
    try {
      const url = buildApiUrl(API_ENDPOINTS.STOCK_POOL.PROFILE_REFRESH(symbol))
      const response = await fetch(url, { method: 'POST' })
      if (!response.ok) throw new Error('Refresh failed')
      await loadProfile()
      onRefresh?.()
    } catch (e: any) {
      setError(e.message || 'Failed to refresh profile')
    }
  }

  if (loading && !profile) {
    return (
      <div style={{
        padding: 16,
        border: '1px solid #e5e7eb',
        borderRadius: 8,
        background: '#f9fafb'
      }}>
        <div style={{ color: '#9ca3af', textAlign: 'center' }}>Loading profile...</div>
      </div>
    )
  }

  if (error && !profile) {
    return (
      <div style={{
        padding: 16,
        border: '1px solid #fee2e2',
        borderRadius: 8,
        background: '#fef2f2'
      }}>
        <div style={{ color: '#991b1b' }}>Error: {error}</div>
        <button 
          onClick={handleRefresh}
          style={{
            marginTop: 8,
            padding: '6px 12px',
            border: '1px solid #fca5a5',
            borderRadius: 6,
            background: '#fff',
            color: '#dc2626',
            cursor: 'pointer'
          }}
        >
          Retry
        </button>
      </div>
    )
  }

  if (!profile) {
    return (
      <div style={{
        padding: 16,
        border: '1px solid #e5e7eb',
        borderRadius: 8,
        background: '#f9fafb'
      }}>
        <div style={{ color: '#9ca3af' }}>No profile data available</div>
      </div>
    )
  }

  return (
    <div style={{
      border: '1px solid #e5e7eb',
      borderRadius: 8,
      background: '#fff',
      overflow: 'hidden'
    }}>
      {/* Header */}
      <div style={{
        padding: 12,
        borderBottom: '1px solid #e5e7eb',
        background: '#f8fafc',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        cursor: 'pointer'
      }} onClick={() => setExpanded(!expanded)}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>
          📊 公司画像 - {profile.company_name || symbol}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={(e) => {
              e.stopPropagation()
              handleRefresh()
            }}
            style={{
              padding: '4px 8px',
              border: '1px solid #d1d5db',
              borderRadius: 4,
              background: '#fff',
              fontSize: 12,
              cursor: 'pointer'
            }}
          >
            🔄
          </button>
          <span style={{ fontSize: 12, color: '#6b7280' }}>
            {expanded ? '▼' : '▶'}
          </span>
        </div>
      </div>

      {expanded && (
        <>
          {/* Basic Information */}
          <div style={{ padding: 12, borderBottom: '1px solid #e5e7eb' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 8 }}>
              基本信息
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 8,
              fontSize: 13
            }}>
              <div>
                <span style={{ color: '#6b7280' }}>公司名称</span>
                <div style={{ fontWeight: 500 }}>{profile.company_name || '-'}</div>
              </div>
              <div>
                <span style={{ color: '#6b7280' }}>行业</span>
                <div style={{ fontWeight: 500 }}>
                  {profile.industry || '-'}
                  {profile.sub_industry ? ` / ${profile.sub_industry}` : ''}
                </div>
              </div>
            </div>
          </div>

          {/* Key Metrics */}
          {metrics && (
            <div style={{ padding: 12, borderBottom: '1px solid #e5e7eb' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 8 }}>
                关键指标
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: 8
              }}>
                <div style={{
                  padding: 8,
                  background: '#f0f9ff',
                  borderRadius: 6,
                  border: '1px solid #bfdbfe',
                  fontSize: 12
                }}>
                  <div style={{ color: '#6b7280', fontSize: 11 }}>主要产品</div>
                  <div style={{ fontWeight: 600, fontSize: 16, color: '#1e40af' }}>
                    {metrics.totalProducts}
                  </div>
                </div>
                <div style={{
                  padding: 8,
                  background: '#fef2f2',
                  borderRadius: 6,
                  border: '1px solid #fecaca',
                  fontSize: 12
                }}>
                  <div style={{ color: '#6b7280', fontSize: 11 }}>竞争对手</div>
                  <div style={{ fontWeight: 600, fontSize: 16, color: '#dc2626' }}>
                    {metrics.competitorCount}
                  </div>
                </div>
                <div style={{
                  padding: 8,
                  background: '#fef3c7',
                  borderRadius: 6,
                  border: '1px solid #fcd34d',
                  fontSize: 12
                }}>
                  <div style={{ color: '#6b7280', fontSize: 11 }}>风险因素</div>
                  <div style={{ fontWeight: 600, fontSize: 16, color: '#b45309' }}>
                    {metrics.riskFactorCount}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Business Summary */}
          {profile.business_summary && (
            <div style={{ padding: 12, borderBottom: '1px solid #e5e7eb' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 6 }}>
                业务介绍
              </div>
              <div style={{
                fontSize: 13,
                lineHeight: 1.6,
                color: '#334155',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word'
              }}>
                {profile.business_summary}
              </div>
            </div>
          )}

          {/* Strategic Keywords */}
          {profile.strategic_keywords && (
            <div style={{ padding: 12, borderBottom: '1px solid #e5e7eb' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 6 }}>
                战略关键词
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.strategic_keywords.split(/[,，;；、]/).map((kw, i) => (
                  kw.trim() && (
                    <span key={i} style={{
                      padding: '3px 8px',
                      background: '#dbeafe',
                      color: '#1e40af',
                      borderRadius: 4,
                      fontSize: 12,
                      border: '1px solid #bfdbfe'
                    }}>
                      {kw.trim()}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Products */}
          {profile.products && (
            <div style={{ padding: 12, borderBottom: '1px solid #e5e7eb' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 6 }}>
                主要产品
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.products.split(/[,，;；、]/).map((prod, i) => (
                  prod.trim() && (
                    <span key={i} style={{
                      padding: '4px 10px',
                      background: '#ecfdf5',
                      color: '#065f46',
                      borderRadius: 4,
                      fontSize: 12,
                      border: '1px solid #a7f3d0'
                    }}>
                      {prod.trim()}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Competitors */}
          {profile.competitors && (
            <div style={{ padding: 12, borderBottom: '1px solid #e5e7eb' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 6 }}>
                竞争对手
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.competitors.split(/[,，;；、]/).map((comp, i) => (
                  comp.trim() && (
                    <span key={i} style={{
                      padding: '4px 10px',
                      background: '#fef3c7',
                      color: '#b45309',
                      borderRadius: 4,
                      fontSize: 12,
                      border: '1px solid #fcd34d'
                    }}>
                      {comp.trim()}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Risk Factors */}
          {profile.risk_factors && (
            <div style={{ padding: 12, borderBottom: '1px solid #e5e7eb' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#4b5563', marginBottom: 6 }}>
                风险因素
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.risk_factors.split(/[,，;；、]/).map((risk, i) => (
                  risk.trim() && (
                    <span key={i} style={{
                      padding: '4px 10px',
                      background: '#fee2e2',
                      color: '#991b1b',
                      borderRadius: 4,
                      fontSize: 12,
                      border: '1px solid #fca5a5'
                    }}>
                      {risk.trim()}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div style={{
            padding: 8,
            background: '#f9fafb',
            fontSize: 11,
            color: '#9ca3af',
            display: 'flex',
            justifyContent: 'space-between'
          }}>
            <span>最后更新: {profile.last_refreshed ? new Date(profile.last_refreshed).toLocaleString('zh-CN') : '未知'}</span>
            <span>Symbol: {profile.symbol}</span>
          </div>
        </>
      )}
    </div>
  )
}
