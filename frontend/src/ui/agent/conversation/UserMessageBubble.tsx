import React from 'react'
import type { AgentUserMessage } from './types'

function formatTime(value: string) {
  return value.slice(11, 16)
}

export default function UserMessageBubble({ message }: Readonly<{ message: AgentUserMessage }>) {
  return (
    <div className="agent-user-message-row">
      <div className="agent-user-message-bubble">
        <div className="agent-message-meta">你 · {formatTime(message.timestamp)}</div>
        <div className="agent-message-content">{message.content}</div>
      </div>
    </div>
  )
}
