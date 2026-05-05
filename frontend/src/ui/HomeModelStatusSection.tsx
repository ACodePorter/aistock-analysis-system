import React from 'react'
import FloatingModule from './FloatingModule'
import FundFlowPanel from './FundFlowPanel'
import ModelStatusPanel from './ModelStatusPanel'
import PredictionInsightCard from './PredictionInsightCard'
import type { PredictionHistoryResponse, StockInsightResponse } from '../api/report'

type HomeModelStatusSectionProps = {
  current?: string
  predictionHistory: PredictionHistoryResponse | null
  predictionHistoryLoading: boolean
  insight: StockInsightResponse | null
  insightLoading: boolean
  running: boolean
  onRunDaily: () => void
  onOpenDiagnostics: (symbol: string) => void
}

export default function HomeModelStatusSection({
  current,
  predictionHistory,
  predictionHistoryLoading,
  insight,
  insightLoading,
  running,
  onRunDaily,
  onOpenDiagnostics,
}: HomeModelStatusSectionProps) {
  return (
    <>
      <FloatingModule style={{padding:12, borderRadius:12}}>
        <ModelStatusPanel
          symbol={current}
          data={predictionHistory}
          insight={insight}
          loading={predictionHistoryLoading}
          insightLoading={insightLoading}
          running={running}
          onRunDaily={onRunDaily}
          onOpenDiagnostics={() => current && onOpenDiagnostics(current)}
        />
        <div style={{marginTop:12}}>
          <FundFlowPanel variant="content" />
        </div>
      </FloatingModule>

      {current && (
        <FloatingModule style={{padding:0, borderRadius:12, overflow:'hidden'}}>
          <PredictionInsightCard insight={insight} loading={insightLoading} />
        </FloatingModule>
      )}
    </>
  )
}