import React from 'react'
import { Alert } from 'antd'

export default function RiskWarningCard({ warnings }: Readonly<{ warnings: string[] }>) {
  if (!warnings.length) return null
  return (
    <section className="agent-answer-section">
      <Alert
        type="warning"
        showIcon
        message="风险提示"
        description={warnings.map((item, index) => <div key={`${index}-${item}`}>{item}</div>)}
      />
    </section>
  )
}
