import React from 'react'
import { Tag } from 'antd'
import type { AgentUserFacingAnswer } from '../../../api/agent'
import ActionPlanCard from './ActionPlanCard'
import ReasoningSummary from './ReasoningSummary'
import RelatedStocksBar from './RelatedStocksBar'
import RiskWarningCard from './RiskWarningCard'
import TechnicalTraceCollapse from './TechnicalTraceCollapse'

function confidenceText(value: AgentUserFacingAnswer['conclusion']['confidence']) {
  if (value === 'high') return '高置信度'
  if (value === 'medium') return '中等置信度'
  return '低置信度'
}

function riskText(value: AgentUserFacingAnswer['conclusion']['riskLevel']) {
  if (value === 'high') return '高风险'
  if (value === 'medium') return '中风险'
  return '低风险'
}

export default function AssistantAnswerCard({ answer, onOpenLogs }: Readonly<{ answer: AgentUserFacingAnswer; onOpenLogs?: (taskId?: string) => void }>) {
  const findings = answer.keyFindings || { positive: [], negative: [], neutral: [] }
  return (
    <article className="agent-assistant-card">
      <div className="agent-assistant-header">
        <div>
          <div className="agent-message-meta">AI 分析</div>
          <h3>{answer.title}</h3>
        </div>
        <div className="agent-answer-tags">
          <Tag color={answer.conclusion.confidence === 'high' ? 'green' : 'gold'}>{confidenceText(answer.conclusion.confidence)}</Tag>
          <Tag color={answer.conclusion.riskLevel === 'high' ? 'red' : 'blue'}>{riskText(answer.conclusion.riskLevel)}</Tag>
        </div>
      </div>
      <section className="agent-direct-answer">
        <div className="agent-answer-section-title">直接结论</div>
        <p>{answer.directAnswer}</p>
      </section>
      <RelatedStocksBar stocks={answer.relatedStocks || []} />
      <ReasoningSummary items={answer.reasoningSummary || []} />
      {!!(findings.positive?.length || findings.negative?.length || findings.neutral?.length) && (
        <section className="agent-answer-section">
          <div className="agent-answer-section-title">关键原因</div>
          <div className="agent-findings-grid">
            {findings.positive?.map(item => <div className="agent-finding agent-finding-positive" key={`positive-${item}`}>{item}</div>)}
            {findings.negative?.map(item => <div className="agent-finding agent-finding-negative" key={`negative-${item}`}>{item}</div>)}
            {findings.neutral?.map(item => <div className="agent-finding agent-finding-neutral" key={`neutral-${item}`}>{item}</div>)}
          </div>
        </section>
      )}
      <ActionPlanCard items={answer.actionPlan || []} />
      <RiskWarningCard warnings={[...(answer.riskWarnings || []), ...(answer.dataQuality?.warning ? [answer.dataQuality.warning] : [])]} />
      <TechnicalTraceCollapse taskId={answer.taskId} trace={answer.technicalTrace || []} onOpenLogs={onOpenLogs} />
    </article>
  )
}
