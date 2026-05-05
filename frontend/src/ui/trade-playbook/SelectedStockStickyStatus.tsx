import React from 'react'
import type { TradePlaybook } from '../../api/tradePlaybook'
import HelpTooltip, { HelpIcon } from '../components/HelpTooltip'
import { helpTips } from '../../config/helpTips'
import { money, rangeText, toneForPlaybook } from './TradePlaybookCard'

export default function SelectedStockStickyStatus({ playbook, current, currentName }: { playbook?: TradePlaybook | null; current?: string; currentName?: string }) {
  const tone = toneForPlaybook(playbook?.actionCategory)
  return (
    <div style={{ margin: '0 12px 12px', border: `1px solid ${tone.border}`, background: 'rgba(15,23,42,0.92)', borderRadius: 8, padding: '9px 12px', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)', fontSize: 12, fontWeight: 850 }}>
        当前状态
        <HelpTooltip {...helpTips.selectedStockStatus}><HelpIcon /></HelpTooltip>
      </div>
      <span style={{ color: 'var(--text)', fontWeight: 900 }}>{playbook?.stockName || currentName || current || '未选择股票'}</span>
      <span style={{ border: `1px solid ${tone.border}`, background: tone.bg, color: tone.fg, borderRadius: 999, padding: '3px 8px', fontSize: 12, fontWeight: 850 }}>{playbook?.actionLabel || '等待剧本'}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>买入：{rangeText(playbook?.buyPlan.idealBuyRange)}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>止损：{money(playbook?.sellPlan.stopLossPrice)}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>目标：{money(playbook?.sellPlan.takeProfitPrice1)} / {money(playbook?.sellPlan.takeProfitPrice2)}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>仓位：{playbook ? `${playbook.buyPlan.maxPositionPct}%` : '-'}</span>
    </div>
  )
}