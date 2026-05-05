import React from 'react'
import { Tooltip } from 'antd'
import type { TooltipPlacement } from 'antd/es/tooltip'
import type { HelpTip } from '../../config/helpTips'

type HelpTooltipProps = Partial<HelpTip> & {
  placement?: TooltipPlacement
  maxWidth?: number
  children: React.ReactElement
}

export default function HelpTooltip({ title, content, examples, placement = 'top', maxWidth = 320, children }: HelpTooltipProps) {
  const normalizedTitle = typeof title === 'string' ? title.trim() : title
  const normalizedContent = typeof content === 'string' ? content.trim() : ''
  if (!normalizedContent && !normalizedTitle && !examples?.length) return children

  const overlay = (
    <div style={{ maxWidth }}>
      {normalizedTitle && <div style={{ color: 'var(--text)', fontWeight: 850, fontSize: 12, marginBottom: 5 }}>{normalizedTitle}</div>}
      {normalizedContent && <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.55, whiteSpace: 'pre-line' }}>{normalizedContent}</div>}
      {examples?.length ? (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {examples.map((example, index) => (
            <div key={`${example}-${index}`} style={{ color: 'var(--text-muted)', opacity: 0.82, fontSize: 11, lineHeight: 1.45 }}>
              {example}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )

  return (
    <Tooltip title={overlay} placement={placement} trigger={['hover', 'click']} mouseEnterDelay={0.15} destroyOnHidden classNames={{ root: 'help-tooltip-dark' }} zIndex={10000}>
      <span className="help-tooltip-trigger">
        {children}
      </span>
    </Tooltip>
  )
}

export const HelpIcon = React.forwardRef<HTMLSpanElement, { label?: string }>(function HelpIcon({ label = '查看说明' }, ref) {
  return (
    <span
      ref={ref}
      aria-label={label}
      role="img"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 16,
        height: 16,
        borderRadius: 999,
        border: '1px solid var(--border)',
        color: 'var(--text-muted)',
        background: 'rgba(255,255,255,0.035)',
        fontSize: 11,
        fontWeight: 850,
        cursor: 'help',
        lineHeight: 1,
        flex: '0 0 auto',
      }}
    >
      ?
    </span>
  )
})