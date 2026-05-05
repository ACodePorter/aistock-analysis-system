import React from 'react'
import { Button } from 'antd'

export default function QuickQuestionChips({ questions, loading, onPick }: Readonly<{ questions: string[]; loading?: boolean; onPick: (question: string) => void }>) {
  return (
    <div className="agent-quick-chips">
      {questions.map(item => (
        <Button key={item} size="small" onClick={() => onPick(item)} loading={loading}>{item}</Button>
      ))}
    </div>
  )
}
