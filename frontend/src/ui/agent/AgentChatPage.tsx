import React from 'react'
import { Tag } from 'antd'
import AgentChatPanel from './conversation/AgentChatPanel'
import { AgentPageShell } from './AgentPageLayout'

export default function AgentChatPage({ selectedStockCode }: Readonly<{ selectedStockCode?: string | null }>) {
  const openAgentLogs = React.useCallback((taskId?: string) => {
    const query = taskId ? `?taskId=${encodeURIComponent(taskId)}` : ''
    try { globalThis.location.hash = `#agent-logs${query}` } catch { /* noop */ }
  }, [])

  return (
    <AgentPageShell
      title="Agent Chat"
      subtitle="面向用户问题的智能分析对话。默认展示综合结论，技术链路按需展开。"
      actions={selectedStockCode ? <Tag color="blue">上下文 {selectedStockCode}</Tag> : undefined}
    >
      <AgentChatPanel
        scope="agent-chat"
        currentPage="agent-chat"
        selectedStockCode={selectedStockCode || undefined}
        selectedMode="professional"
        onOpenLogs={openAgentLogs}
      />
    </AgentPageShell>
  )
}
