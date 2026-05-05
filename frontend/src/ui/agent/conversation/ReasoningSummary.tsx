import React from 'react'

export default function ReasoningSummary({ items }: Readonly<{ items: string[] }>) {
  if (!items.length) return null
  return (
    <section className="agent-answer-section">
      <div className="agent-answer-section-title">我的分析过程</div>
      <ol className="agent-reasoning-list">
        {items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
      </ol>
    </section>
  )
}
