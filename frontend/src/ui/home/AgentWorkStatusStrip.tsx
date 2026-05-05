import React from 'react'
import { Button, Tag, message } from 'antd'
import { PlayCircleOutlined, ProfileOutlined, SyncOutlined } from '@ant-design/icons'
import {
  fetchAgentLogsOverview,
  fetchAgentPipelineRuns,
  fetchAgentStatus,
  runAgentPipeline,
  type AgentLogsOverview,
  type AgentPipelineRunLog,
  type AgentStatusSnapshot,
} from '../../api/agent'

type Props = {
  selectedStockCode?: string
  onOpenLogs: () => void
  onStatusChange?: (items: AgentStatusSnapshot[]) => void
}

function formatTime(value?: string | null) {
  return value ? value.slice(0, 16).replace('T', ' ') : '-'
}

function statusTone(status?: string | null) {
  if (status === 'success' || status === 'healthy') return 'green'
  if (status === 'partial_success' || status === 'degraded' || status === 'skipped') return 'gold'
  if (status === 'failed' || status === 'disabled') return 'red'
  if (status === 'running') return 'blue'
  return 'default'
}

export default function AgentWorkStatusStrip({ selectedStockCode, onOpenLogs, onStatusChange }: Readonly<Props>) {
  const [overview, setOverview] = React.useState<AgentLogsOverview | null>(null)
  const [statuses, setStatuses] = React.useState<AgentStatusSnapshot[]>([])
  const [pipelines, setPipelines] = React.useState<AgentPipelineRunLog[]>([])
  const [loading, setLoading] = React.useState(false)
  const [running, setRunning] = React.useState(false)

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const [overviewData, statusData, pipelineData] = await Promise.all([
        fetchAgentLogsOverview(),
        fetchAgentStatus(),
        fetchAgentPipelineRuns({ limit: 5 }),
      ])
      setOverview(overviewData)
      const statusItems = statusData.items || []
      setStatuses(statusItems)
      setPipelines(pipelineData.items || [])
      onStatusChange?.(statusItems)
    } catch (error_: any) {
      message.error(error_?.message || 'Agent 状态加载失败')
    } finally {
      setLoading(false)
    }
  }, [onStatusChange])

  React.useEffect(() => { load() }, [load])

  const runPreMarket = async () => {
    setRunning(true)
    try {
      await runAgentPipeline('pre-market', {
        triggeredBy: 'homepage',
        context: { currentPage: 'home', selectedStockCode },
      })
      message.success('Agent Pipeline 已触发')
      await load()
    } catch (error_: any) {
      message.error(error_?.message || 'Agent Pipeline 触发失败')
    } finally {
      setRunning(false)
    }
  }

  const latestPipeline = pipelines[0]
  const healthyCount = statuses.filter(item => ['healthy', 'idle'].includes(item.status)).length
  const degradedCount = statuses.filter(item => ['degraded', 'failed', 'disabled'].includes(item.status)).length
  const summary = latestPipeline
    ? `最近 Pipeline：${latestPipeline.pipelineType} / ${latestPipeline.status} / ${formatTime(latestPipeline.startedAt)}`
    : '今日尚未读取到 Agent Pipeline 运行记录。'

  return (
    <section style={{ padding: '0 12px 12px' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(16,24,39,0.82)', padding: 12, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 12, alignItems: 'center' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ color: 'var(--text)', fontWeight: 900 }}>Agent 工作状态</span>
            <Tag color={statusTone(overview?.overallStatus)}>{overview?.overallStatus || 'loading'}</Tag>
            {latestPipeline && <Tag color={statusTone(latestPipeline.status)}>{latestPipeline.status}</Tag>}
            <Tag color="green">正常 {healthyCount}</Tag>
            <Tag color={degradedCount ? 'gold' : 'default'}>降级/失败 {degradedCount}</Tag>
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.5, marginTop: 6 }}>{summary}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Button size="small" icon={<SyncOutlined />} loading={loading} onClick={load}>刷新</Button>
          <Button size="small" icon={<PlayCircleOutlined />} loading={running} onClick={runPreMarket}>运行 Pipeline</Button>
          <Button size="small" icon={<ProfileOutlined />} onClick={onOpenLogs}>查看日志</Button>
        </div>
      </div>
    </section>
  )
}