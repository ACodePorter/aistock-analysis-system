import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AgentRunLog, AgentSkillUsageLog } from '../../../api/agent'
import AgentRunTimeline from '../AgentRunTimeline'


describe('AgentRunTimeline', () => {
  it('renders an empty state when no events are available', () => {
    render(<AgentRunTimeline agentRuns={[]} skillUsages={[]} />)

    expect(screen.getByText('暂无可展示的执行链路。')).toBeInTheDocument()
  })

  it('merges agent runs and skill usages in chronological order', () => {
    const agentRuns: AgentRunLog[] = [
      {
        runId: 'run_1',
        taskId: 'task_1',
        pipelineRunId: 'pipe_1',
        agentName: 'DataStatusAgent',
        status: 'success',
        inputSummary: '检查数据',
        outputSummary: '数据状态正常',
        startedAt: '2026-04-27T09:01:00',
        finishedAt: '2026-04-27T09:01:01',
        durationMs: 120,
        error: null,
        usedDataSources: ['prices_daily'],
        usedSkills: ['check_data_freshness'],
        output: {},
      },
    ]
    const skillUsages: AgentSkillUsageLog[] = [
      {
        usageId: 'usage_1',
        skillKey: 'check_data_freshness',
        skillName: 'Freshness Skill',
        ownerAgent: 'DataStatusAgent',
        taskId: 'task_1',
        pipelineRunId: 'pipe_1',
        agentRunId: 'run_1',
        status: 'success',
        startedAt: '2026-04-27T09:00:30',
        finishedAt: '2026-04-27T09:00:31',
        durationMs: 80,
        inputSummary: null,
        outputSummary: '价格和预测数据可用',
        error: null,
        triggeredBy: 'scheduler',
        dataSourcesUsed: ['forecasts'],
      },
    ]

    const { container } = render(<AgentRunTimeline agentRuns={agentRuns} skillUsages={skillUsages} />)
    const text = container.textContent || ''

    expect(screen.getByText('Freshness Skill')).toBeInTheDocument()
    expect(screen.getAllByText('DataStatusAgent')).toHaveLength(2)
    expect(screen.getByText('价格和预测数据可用')).toBeInTheDocument()
    expect(screen.getByText('数据状态正常')).toBeInTheDocument()
    expect(text.indexOf('Freshness Skill')).toBeLessThan(text.indexOf('DataStatusAgent'))
  })
})