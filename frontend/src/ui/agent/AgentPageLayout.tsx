import React from 'react'

type AgentPageShellProps = Readonly<{
  eyebrow?: string
  title: string
  subtitle: string
  actions?: React.ReactNode
  children: React.ReactNode
}>

type AgentPanelProps = Readonly<{
  title?: string
  subtitle?: string
  extra?: React.ReactNode
  className?: string
  children: React.ReactNode
}>

export function AgentPageShell({ eyebrow = 'AGENT RUNTIME', title, subtitle, actions, children }: AgentPageShellProps) {
  return (
    <div className="agent-page-shell">
      <header className="agent-page-header">
        <div className="agent-page-title-block">
          <div className="agent-page-eyebrow">{eyebrow}</div>
          <h1 className="agent-page-title">{title}</h1>
          <div className="agent-page-subtitle">{subtitle}</div>
        </div>
        {actions && <div className="agent-page-actions">{actions}</div>}
      </header>
      {children}
    </div>
  )
}

export function AgentPanel({ title, subtitle, extra, className, children }: AgentPanelProps) {
  const panelClassName = className ? `agent-panel ${className}` : 'agent-panel'
  return (
    <section className={panelClassName}>
      {(title || subtitle || extra) && (
        <div className="agent-panel-header">
          <div>
            {title && <div className="agent-panel-title">{title}</div>}
            {subtitle && <div className="agent-panel-subtitle">{subtitle}</div>}
          </div>
          {extra && <div className="agent-panel-extra">{extra}</div>}
        </div>
      )}
      {children}
    </section>
  )
}