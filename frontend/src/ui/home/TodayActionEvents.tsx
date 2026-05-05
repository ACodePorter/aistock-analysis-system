import React from 'react'
import type { TodayActionEvent } from './actionability'
import { formatAbsPct } from './actionability'

const severityTone: Record<TodayActionEvent['severity'], { border: string; bg: string; color: string; label: string }> = {
  info: { border: 'var(--primary-border)', bg: 'var(--primary-light)', color: 'var(--primary)', label: '盯盘' },
  warning: { border: 'var(--action-hold-border)', bg: 'var(--action-hold-bg)', color: 'var(--warning)', label: '警惕' },
  danger: { border: 'var(--action-sell-border)', bg: 'var(--action-sell-bg)', color: 'var(--negative)', label: '风险' },
  success: { border: 'var(--action-buy-border)', bg: 'var(--action-buy-bg)', color: 'var(--positive)', label: '触发' },
}

function money(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '-'
  return value.toFixed(2)
}

export default function TodayActionEvents({ events, onSelectSymbol }: Readonly<{ events: TodayActionEvent[]; onSelectSymbol: (symbol: string) => void }>) {
  return (
    <section style={{ padding: '0 12px 12px' }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'rgba(16,24,39,0.78)', padding: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ color: 'var(--text)', fontSize: 17, fontWeight: 900 }}>今日操作事件</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 4 }}>把等待价位转成需要盯盘或处理的触发事件。</div>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{events.length} 条</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
          {events.map((event, index) => {
            const tone = severityTone[event.severity]
            const clickable = event.stockCode !== 'AGENT'
            return (
              <button
                key={`${event.eventType}-${event.stockCode}-${index}`}
                type="button"
                onClick={() => clickable && onSelectSymbol(event.stockCode)}
                style={{ border: `1px solid ${tone.border}`, background: tone.bg, color: 'var(--text)', borderRadius: 8, padding: 11, textAlign: 'left', cursor: clickable ? 'pointer' : 'default' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontWeight: 850 }}>{event.stockName}</span>
                  <span style={{ color: tone.color, fontSize: 11, fontWeight: 900 }}>{tone.label}</span>
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.5, marginTop: 6 }}>{event.message}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, lineHeight: 1.45, marginTop: 6 }}>
                  当前 {money(event.currentPrice)} / 相关价 {money(event.relatedPrice)} / 差距 {formatAbsPct(event.distancePct)}
                </div>
                <div style={{ color: 'var(--text)', fontSize: 12, lineHeight: 1.45, marginTop: 6 }}>{event.suggestedAction}</div>
              </button>
            )
          })}
          {events.length === 0 && <div style={{ gridColumn: '1 / -1', border: '1px dashed var(--border)', borderRadius: 8, padding: 14, color: 'var(--text-muted)', fontSize: 13 }}>暂无触发事件；当前以等待计划价位和观察 Agent 状态为主。</div>}
        </div>
      </div>
    </section>
  )
}