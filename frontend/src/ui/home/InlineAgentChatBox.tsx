import React from 'react'
import AgentChatPanel from '../agent/conversation/AgentChatPanel'

export default function InlineAgentChatBox({
  selectedStockCode,
  selectedMode = 'professional',
  onOpenLogs,
}: Readonly<{
  selectedStockCode?: string
  selectedMode?: 'normal' | 'professional'
  onOpenLogs: (taskId?: string) => void
}>) {
  return (
    <section style={{ padding: '0 12px 12px' }}>
      <AgentChatPanel
        scope="home"
        currentPage="home"
        selectedStockCode={selectedStockCode}
        selectedMode={selectedMode}
        onOpenLogs={onOpenLogs}
      />
    </section>
  )
}
