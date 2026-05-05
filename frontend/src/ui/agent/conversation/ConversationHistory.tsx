import React from 'react'
import { Empty } from 'antd'
import ConversationTurnCard from './ConversationTurnCard'
import type { ConversationTurn } from './types'

export default function ConversationHistory({ turns, confirmingTaskId, onConfirm, onOpenLogs, onDelete }: Readonly<{ turns: ConversationTurn[]; confirmingTaskId?: string | null; onConfirm?: (turn: ConversationTurn) => void; onOpenLogs?: (taskId?: string) => void; onDelete?: (turnId: string) => void }>) {
  const bottomRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    if (typeof bottomRef.current?.scrollIntoView === 'function') {
      bottomRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [turns.length, turns.at(-1)?.updatedAt])

  if (!turns.length) {
    return (
      <div className="agent-history-empty">
        <Empty description="还没有对话。你可以直接询问交易结论、持仓处理或 Agent 判断依据。" />
      </div>
    )
  }

  return (
    <div className="agent-conversation-history">
      {turns.map(turn => (
        <ConversationTurnCard
          key={turn.id}
          turn={turn}
          confirming={confirmingTaskId === turn.task.taskId}
          onConfirm={onConfirm}
          onOpenLogs={onOpenLogs}
          onDelete={onDelete}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
