import React from 'react'
import { Button, Input, Space, Tag } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import QuickQuestionChips from './QuickQuestionChips'

export default function AgentInputBox({
  value,
  loading,
  selectedStockCode,
  quickQuestions,
  onChange,
  onSubmit,
}: Readonly<{
  value: string
  loading: boolean
  selectedStockCode?: string | null
  quickQuestions: string[]
  onChange: (value: string) => void
  onSubmit: (message?: string) => void
}>) {
  return (
    <div className="agent-input-box">
      <Input.TextArea
        value={value}
        onChange={event => onChange(event.target.value)}
        onPressEnter={event => {
          if (!event.shiftKey) {
            event.preventDefault()
            onSubmit()
          }
        }}
        placeholder="问 Agent：为什么今天没有可以买的股票？"
        autoSize={{ minRows: 3, maxRows: 6 }}
      />
      <Space wrap>
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => onSubmit()}>发送</Button>
        <Button onClick={() => onChange('')} disabled={!value}>清空</Button>
        {selectedStockCode && <Tag color="blue">上下文 {selectedStockCode}</Tag>}
      </Space>
      <QuickQuestionChips questions={quickQuestions} loading={loading} onPick={onSubmit} />
    </div>
  )
}
