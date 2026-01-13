import React, { useState, useEffect } from 'react'
import { buildApiUrl, API_ENDPOINTS } from '../config/api'

interface CompanyProfile {
  symbol: string
  company_name: string
  industry?: string
  sub_industry?: string
  business_summary?: string
  core_products?: string
  competitors?: string
  risk_factors?: string
  strategic_keywords?: string
  competitive_position?: string
  last_refreshed?: string
  analysis?: any
}

interface CompanyInfoPanelProps {
  symbol: string
}

export default function CompanyInfoPanel({ symbol }: CompanyInfoPanelProps) {
  const [profile, setProfile] = React.useState<CompanyProfile | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [enriching, setEnriching] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  // 获取公司画像数据
  const loadProfile = React.useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    setError(null)
    try {
      const url = buildApiUrl(API_ENDPOINTS.STOCK_POOL.PROFILE(symbol))
      const r = await fetch(url)
      if (r.status === 404) {
        setProfile(null)
        return
      }
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setProfile(data)
    } catch (e: any) {
      console.error('Failed to load profile:', e)
      setError(e.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [symbol])

  // 触发 LLM 富化
  const triggerEnrichment = async () => {
    setEnriching(true)
    setError(null)
    try {
      const url = buildApiUrl(`/api/stock-profile/${symbol}/enrich`)
      const r = await fetch(url, { method: 'POST' })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      if (data.status === 'success') {
        setProfile(data)
      } else {
        setError(data.message || '富化失败')
      }
    } catch (e: any) {
      console.error('Enrichment failed:', e)
      setError(e.message || '富化失败')
    } finally {
      setEnriching(false)
      // 重新加载数据
      setTimeout(loadProfile, 1000)
    }
  }

  React.useEffect(() => {
    loadProfile()
  }, [loadProfile])

  if (loading) {
    return (
      <div style={{
        padding: '24px',
        background: '#fff',
        borderRadius: '12px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
        textAlign: 'center'
      }}>
        <div style={{ fontSize: '24px', marginBottom: '12px' }}>⏳</div>
        <div style={{ color: '#666' }}>加载公司信息中...</div>
      </div>
    )
  }

  if (error && !profile) {
    return (
      <div style={{
        padding: '24px',
        background: '#fef2f2',
        borderRadius: '12px',
        border: '1px solid #fecaca'
      }}>
        <div style={{ fontSize: '18px', marginBottom: '12px' }}>⚠️</div>
        <div style={{ color: '#991b1b', marginBottom: '16px' }}>{error}</div>
        <button
          onClick={triggerEnrichment}
          disabled={enriching}
          style={{
            padding: '8px 16px',
            background: '#3b82f6',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: enriching ? 'not-allowed' : 'pointer',
            opacity: enriching ? 0.6 : 1
          }}
        >
          {enriching ? '正在加载...' : '尝试加载'}
        </button>
      </div>
    )
  }

  if (!profile) {
    return (
      <div style={{
        padding: '24px',
        background: '#f3f4f6',
        borderRadius: '12px',
        textAlign: 'center',
        color: '#666'
      }}>
        <div style={{ fontSize: '32px', marginBottom: '12px' }}>📊</div>
        <div style={{ marginBottom: '16px' }}>暂无公司信息</div>
        <button
          onClick={triggerEnrichment}
          disabled={enriching}
          style={{
            padding: '8px 16px',
            background: '#3b82f6',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: enriching ? 'not-allowed' : 'pointer',
            opacity: enriching ? 0.6 : 1
          }}
        >
          {enriching ? '正在加载...' : '获取信息'}
        </button>
      </div>
    )
  }

  return (
    <div style={{
      padding: '24px',
      background: '#fff',
      borderRadius: '12px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
      fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial'
    }}>
      {/* 标题区 */}
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ margin: '0 0 8px 0', fontSize: '24px', fontWeight: 700, color: '#111827' }}>
          {profile.company_name || profile.symbol}
        </h2>
        <div style={{ color: '#6b7280', fontSize: '14px' }}>
          代码: {profile.symbol}
        </div>
      </div>

      {/* 快速信息 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '16px',
        marginBottom: '24px',
        paddingBottom: '24px',
        borderBottom: '1px solid #e5e7eb'
      }}>
        {/* 行业 */}
        <div>
          <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px', fontWeight: 600 }}>
            行业
          </div>
          <div style={{ fontSize: '16px', color: '#111827', fontWeight: 600 }}>
            {profile.industry || '—'}
          </div>
          {profile.sub_industry && (
            <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              细分: {profile.sub_industry}
            </div>
          )}
        </div>

        {/* 市场地位 */}
        <div>
          <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px', fontWeight: 600 }}>
            竞争地位
          </div>
          <div style={{ fontSize: '16px', color: '#111827', fontWeight: 600 }}>
            {profile.competitive_position || '—'}
          </div>
        </div>
      </div>

      {/* 业务概述 */}
      {profile.business_summary && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>
            📋 业务概述
          </h3>
          <p style={{
            margin: 0,
            fontSize: '13px',
            lineHeight: '1.6',
            color: '#374151',
            background: '#f9fafb',
            padding: '12px',
            borderRadius: '8px',
            borderLeft: '3px solid #3b82f6'
          }}>
            {profile.business_summary}
          </p>
        </div>
      )}

      {/* 产品与服务 */}
      {profile.core_products && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>
            🛍️ 核心产品
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {profile.core_products.split(',').map((p, i) => (
              p.trim() && (
                <span
                  key={i}
                  style={{
                    display: 'inline-block',
                    padding: '6px 12px',
                    background: '#dbeafe',
                    color: '#1e40af',
                    borderRadius: '20px',
                    fontSize: '12px',
                    fontWeight: 600
                  }}
                >
                  {p.trim()}
                </span>
              )
            ))}
          </div>
        </div>
      )}

      {/* 竞争对手 */}
      {profile.competitors && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>
            🏆 主要竞争对手
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {profile.competitors.split(',').map((c, i) => (
              c.trim() && (
                <span
                  key={i}
                  style={{
                    display: 'inline-block',
                    padding: '6px 12px',
                    background: '#fecaca',
                    color: '#991b1b',
                    borderRadius: '20px',
                    fontSize: '12px',
                    fontWeight: 600
                  }}
                >
                  {c.trim()}
                </span>
              )
            ))}
          </div>
        </div>
      )}

      {/* 风险因素 */}
      {profile.risk_factors && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>
            ⚡ 风险因素
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {profile.risk_factors.split(',').map((r, i) => (
              r.trim() && (
                <span
                  key={i}
                  style={{
                    display: 'inline-block',
                    padding: '6px 12px',
                    background: '#fee2e2',
                    color: '#7f1d1d',
                    borderRadius: '20px',
                    fontSize: '12px',
                    fontWeight: 600
                  }}
                >
                  {r.trim()}
                </span>
              )
            ))}
          </div>
        </div>
      )}

      {/* 关键词 */}
      {profile.strategic_keywords && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 700, color: '#111827' }}>
            🏷️ 关键词
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {profile.strategic_keywords.split(',').map((k, i) => (
              k.trim() && (
                <span
                  key={i}
                  style={{
                    display: 'inline-block',
                    padding: '4px 10px',
                    background: '#f0fdf4',
                    color: '#166534',
                    borderRadius: '16px',
                    fontSize: '11px',
                    fontWeight: 600
                  }}
                >
                  {k.trim()}
                </span>
              )
            ))}
          </div>
        </div>
      )}

      {/* 更新时间 & 刷新按钮 */}
      <div style={{
        paddingTop: '16px',
        borderTop: '1px solid #e5e7eb',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ fontSize: '12px', color: '#9ca3af' }}>
          最后更新: {profile.last_refreshed
            ? new Date(profile.last_refreshed).toLocaleString('zh-CN')
            : '从未更新'}
        </div>
        <button
          onClick={triggerEnrichment}
          disabled={enriching}
          style={{
            padding: '6px 12px',
            background: enriching ? '#d1d5db' : '#3b82f6',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: enriching ? 'not-allowed' : 'pointer',
            opacity: enriching ? 0.7 : 1,
            transition: 'all 0.2s'
          }}
        >
          {enriching ? '🔄 更新中...' : '🔄 刷新'}
        </button>
      </div>

      {error && (
        <div style={{
          marginTop: '12px',
          padding: '12px',
          background: '#fef2f2',
          color: '#991b1b',
          borderRadius: '6px',
          fontSize: '12px'
        }}>
          ⚠️ {error}
        </div>
      )}
    </div>
  )
}
