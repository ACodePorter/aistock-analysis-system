import React from 'react'
import { Alert, Button, Descriptions, Drawer, Input, Select, Table, Tabs, Tag, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  confirmAgentTask,
  fetchAgentLogsOverview,
  fetchAgentPipelineRun,
  fetchAgentPipelineRuns,
  fetchAgentPipelines,
  fetchAgentRuns,
  fetchAgentStatus,
  fetchAgentTask,
  fetchAgentTaskRuns,
  fetchSkillAuditLogs,
  fetchSkillUsages,
  rerunAgentTask,
  rerunFailedAgentTasks,
  runAgentPipeline,
  type AgentLogsOverview,
  type AgentPipelineDefinition,
  type AgentPipelineRunDetail,
  type AgentPipelineRunLog,
  type AgentRunLog,
  type AgentSkillAuditLog,
  type AgentSkillUsageLog,
  type AgentStatusSnapshot,
  type AgentTaskDetail,
  type AgentTaskRunsResponse,
} from '../../api/agent'
import AgentRunTimeline from './AgentRunTimeline'
import { AgentPageShell, AgentPanel } from './AgentPageLayout'

function statusColor(status?: string | null) {
  if (!status) return 'default'
  if (['success', 'healthy', 'idle'].includes(status)) return 'green'
  if (['running', 'pending'].includes(status)) return 'blue'
  if (['degraded', 'timeout', 'skipped'].includes(status)) return 'gold'
  if (['failed', 'disabled'].includes(status)) return 'red'
  return 'default'
}

function formatTime(value?: string | null) {
  return value ? value.slice(0, 19).replace('T', ' ') : '-'
}

function readHashParams() {
  const hash = globalThis.location.hash || ''
  const queryIndex = hash.indexOf('?')
  return queryIndex >= 0 ? new URLSearchParams(hash.slice(queryIndex + 1)) : new URLSearchParams()
}

export default function AgentLogsPage() {
  const [overview, setOverview] = React.useState<AgentLogsOverview | null>(null)
  const [pipelines, setPipelines] = React.useState<AgentPipelineDefinition[]>([])
  const [pipelineRuns, setPipelineRuns] = React.useState<AgentPipelineRunLog[]>([])
  const [statusRows, setStatusRows] = React.useState<AgentStatusSnapshot[]>([])
  const [agentRuns, setAgentRuns] = React.useState<AgentRunLog[]>([])
  const [skillUsages, setSkillUsages] = React.useState<AgentSkillUsageLog[]>([])
  const [skillAudits, setSkillAudits] = React.useState<AgentSkillAuditLog[]>([])
  const [loading, setLoading] = React.useState(false)
  const [agentName, setAgentName] = React.useState<string | undefined>()
  const [pipelineType, setPipelineType] = React.useState<string | undefined>()
  const [pipelineMessage, setPipelineMessage] = React.useState('')
  const [status, setStatus] = React.useState<string | undefined>()
  const [taskId, setTaskId] = React.useState('')
  const [drawerOpen, setDrawerOpen] = React.useState(false)
  const [pipelineDrawerOpen, setPipelineDrawerOpen] = React.useState(false)
  const [taskDetail, setTaskDetail] = React.useState<AgentTaskDetail | null>(null)
  const [taskRuns, setTaskRuns] = React.useState<AgentTaskRunsResponse | null>(null)
  const [pipelineDetail, setPipelineDetail] = React.useState<AgentPipelineRunDetail | null>(null)
  const [confirmingTask, setConfirmingTask] = React.useState(false)
  const [rerunningTask, setRerunningTask] = React.useState(false)
  const [rerunningFailed, setRerunningFailed] = React.useState(false)

  React.useEffect(() => {
    const applyHashFilters = () => {
      const params = readHashParams()
      if (params.has('taskId')) setTaskId(params.get('taskId') || '')
      if (params.has('agentName')) setAgentName(params.get('agentName') || undefined)
      if (params.has('pipelineType')) setPipelineType(params.get('pipelineType') || undefined)
      if (params.has('status')) setStatus(params.get('status') || undefined)
    }
    applyHashFilters()
    globalThis.addEventListener('hashchange', applyHashFilters)
    return () => globalThis.removeEventListener('hashchange', applyHashFilters)
  }, [])

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const [overviewData, pipelineData, pipelineRunData, statusData, runsData, usagesData, auditData] = await Promise.all([
        fetchAgentLogsOverview(),
        fetchAgentPipelines(),
        fetchAgentPipelineRuns({ pipelineType, status, limit: 80 }),
        fetchAgentStatus(),
        fetchAgentRuns({ agentName, status, taskId: taskId.trim() || undefined, limit: 80 }),
        fetchSkillUsages({ ownerAgent: agentName, status, taskId: taskId.trim() || undefined, limit: 80 }),
        fetchSkillAuditLogs({ limit: 80 }).catch(() => ({items: [], count: 0})),
      ])
      setOverview(overviewData)
      setPipelines(pipelineData.items || [])
      setPipelineRuns(pipelineRunData.items || [])
      setStatusRows(statusData.items || [])
      setAgentRuns(runsData.items || [])
      setSkillUsages(usagesData.items || [])
      setSkillAudits(auditData.items || [])
    } catch (error_: any) {
      message.error(error_?.message || '加载 Agent 日志失败')
    } finally {
      setLoading(false)
    }
  }, [agentName, pipelineType, status, taskId])

  React.useEffect(() => { load() }, [load])

  const agentOptions = React.useMemo(() => {
    const names = new Set<string>()
    statusRows.forEach(item => names.add(item.agentName))
    agentRuns.forEach(item => names.add(item.agentName))
    skillUsages.forEach(item => names.add(item.ownerAgent))
    return Array.from(names).sort((left, right) => left.localeCompare(right)).map(value => ({label:value, value}))
  }, [agentRuns, skillUsages, statusRows])

  const pipelineOptions = React.useMemo(
    () => pipelines.map(item => ({label: item.label, value: item.pipelineType})),
    [pipelines],
  )

  const openTask = async (id?: string | null) => {
    if (!id) return
    setDrawerOpen(true)
    setTaskDetail(null)
    setTaskRuns(null)
    try {
      const [detail, runs] = await Promise.all([fetchAgentTask(id), fetchAgentTaskRuns(id)])
      setTaskDetail(detail)
      setTaskRuns(runs)
    } catch (error_: any) {
      message.error(error_?.message || '任务详情加载失败')
    }
  }

  const refreshTask = async (id: string) => {
    const [detail, runs] = await Promise.all([fetchAgentTask(id), fetchAgentTaskRuns(id)])
    setTaskDetail(detail)
    setTaskRuns(runs)
  }

  const confirmTask = async () => {
    if (!taskDetail) return
    setConfirmingTask(true)
    try {
      const text = `确认执行 ${taskDetail.taskId}`
      const response = await confirmAgentTask(taskDetail.taskId, { confirmationText: text })
      message.success(response.reply || '任务已确认执行')
      await refreshTask(taskDetail.taskId)
      await load()
    } catch (error_: any) {
      message.error(error_?.message || '确认执行失败')
    } finally {
      setConfirmingTask(false)
    }
  }

  const rerunTask = async () => {
    if (!taskDetail) return
    setRerunningTask(true)
    try {
      const needsConfirmation = taskDetail.requiresConfirmation || taskDetail.riskLevel === 'high' || taskDetail.riskLevel === 'critical'
      const response = await rerunAgentTask(taskDetail.taskId, {
        confirmed: needsConfirmation,
        confirmationText: needsConfirmation ? `确认重跑 ${taskDetail.taskId}` : undefined,
      })
      message.success(response.reply || '任务已重跑')
      await refreshTask(taskDetail.taskId)
      await load()
    } catch (error_: any) {
      message.error(error_?.message || '任务重跑失败')
    } finally {
      setRerunningTask(false)
    }
  }

  const rerunFailedTasks = async () => {
    setRerunningFailed(true)
    try {
      const result = await rerunFailedAgentTasks({ limit: 5 })
      const pendingCount = result.items.filter(item => item.requiresConfirmation).length
      const pendingText = pendingCount ? `，${pendingCount} 个等待确认` : ''
      message.success(`已处理 ${result.count} 个失败任务${pendingText}`)
      await load()
    } catch (error_: any) {
      message.error(error_?.message || '批量重跑失败')
    } finally {
      setRerunningFailed(false)
    }
  }

  const openPipeline = async (id?: string | null) => {
    if (!id) return
    setPipelineDrawerOpen(true)
    setPipelineDetail(null)
    try {
      setPipelineDetail(await fetchAgentPipelineRun(id))
    } catch (error_: any) {
      message.error(error_?.message || 'Pipeline 详情加载失败')
    }
  }

  const triggerPipeline = async () => {
    const selected = pipelineType || pipelines[0]?.pipelineType || 'data-diagnosis'
    setLoading(true)
    try {
      const result = await runAgentPipeline(selected, { message: pipelineMessage.trim() || undefined })
      message.success(`Pipeline 已执行：${result.status}`)
      setPipelineMessage('')
      await load()
      await openPipeline(result.pipelineRunId)
    } catch (error_: any) {
      message.error(error_?.message || '触发 Pipeline 失败')
    } finally {
      setLoading(false)
    }
  }

  const clearFilters = () => {
    setPipelineType(undefined)
    setAgentName(undefined)
    setStatus(undefined)
    setTaskId('')
    if (globalThis.location.hash.startsWith('#agent-logs?')) {
      try { globalThis.history.replaceState({}, '', '#agent-logs') } catch { globalThis.location.hash = '#agent-logs' }
    }
  }

  const statusColumns: ColumnsType<AgentStatusSnapshot> = [
    { title: 'Agent', dataIndex: 'displayName', render: (_, row) => <div><div style={{fontWeight:700}}>{row.displayName}</div><div style={{fontSize:12, color:'var(--text-muted)'}}>{row.agentName}</div></div> },
    { title: '状态', dataIndex: 'status', width: 100, render: value => <Tag color={statusColor(value)}>{value}</Tag> },
    { title: '24h 成功率', dataIndex: 'successRate24h', width: 110, render: value => value == null ? '-' : `${Math.round(value * 100)}%` },
    { title: '平均耗时', dataIndex: 'avgDurationMs', width: 100, render: value => value == null ? '-' : `${value} ms` },
    { title: '启用 Skill', dataIndex: 'enabledSkills', width: 100 },
    { title: '最近运行', dataIndex: 'lastRunAt', width: 170, render: formatTime },
    { title: '最近错误', dataIndex: 'recentError', ellipsis: true, render: value => value || '-' },
  ]

  const pipelineColumns: ColumnsType<AgentPipelineRunLog> = [
    { title: 'Pipeline ID', dataIndex: 'pipelineRunId', width: 190, render: value => <Button type="link" size="small" onClick={() => openPipeline(value)}>{value}</Button> },
    { title: '类型', dataIndex: 'pipelineType', width: 150, render: value => <Tag color="purple">{value}</Tag> },
    { title: '状态', dataIndex: 'status', width: 110, render: value => <Tag color={statusColor(value)}>{value}</Tag> },
    { title: '摘要', dataIndex: 'finalSummary', ellipsis: true, render: value => value || '-' },
    { title: '触发人', dataIndex: 'triggeredBy', width: 100 },
    { title: '耗时', dataIndex: 'durationMs', width: 90, render: value => value == null ? '-' : `${value} ms` },
    { title: '开始时间', dataIndex: 'startedAt', width: 170, render: formatTime },
  ]

  const runColumns: ColumnsType<AgentRunLog> = [
    { title: 'Run ID', dataIndex: 'runId', width: 190, render: value => <span style={{fontFamily:'monospace'}}>{value}</span> },
    { title: 'Task', dataIndex: 'taskId', width: 150, render: value => <Button type="link" size="small" onClick={() => openTask(value)}>{value}</Button> },
    { title: 'Agent', dataIndex: 'agentName', width: 160, render: value => <Tag color="blue">{value}</Tag> },
    { title: '状态', dataIndex: 'status', width: 90, render: value => <Tag color={statusColor(value)}>{value}</Tag> },
    { title: '摘要', dataIndex: 'outputSummary', ellipsis: true, render: value => value || '-' },
    { title: '技能', dataIndex: 'usedSkills', width: 180, render: values => values?.length ? values.map((item: string) => <Tag key={item}>{item}</Tag>) : '-' },
    { title: '耗时', dataIndex: 'durationMs', width: 90, render: value => value == null ? '-' : `${value} ms` },
    { title: '开始时间', dataIndex: 'startedAt', width: 170, render: formatTime },
  ]

  const usageColumns: ColumnsType<AgentSkillUsageLog> = [
    { title: 'Usage ID', dataIndex: 'usageId', width: 190, render: value => <span style={{fontFamily:'monospace'}}>{value}</span> },
    { title: 'Task', dataIndex: 'taskId', width: 150, render: value => value ? <Button type="link" size="small" onClick={() => openTask(value)}>{value}</Button> : '-' },
    { title: 'Skill', dataIndex: 'skillName', width: 190, render: (_, row) => <div><div style={{fontWeight:700}}>{row.skillName}</div><div style={{fontSize:12, color:'var(--text-muted)'}}>{row.skillKey}</div></div> },
    { title: 'Owner', dataIndex: 'ownerAgent', width: 160, render: value => <Tag color="blue">{value}</Tag> },
    { title: '状态', dataIndex: 'status', width: 90, render: value => <Tag color={statusColor(value)}>{value}</Tag> },
    { title: '摘要', dataIndex: 'outputSummary', ellipsis: true, render: value => value || '-' },
    { title: '数据源', dataIndex: 'dataSourcesUsed', width: 220, render: values => values?.length ? values.map((item: string) => <Tag key={item}>{item}</Tag>) : '-' },
    { title: '开始时间', dataIndex: 'startedAt', width: 170, render: formatTime },
  ]

  const auditColumns: ColumnsType<AgentSkillAuditLog> = [
    { title: 'Audit ID', dataIndex: 'auditLogId', width: 190, render: value => <span style={{fontFamily:'monospace'}}>{value}</span> },
    { title: 'Skill', dataIndex: 'skillKey', width: 190 },
    { title: '动作', dataIndex: 'action', width: 100 },
    { title: '结果', dataIndex: 'result', width: 90, render: value => <Tag color={value === 'success' ? 'green' : 'red'}>{value}</Tag> },
    { title: '风险', dataIndex: 'riskLevel', width: 90, render: value => <Tag color={value === 'high' || value === 'critical' ? 'red' : 'green'}>{value}</Tag> },
    { title: '原因', dataIndex: 'reason', ellipsis: true, render: value => value || '-' },
    { title: '时间', dataIndex: 'timestamp', width: 170, render: formatTime },
  ]

  return (
    <AgentPageShell
      title="Agent 状态历史与日志"
      subtitle="AgentRun、SkillUsage、任务计划和数据 Pipeline 健康摘要。支持从主页携带 Task ID 跳转验证。"
      actions={(
        <>
        <Button onClick={load} loading={loading}>刷新</Button>
        <Button danger onClick={rerunFailedTasks} loading={rerunningFailed}>重跑最近失败</Button>
        </>
      )}
    >

      {overview && (
        <Alert type={overview.overallStatus === 'healthy' ? 'success' : 'warning'} showIcon message={overview.summary} />
      )}

      <div className="agent-metric-grid">
        {[
          ['总 AgentRun', overview?.agentRunTotal ?? '-'],
          ['总 SkillUsage', overview?.skillUsageTotal ?? '-'],
          ['总 AgentPipeline', overview?.agentPipelineRunTotal ?? '-'],
          ['24h Agent 失败', overview?.agentFailed24h ?? '-'],
          ['24h Skill 失败', overview?.skillFailed24h ?? '-'],
          ['24h AgentPipeline 失败', overview?.agentPipelineFailed24h ?? '-'],
        ].map(([label, value]) => (
          <div key={label} className="agent-metric-card">
            <div className="agent-metric-label">{label}</div>
            <div className="agent-metric-value">{value}</div>
          </div>
        ))}
      </div>

      <AgentPanel>
        <div className="agent-toolbar">
          <Select allowClear placeholder="Pipeline" value={pipelineType} onChange={setPipelineType} options={pipelineOptions} style={{width:220}} />
          <Select allowClear placeholder="Agent" value={agentName} onChange={setAgentName} options={agentOptions} style={{width:210}} />
          <Select allowClear placeholder="状态" value={status} onChange={setStatus} options={['success','partial_success','failed','degraded','skipped','running','pending'].map(value => ({label:value, value}))} style={{width:160}} />
          <Input.Search value={taskId} onChange={event => setTaskId(event.target.value)} onSearch={load} placeholder="按 Task ID 过滤" allowClear style={{width:260}} />
          <Input value={pipelineMessage} onChange={event => setPipelineMessage(event.target.value)} placeholder="可选：Pipeline 附加请求" allowClear style={{width:280}} />
          <Button type="primary" onClick={triggerPipeline} loading={loading}>运行 Pipeline</Button>
          <Button onClick={clearFilters} disabled={!pipelineType && !agentName && !status && !taskId}>清除筛选</Button>
        </div>
        <Tabs
          items={[
            { key: 'status', label: 'Agent 状态', children: <Table rowKey="agentName" loading={loading} columns={statusColumns} dataSource={statusRows} size="small" pagination={false} /> },
            { key: 'pipelines', label: 'PipelineRun', children: <Table rowKey="pipelineRunId" loading={loading} columns={pipelineColumns} dataSource={pipelineRuns} size="small" scroll={{x:1100}} pagination={{pageSize:10}} /> },
            { key: 'runs', label: 'AgentRun', children: <Table rowKey="runId" loading={loading} columns={runColumns} dataSource={agentRuns} size="small" scroll={{x:1200}} pagination={{pageSize:10}} /> },
            { key: 'skills', label: 'SkillUsage', children: <Table rowKey="usageId" loading={loading} columns={usageColumns} dataSource={skillUsages} size="small" scroll={{x:1300}} pagination={{pageSize:10}} /> },
            { key: 'audit', label: 'SkillAudit', children: <Table rowKey="auditLogId" loading={loading} columns={auditColumns} dataSource={skillAudits} size="small" scroll={{x:1200}} pagination={{pageSize:10}} /> },
          ]}
        />
      </AgentPanel>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} width={820} title={taskDetail ? `任务 ${taskDetail.taskId}` : '任务详情'} destroyOnHidden>
        {taskDetail ? (
          <div style={{display:'flex', flexDirection:'column', gap:12}}>
            {taskDetail.status === 'pending_confirmation' && (
              <Alert
                type="warning"
                showIcon
                message="该任务等待确认"
                description="确认后会按已生成的 Task Plan 继续执行；高风险请求仍不会执行真实下单、关闭风控或删除审计等禁止动作。"
                action={<Button type="primary" danger loading={confirmingTask} onClick={confirmTask}>确认执行</Button>}
              />
            )}
            {taskDetail.status === 'failed' && (
              <Alert
                type="error"
                showIcon
                message="该任务执行失败"
                description="可按原始 Task Plan 重跑；若原任务需要确认，重跑时仍会携带确认文本。"
                action={<Button type="primary" danger loading={rerunningTask} onClick={rerunTask}>重跑任务</Button>}
              />
            )}
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="用户请求">{taskDetail.userMessage}</Descriptions.Item>
              <Descriptions.Item label="意图">{taskDetail.intent}</Descriptions.Item>
              <Descriptions.Item label="风险"><Tag color={taskDetail.riskLevel === 'high' ? 'red' : 'green'}>{taskDetail.riskLevel}</Tag></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={statusColor(taskDetail.status)}>{taskDetail.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="确认要求">{taskDetail.requiresConfirmation ? '需要确认' : '无需确认'}</Descriptions.Item>
              <Descriptions.Item label="最终摘要">{taskDetail.finalSummary || '-'}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{formatTime(taskDetail.createdAt)}</Descriptions.Item>
            </Descriptions>
            <Tabs
              items={[
                { key: 'plan', label: 'Task Plan', children: <pre className="agent-code-block">{JSON.stringify(taskDetail.plan, null, 2)}</pre> },
                { key: 'timeline', label: 'Timeline', children: <AgentRunTimeline agentRuns={taskRuns?.agentRuns || []} skillUsages={taskRuns?.skillUsages || []} /> },
                { key: 'runs', label: 'AgentRun', children: <Table rowKey="runId" columns={runColumns} dataSource={taskRuns?.agentRuns || []} size="small" pagination={false} scroll={{x:1100}} /> },
                { key: 'usages', label: 'SkillUsage', children: <Table rowKey="usageId" columns={usageColumns} dataSource={taskRuns?.skillUsages || []} size="small" pagination={false} scroll={{x:1200}} /> },
              ]}
            />
          </div>
        ) : <Alert type="info" showIcon message="正在加载任务详情" />}
      </Drawer>

      <Drawer open={pipelineDrawerOpen} onClose={() => setPipelineDrawerOpen(false)} width={920} title={pipelineDetail ? `Pipeline ${pipelineDetail.pipelineRunId}` : 'Pipeline 详情'} destroyOnHidden>
        {pipelineDetail ? (
          <div style={{display:'flex', flexDirection:'column', gap:12}}>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="类型">{pipelineDetail.pipelineType}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={statusColor(pipelineDetail.status)}>{pipelineDetail.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="触发人">{pipelineDetail.triggeredBy}</Descriptions.Item>
              <Descriptions.Item label="摘要">{pipelineDetail.finalSummary || '-'}</Descriptions.Item>
              <Descriptions.Item label="开始时间">{formatTime(pipelineDetail.startedAt)}</Descriptions.Item>
              <Descriptions.Item label="耗时">{pipelineDetail.durationMs == null ? '-' : `${pipelineDetail.durationMs} ms`}</Descriptions.Item>
              <Descriptions.Item label="警告">{pipelineDetail.warnings.length ? pipelineDetail.warnings.join('；') : '-'}</Descriptions.Item>
            </Descriptions>
            <Tabs
              items={[
                { key: 'steps', label: 'Steps', children: <pre className="agent-code-block">{JSON.stringify(pipelineDetail.payload?.steps || [], null, 2)}</pre> },
                { key: 'timeline', label: 'Timeline', children: <AgentRunTimeline agentRuns={pipelineDetail.agentRuns || []} skillUsages={pipelineDetail.skillUsages || []} /> },
                { key: 'runs', label: 'AgentRun', children: <Table rowKey="runId" columns={runColumns} dataSource={pipelineDetail.agentRuns || []} size="small" pagination={false} scroll={{x:1100}} /> },
                { key: 'usages', label: 'SkillUsage', children: <Table rowKey="usageId" columns={usageColumns} dataSource={pipelineDetail.skillUsages || []} size="small" pagination={false} scroll={{x:1200}} /> },
              ]}
            />
          </div>
        ) : <Alert type="info" showIcon message="正在加载 Pipeline 详情" />}
      </Drawer>
    </AgentPageShell>
  )
}