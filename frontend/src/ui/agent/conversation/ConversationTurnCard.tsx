import React from 'react'
import { Alert, Button, Popconfirm, Tooltip } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import AssistantAnswerCard from './AssistantAnswerCard'
import UserMessageBubble from './UserMessageBubble'
import type { ConversationTurn } from './types'

function renderTurnBody(turn: ConversationTurn, onOpenLogs?: (taskId?: string) => void) {
  if (turn.assistantAnswer) {
    return <AssistantAnswerCard answer={turn.assistantAnswer} onOpenLogs={onOpenLogs} />
  }
  if (turn.status === 'failed') {
    return <Alert type="error" showIcon message="分析失败" description={turn.task.progressText || 'Agent 对话失败，请稍后重试。'} />
  }
  return (
    <div className="agent-thinking-card">
      <div className="agent-thinking-pulse" />
      <span>{turn.task.progressText || '正在综合分析'}</span>
    </div>
  )
}

export default function ConversationTurnCard({ turn, confirming, onConfirm, onOpenLogs, onDelete }: Readonly<{ turn: ConversationTurn; confirming?: boolean; onConfirm?: (turn: ConversationTurn) => void; onOpenLogs?: (taskId?: string) => void; onDelete?: (turnId: string) => void }>) {
  return (
    <div className="agent-turn-card">
      {onDelete && (
        <div className="agent-turn-actions">
          <Popconfirm title="删除这条对话？" okText="删除" cancelText="取消" onConfirm={() => onDelete(turn.id)}>
            <Tooltip title="删除这条对话">
              <Button aria-label="删除这条对话" icon={<DeleteOutlined />} size="small" danger />
            </Tooltip>
          </Popconfirm>
        </div>
      )}
      <UserMessageBubble message={turn.userMessage} />
      {renderTurnBody(turn, onOpenLogs)}
      {turn.task.requiresConfirmation && turn.task.taskId && onConfirm && (
        <div className="agent-confirm-row">
          <Button danger type="primary" loading={confirming} onClick={() => onConfirm(turn)}>确认执行</Button>
        </div>
      )}
    </div>
  )
}
