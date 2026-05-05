import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchPipelineRetryStatus,
  fetchPipelineStatus,
  triggerPipelineRetry,
  type PipelineStatus,
  type PipelineStatusResponse,
} from '../api/pipelineStatus'
import { fetchModelLifecycle, type ModelLifecycleResponse } from '../api/modelLifecycle'
import HelpTooltip from './components/HelpTooltip'
import { helpTips } from '../config/helpTips'

interface Props {
  symbol: string | null | undefined
  onOpenDrawer: (symbol: string) => void
}

const STATUS_COLORS: Record<PipelineStatus, { bg: string; fg: string; label: string }> = {
  success: { bg: 'rgba(16,185,129,0.16)', fg: '#10b981', label: '正常' },
  running: { bg: 'rgba(99,102,241,0.18)', fg: '#818cf8', label: '执行中' },
  skipped: { bg: 'rgba(234,179,8,0.18)', fg: '#eab308', label: '跳过' },
  failed:  { bg: 'rgba(239,68,68,0.20)', fg: '#ef4444', label: '失败' },
}

const RUN_TYPE_LABELS: Record<string, string> = {
  daily_pipeline: '日线管道',
  fetch_daily: '行情补数',
  compute_signal: '信号',
  predict: '预测',
  full_report: '完整报告',
}

const RUN_TYPE_TIPS: Record<string, keyof typeof helpTips> = {
  daily_pipeline: 'dataPipelineDiagnosis',
  fetch_daily: 'fetchDailyTask',
  compute_signal: 'agentTechnicalTiming',
  predict: 'predictionTask',
  full_report: 'fullReportTask',
}

const MODEL_STATUS_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  optimized: { bg: 'rgba(16,185,129,0.16)', fg: '#10b981', label: '已优化' },
  retained: { bg: 'rgba(234,179,8,0.18)', fg: '#eab308', label: '保留旧模型' },
  needs_retrain: { bg: 'rgba(99,102,241,0.18)', fg: '#818cf8', label: '待训练' },
  stagnated: { bg: 'rgba(239,68,68,0.20)', fg: '#ef4444', label: '优化停滞' },
  unknown: { bg: 'rgba(255,255,255,0.06)', fg: 'var(--text-muted)', label: '无记录' },
}

const CARD_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: '8px 12px',
  marginBottom: 12,
  display: 'flex',
  flexWrap: 'wrap',
  alignItems: 'center',
  gap: 12,
  background: 'rgba(255,255,255,0.02)',
  fontSize: 12,
}

function Badge({ status }: { status: PipelineStatus | null | undefined }) {
  if (!status) {
    return (
      <span
        style={{
          padding: '2px 8px',
          borderRadius: 999,
          background: 'rgba(255,255,255,0.06)',
          color: 'var(--text-muted)',
        }}
      >
        无记录
      </span>
    )
  }
  const s = STATUS_COLORS[status] ?? STATUS_COLORS.skipped
  return (
    <span style={{ padding: '2px 8px', borderRadius: 999, background: s.bg, color: s.fg, fontWeight: 500 }}>
      {s.label}
    </span>
  )
}

function formatRelative(iso: string | null | undefined) {
  if (!iso) return '—'
  try {
    const t = new Date(iso).getTime()
    const dt = Date.now() - t
    if (isNaN(dt)) return iso
    const mins = Math.floor(dt / 60000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins} 分钟前`
    const hrs = Math.floor(mins / 60)
    if (hrs < 48) return `${hrs} 小时前`
    const days = Math.floor(hrs / 24)
    return `${days} 天前`
  } catch {
    return iso
  }
}

function formatScoreDelta(scoreBefore: number | null | undefined, scoreAfter: number | null | undefined) {
  if (scoreBefore == null || scoreAfter == null) return null
  const delta = scoreAfter - scoreBefore
  const sign = delta >= 0 ? '+' : ''
  return `${scoreBefore.toFixed(3)} → ${scoreAfter.toFixed(3)} (${sign}${delta.toFixed(3)})`
}

export const PricePredictionStatus: React.FC<Props> = ({ symbol, onOpenDrawer }) => {
  const [data, setData] = useState<PipelineStatusResponse | null>(null)
  const [modelLifecycle, setModelLifecycle] = useState<ModelLifecycleResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [retryJobId, setRetryJobId] = useState<string | null>(null)
  const [retryState, setRetryState] = useState<PipelineStatus | 'queued' | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const pollTimer = useRef<number | null>(null)

  const load = useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    setHint(null)
    try {
      const [res, lifecycle] = await Promise.all([
        fetchPipelineStatus(symbol),
        fetchModelLifecycle(symbol, 8).catch(() => null),
      ])
      setData(res)
      setModelLifecycle(lifecycle)
    } catch (err: any) {
      setHint(`状态获取失败: ${err?.message ?? err}`)
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    setData(null)
    setModelLifecycle(null)
    setRetryJobId(null)
    setRetryState(null)
    setHint(null)
    if (symbol) load()
  }, [symbol, load])

  useEffect(() => () => {
    if (pollTimer.current) window.clearInterval(pollTimer.current)
  }, [])

  const handleRetry = async () => {
    if (!symbol) return
    setHint(null)
    try {
      const ack = await triggerPipelineRetry(symbol)
      setRetryJobId(ack.job_id)
      setRetryState(ack.status)
      // poll
      if (pollTimer.current) window.clearInterval(pollTimer.current)
      pollTimer.current = window.setInterval(async () => {
        try {
          const st = await fetchPipelineRetryStatus(symbol, ack.job_id)
          setRetryState(st.status as any)
          if (st.status === 'success' || st.status === 'failed') {
            if (pollTimer.current) {
              window.clearInterval(pollTimer.current)
              pollTimer.current = null
            }
            if (st.status === 'failed' && st.error) {
              setHint(st.error)
            }
            load()
          }
        } catch (err: any) {
          if (pollTimer.current) {
            window.clearInterval(pollTimer.current)
            pollTimer.current = null
          }
          setHint(`轮询重试状态失败: ${err?.message ?? err}`)
        }
      }, 2000)
    } catch (err: any) {
      setHint(`触发重试失败: ${err?.message ?? err}`)
    }
  }

  if (!symbol) return null

  const overallStatus = (data?.overall?.status ?? null) as PipelineStatus | null
  const retryRunning = retryState === 'queued' || retryState === 'running'
  const typeOrder = ['daily_pipeline', 'fetch_daily', 'predict', 'full_report']
  const modelStatus = MODEL_STATUS_COLORS[modelLifecycle?.summary?.active_status || 'unknown'] ?? MODEL_STATUS_COLORS.unknown
  const latestModelEvent = modelLifecycle?.items?.[0]
  const scoreDelta = formatScoreDelta(latestModelEvent?.score_before, latestModelEvent?.score_after)

  return (
    <div style={CARD_STYLE}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: 'var(--text-muted)' }}>总体：</span>
        <Badge status={retryRunning ? 'running' : overallStatus} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: 'var(--text-muted)' }}>最近行情日：</span>
        <span style={{ fontWeight: 500 }}>{data?.latest_price_date ?? '—'}</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: 'var(--text-muted)' }}>最新预测批次：</span>
        <span style={{ fontWeight: 500 }}>{formatRelative(data?.latest_forecast_run_at)}</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        {typeOrder.map(rt => {
          const rec = data?.latest_by_type?.[rt]
          if (!rec) return null
          return (
            <HelpTooltip
              key={rt}
              {...helpTips[RUN_TYPE_TIPS[rt] || 'dataPipelineDiagnosis']}
              content={`${helpTips[RUN_TYPE_TIPS[rt] || 'dataPipelineDiagnosis'].content}${rec.message || rec.error_message ? `\n最近信息：${rec.message || rec.error_message}` : ''}`}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'help' }}>
                <span style={{ color: 'var(--text-muted)' }}>{RUN_TYPE_LABELS[rt] || rt}：</span>
                <Badge status={rec.status} />
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                  {formatRelative(rec.run_at)}
                </span>
              </span>
            </HelpTooltip>
          )
        })}
      </div>

      <HelpTooltip
        {...helpTips.modelStatus}
        content={`${helpTips.modelStatus.content}\n${modelLifecycle?.summary?.active_reason || '暂无模型生命周期记录'}`}
      >
        <div
          style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          flexWrap: 'wrap',
          paddingLeft: 10,
          borderLeft: '1px solid var(--border)',
          }}
        >
          <span style={{ color: 'var(--text-muted)' }}>模型健康：</span>
          <span style={{ padding: '2px 8px', borderRadius: 999, background: modelStatus.bg, color: modelStatus.fg, fontWeight: 500 }}>
            {modelStatus.label}
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
            {modelLifecycle?.summary?.active_reason || '暂无生命周期记录'}
          </span>
          {scoreDelta && (
            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
              分数 {scoreDelta}
            </span>
          )}
        </div>
      </HelpTooltip>

      <div style={{ flex: 1 }} />

      <HelpTooltip {...helpTips.retryTask}>
        <span style={{ display: 'inline-flex' }}>
          <button
            onClick={handleRetry}
            disabled={retryRunning || loading}
            className="dark-btn dark-btn-secondary"
            style={{ padding: '4px 10px', fontSize: 12 }}
          >
            {retryRunning ? '重试中…' : '立即重试'}
          </button>
        </span>
      </HelpTooltip>
      <HelpTooltip {...helpTips.viewDetails}>
        <button
          onClick={() => onOpenDrawer(symbol)}
          className="dark-btn dark-btn-secondary"
          style={{ padding: '4px 10px', fontSize: 12 }}
        >
          查看详情
        </button>
      </HelpTooltip>

      {hint && (
        <div
          style={{
            width: '100%',
            color: '#f87171',
            fontSize: 11,
            paddingTop: 4,
            borderTop: '1px dashed var(--border)',
          }}
        >
          {hint}
        </div>
      )}
    </div>
  )
}

export default PricePredictionStatus
