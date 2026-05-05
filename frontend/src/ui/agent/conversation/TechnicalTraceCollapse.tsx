import React from 'react'
import { Button, Tag } from 'antd'
import type { AgentTraceItem } from '../../../api/agent'

function statusColor(status?: string) {
  if (status === 'success') return 'green'
  if (status === 'degraded' || status === 'skipped' || status === 'timeout') return 'gold'
  if (status === 'failed') return 'red'
  return 'blue'
}

export default function TechnicalTraceCollapse({ taskId, trace, onOpenLogs }: Readonly<{ taskId?: string; trace: AgentTraceItem[]; onOpenLogs?: (taskId?: string) => void }>) {
  const [open, setOpen] = React.useState(false)
  return (
    <section className="agent-answer-section agent-trace-section">
      <div className="agent-trace-actions">
        <Button size="small" onClick={() => setOpen(value => !value)}>{open ? '收起技术详情' : '查看技术详情'}</Button>
        {taskId && onOpenLogs && <Button size="small" onClick={() => onOpenLogs(taskId)}>到日志中心验证</Button>}
      </div>
      {open && (
        <div className="agent-technical-trace">
          {taskId && <div className="agent-trace-task">任务 ID：{taskId}</div>}
          <div className="agent-trace-list">
            {trace.length ? trace.map((item, index) => (
              <div className="agent-trace-item" key={`${item.agentName}-${item.skillKey || index}`}>
                <div className="agent-trace-title-row">
                  <span className="agent-trace-agent">{item.agentName}</span>
                  <Tag color={statusColor(item.status)}>{item.userTextStatus || item.status}</Tag>
                  {item.durationMs != null && <Tag>{item.durationMs} ms</Tag>}
                </div>
                {item.summary && <div className="agent-trace-summary">{item.summary}</div>}
                {!!item.usedSkills?.length && <div className="agent-trace-tags">{item.usedSkills.map(skill => <Tag key={skill}>{skill}</Tag>)}</div>}
                {!!item.usedDataSources?.length && <div className="agent-trace-tags">{item.usedDataSources.map(source => <Tag key={source} color="purple">{source}</Tag>)}</div>}
                {item.error && <div className="agent-trace-error">{item.error}</div>}
              </div>
            )) : <div className="agent-empty-hint">暂无可展示的技术链路。</div>}
          </div>
        </div>
      )}
    </section>
  )
}
