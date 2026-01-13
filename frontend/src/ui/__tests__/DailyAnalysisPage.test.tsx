import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DailyAnalysisPage from '../DailyAnalysisPage'

vi.mock('../../api/dailyAnalysis', () => {
  return {
    // simulate backend nested shape { path, report: {...} }
    fetchLatestAgentReport: vi.fn().mockResolvedValue({
      generated_at: '2025-10-08T10:00:00Z',
      trade_date: '2025-10-08',
      top_symbols: ['AAA','BBB','CCC'],
      summary_markdown: '示例摘要内容'
    }),
    fetchStockPoolPage: vi.fn().mockResolvedValue({
      page:1, page_size:30, total:3,
      items: [
        { symbol:'AAA', first_seen:'2025-10-01', last_seen:'2025-10-08', days_active:6, industry:'电子' },
        { symbol:'BBB', first_seen:'2025-10-02', last_seen:'2025-10-08', days_active:5, industry:'金融' },
        { symbol:'CCC', first_seen:'2025-10-03', last_seen:'2025-10-08', days_active:4, industry:'医药' }
      ]
    }),
    fetchModelPrediction: vi.fn().mockResolvedValue({
      generated_at:'2025-10-08T10:01:00Z',
      model:'demo',
      predictions: []
    }),
    runAgent: vi.fn().mockResolvedValue({ job_id:'abc123', status:'running' })
  }
})

describe('DailyAnalysisPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  it('renders agent and stock pool sections', async () => {
    render(<DailyAnalysisPage />)
    await waitFor(()=>{
      expect(screen.getByText('Agent 概览')).toBeInTheDocument()
      expect(screen.getByText('动态股票池')).toBeInTheDocument()
    })
    // AAA / BBB 可能在多个 section 同时出现（例如 Top20 标签 + 表格行），使用 getAllByText 确认存在即可
    expect(screen.getAllByText('AAA').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('BBB').length).toBeGreaterThanOrEqual(1)
    // runAgent button present
    expect(screen.getByText('生成报告')).toBeInTheDocument()
  })
})
