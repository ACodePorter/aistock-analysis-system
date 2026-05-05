import React from 'react'
import { Tag } from 'antd'
import type { AgentDecisionTrace, AgentDecisionTraceItem } from './actionability'

function stanceTone(stance: AgentDecisionTraceItem['stance']) {
  if (stance === 'support') return { color: 'green', label: '支持' }
  if (stance === 'oppose') return { color: 'red', label: '风险' }
  if (stance === 'degraded') return { color: 'gold', label: '降级' }
  return { color: 'blue', label: '中性' }
}

function formatTime(value?: string | null) {
  return value ? value.slice(0, 16).replace('T', ' ') : '-'
}

export default function AgentDecisionTracePanel({ trace, onOpenLogs }: Readonly<{ trace: AgentDecisionTrace; onOpenLogs: () => void }>) {
  return (
    <section style={{ padding: '0 12px 12px' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(16,24,39,0.78)', padding: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start', marginBottom: 12 }}>
          <div>
            <div style={{ color: 'var(--text)', fontSize: 17, fontWeight: 900 }}>Agent 决策链</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 4 }}>{trace.plainSummary}</div>
          </div>
          <button type="button" className="dark-btn dark-btn-secondary" onClick={onOpenLogs}>查看日志</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
          {trace.items.map(item => {
            const tone = stanceTone(item.stance)
            return (
              <div key={item.agentKey} style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(255,255,255,0.025)', padding: 11 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <span style={{ color: 'var(--text)', fontWeight: 850 }}>{item.title}</span>
                  <Tag color={tone.color}>{tone.label}</Tag>
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.5, marginTop: 6 }}>{item.summary}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 7 }}>最近运行 {formatTime(item.lastRunAt)}</div>
              </div>
            )
          })}
          {trace.items.length === 0 && <div style={{ gridColumn: '1 / -1', border: '1px dashed var(--border)', borderRadius: 8, padding: 14, color: 'var(--text-muted)', fontSize: 13 }}>请选择股票后查看当前结论由哪些 Agent 参与。</div>}
        </div>
      </div>
    </section>
  )
}