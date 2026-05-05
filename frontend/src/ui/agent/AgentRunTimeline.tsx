import React from 'react'
import { Tag, Timeline } from 'antd'
import type { AgentRunLog, AgentSkillUsageLog } from '../../api/agent'

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

interface TimelineEvent {
  id: string
  kind: 'agent' | 'skill'
  status: string
  title: string
  summary?: string | null
  time?: string | null
  meta: string[]
}

export default function AgentRunTimeline({
  agentRuns,
  skillUsages,
}: Readonly<{
  agentRuns: AgentRunLog[]
  skillUsages: AgentSkillUsageLog[]
}>) {
  const events = React.useMemo<TimelineEvent[]>(() => {
    const runEvents = agentRuns.map(item => ({
      id: item.runId,
      kind: 'agent' as const,
      status: item.status,
      title: item.agentName,
      summary: item.outputSummary || item.error,
      time: item.startedAt,
      meta: [item.durationMs == null ? '' : `${item.durationMs} ms`, ...(item.usedSkills || [])].filter(Boolean),
    }))
    const usageEvents = skillUsages.map(item => ({
      id: item.usageId,
      kind: 'skill' as const,
      status: item.status,
      title: item.skillName || item.skillKey,
      summary: item.outputSummary || item.error,
      time: item.startedAt,
      meta: [item.ownerAgent, ...(item.dataSourcesUsed || [])].filter(Boolean),
    }))
    return [...runEvents, ...usageEvents].sort((left, right) => (left.time || '').localeCompare(right.time || ''))
  }, [agentRuns, skillUsages])

  if (!events.length) {
    return <div style={{fontSize:12, color:'var(--text-muted)'}}>暂无可展示的执行链路。</div>
  }

  return (
    <Timeline
      style={{marginTop:8}}
      items={events.map(item => ({
        color: statusColor(item.status),
        children: (
          <div style={{display:'flex', flexDirection:'column', gap:4}}>
            <div style={{display:'flex', gap:8, alignItems:'center', flexWrap:'wrap'}}>
              <Tag color={item.kind === 'agent' ? 'blue' : 'purple'}>{item.kind === 'agent' ? 'Agent' : 'Skill'}</Tag>
              <span style={{fontWeight:700, color:'var(--text)'}}>{item.title}</span>
              <Tag color={statusColor(item.status)}>{item.status}</Tag>
              <span style={{fontSize:12, color:'var(--text-muted)'}}>{formatTime(item.time)}</span>
            </div>
            {item.summary && <div style={{fontSize:13, color:'var(--text-muted)', lineHeight:1.5}}>{item.summary}</div>}
            {!!item.meta.length && (
              <div style={{display:'flex', gap:4, flexWrap:'wrap'}}>
                {item.meta.map(value => <Tag key={`${item.id}-${value}`}>{value}</Tag>)}
              </div>
            )}
          </div>
        ),
      }))}
    />
  )
}