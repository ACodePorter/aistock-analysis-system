import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DailyAnalysisPage from '../DailyAnalysisPage'

// Sequence controller
let statusCalls = 0

vi.mock('../../api/dailyAnalysis', () => {
  return {
    fetchLatestAgentReport: vi.fn()
      // first call: no report (simulate backend returns null) -> our component auto triggers run
      .mockResolvedValueOnce(null as any)
      // after generation finishes we return a real report
      .mockResolvedValue({
        generated_at: '2025-10-08T10:05:00Z',
        trade_date: '2025-10-08',
        top_symbols: ['ZZZ','YYY'],
        summary_markdown: '自动生成摘要'
      }),
    fetchStockPoolPage: vi.fn().mockResolvedValue({ page:1, page_size:30, total:0, items: [] }),
    fetchModelPrediction: vi.fn().mockResolvedValue({ generated_at:'2025-10-08T10:05:30Z', model:'demo', predictions: [] }),
    runAgent: vi.fn().mockResolvedValue({ job_id:'job_auto', status:'running' }),
    fetchAgentStatus: vi.fn().mockImplementation(async ()=>{
      statusCalls += 1
      if (statusCalls < 2) return { job_id:'job_auto', status:'running' }
      return { job_id:'job_auto', status:'succeeded' }
    })
  }
})

describe('DailyAnalysisPage auto-run flow', () => {
  beforeEach(()=>{ statusCalls = 0 })
  it('auto triggers agent run when no report then displays generated content', async () => {
    render(<DailyAnalysisPage />)
    // initial empty state
    await waitFor(()=>{
      expect(screen.getByText('Agent 概览')).toBeInTheDocument()
    })
    // After polling completes, the report content should appear
    await waitFor(()=>{
      expect(screen.getByText('生成时间：2025-10-08T10:05:00Z')).toBeInTheDocument()
      expect(screen.getAllByText('ZZZ').length).toBeGreaterThanOrEqual(1)
    }, { timeout: 9000 })
  }, 10000)
})
