import React from 'react'

type FloatingModuleProps = {
  title?: React.ReactNode
  subtitle?: React.ReactNode
  rightActions?: React.ReactNode
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
}

export default function FloatingModule({
  title,
  subtitle,
  rightActions,
  children,
  className,
  style,
}: FloatingModuleProps) {
  return (
    <div className={['card-panel', className].filter(Boolean).join(' ')} style={style}>
      {(title || subtitle || rightActions) && (
        <div className="card-panel-header">
          <div>
            {title && <div className="card-panel-title">{title}</div>}
            {subtitle && <div className="card-panel-subtitle">{subtitle}</div>}
          </div>
          {rightActions}
        </div>
      )}
      {children}
    </div>
  )
}
