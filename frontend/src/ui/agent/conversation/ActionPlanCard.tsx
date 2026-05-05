import React from 'react'
import { Tag } from 'antd'
import type { AgentActionItem } from '../../../api/agent'

function priorityText(priority: AgentActionItem['priority']) {
  if (priority === 'high') return '优先'
  if (priority === 'medium') return '关注'
  return '可选'
}

function priorityColor(priority: AgentActionItem['priority']) {
  if (priority === 'high') return 'red'
  if (priority === 'medium') return 'gold'
  return 'blue'
}

export default function ActionPlanCard({ items }: Readonly<{ items: AgentActionItem[] }>) {
  if (!items.length) return null
  return (
    <section className="agent-answer-section">
      <div className="agent-answer-section-title">建议你现在做什么</div>
      <div className="agent-action-list">
        {items.map((item, index) => (
          <div className="agent-action-item" key={`${item.condition}-${index}`}>
            <Tag color={priorityColor(item.priority)}>{priorityText(item.priority)}</Tag>
            <div>
              <div className="agent-action-condition">{item.condition}</div>
              <div className="agent-action-text">{item.action}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
