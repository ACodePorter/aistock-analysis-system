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
      <div className="card-panel" style={{ padding: 16 }}>
        <div className="text-muted" style={{ textAlign: 'center' }}>Loading profile...</div>
      </div>
    )
  }

  if (error && !profile) {
    return (
      <div className="card-panel" style={{ padding: 16 }}>
        <div style={{ color: 'var(--danger)' }}>Error: {error}</div>
        <button onClick={handleRefresh} className="dark-btn dark-btn-secondary" style={{ marginTop: 8 }}>Retry</button>
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="card-panel" style={{ padding: 16 }}>
        <div className="text-muted">No profile data available</div>
      </div>
    )
  }

  return (
    <div className="card-panel stock-profile-card">
      {/* Header */}
      <div className="card-header" onClick={() => setExpanded(!expanded)}>
        <div className="card-title">📊 公司画像 - {profile.company_name || symbol}</div>
        <div className="card-actions">
          <button
            onClick={(e) => {
              e.stopPropagation()
              handleRefresh()
            }}
            className="dark-btn dark-btn-ghost"
            aria-label="refresh"
          >
            🔄
          </button>
          <span style={{color: 'var(--text-muted)'}}>{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {expanded && (
        <>
          {/* Basic Information */}
          <div style={{ padding: 12, borderBottom: '1px solid var(--border-dark)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>
              基本信息
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 8,
              fontSize: 13
            }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>公司名称</span>
                <div style={{ fontWeight: 500 }}>{profile.company_name || '-'}</div>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>行业</span>
                <div style={{ fontWeight: 500 }}>
                  {profile.industry || '-'}
                  {profile.sub_industry ? ` / ${profile.sub_industry}` : ''}
                </div>
              </div>
            </div>
          </div>

          {/* Key Metrics */}
          {metrics && (
            <div style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>
                关键指标
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: 8
              }}>
                <div style={{
                  padding: 8,
                  background: 'rgba(59, 130, 246, 0.1)',
                  borderRadius: 6,
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  fontSize: 12
                }}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>主要产品</div>
                  <div style={{ fontWeight: 600, fontSize: 16, color: '#3b82f6' }}>
                    {metrics.totalProducts}
                  </div>
                </div>
                <div style={{
                  padding: 8,
                  background: 'rgba(239, 68, 68, 0.1)',
                  borderRadius: 6,
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  fontSize: 12
                }}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>竞争对手</div>
                  <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--accent-red)' }}>
                    {metrics.competitorCount}
                  </div>
                </div>
                <div style={{
                  padding: 8,
                  background: 'rgba(245, 158, 11, 0.1)',
                  borderRadius: 6,
                  border: '1px solid rgba(245, 158, 11, 0.3)',
                  fontSize: 12
                }}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>风险因素</div>
                  <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--accent-amber)' }}>
                    {metrics.riskFactorCount}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Business Summary */}
          {profile.business_summary && (
            <div style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                业务介绍
              </div>
              <div style={{
                fontSize: 13,
                lineHeight: 1.6,
                color: 'var(--text)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word'
              }}>
                {profile.business_summary}
              </div>
            </div>
          )}

          {/* Strategic Keywords */}
          {profile.strategic_keywords && (
            <div style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                战略关键词
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.strategic_keywords.split(/[,，;；、]/).map((kw, i) => (
                  kw.trim() && (
                    <span key={i} className="dark-badge dark-badge-info">
                      {kw.trim()}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Products */}
          {profile.products && (
            <div style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                主要产品
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.products.split(/[,，;；、]/).map((prod, i) => (
                  prod.trim() && (
                    <span key={i} className="dark-badge dark-badge-success">
                      {prod.trim()}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Competitors */}
          {profile.competitors && (
            <div style={{ padding: 12, borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                竞争对手
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.competitors.split(/[,，;；、]/).map((comp, i) => (
                  comp.trim() && (
                    <span key={i} className="dark-badge dark-badge-warning">
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
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                风险因素
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {profile.risk_factors.split(/[,，;；、]/).map((risk, i) => (
                  risk.trim() && (
                    <span key={i} className="dark-badge dark-badge-error">
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
            background: 'rgba(255,255,255,0.02)',
            fontSize: 11,
            color: 'var(--text-muted)',
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
