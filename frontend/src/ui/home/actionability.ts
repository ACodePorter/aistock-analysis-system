import type { AgentStatusSnapshot } from '../../api/agent'
import type { PlaybookAgentView, StockTradePlaybookResponse, TomorrowPlaybookResponse, TradePlaybook } from '../../api/tradePlaybook'

export type ActionableMarketMode = 'active' | 'selective' | 'wait' | 'defensive' | 'avoid'

export type ActionableActionType =
  | 'buy_now'
  | 'near_buy'
  | 'wait_pullback'
  | 'wait_breakout'
  | 'hold'
  | 'reduce'
  | 'sell'
  | 'avoid'

export interface ActionableStockPlan {
  stockCode: string
  stockName: string
  actionType: ActionableActionType
  actionLabel: string
  currentPrice: number | null
  triggerPrice?: number
  triggerRange?: [number, number]
  distanceToTriggerPct?: number
  stopLossPrice?: number | null
  takeProfitPrice1?: number | null
  takeProfitPrice2?: number | null
  priorityScore: number
  confidenceScore: number
  riskScore: number
  oneLineAction: string
  reason: string
  riskWarning?: string
  agentConsensus?: {
    supportingAgents: string[]
    opposingAgents: string[]
    degradedAgents: string[]
  }
}

export interface ActionableTradingDashboard {
  asOfDate: string
  targetTradeDate: string
  summary: {
    plainConclusion: string
    marketMode: ActionableMarketMode
    actionableCount: number
    nearBuyCount: number
    sellSignalCount: number
    avoidCount: number
  }
  executableBuys: ActionableStockPlan[]
  nearBuyCandidates: ActionableStockPlan[]
  breakoutWatch: ActionableStockPlan[]
  holdingActions: ActionableStockPlan[]
  sellOrReduce: ActionableStockPlan[]
  avoidList: ActionableStockPlan[]
  noActionReason?: string
}

export type TodayActionEventType =
  | 'buy_zone_near'
  | 'buy_zone_reached'
  | 'breakout_near'
  | 'breakout_triggered'
  | 'stop_loss_near'
  | 'stop_loss_triggered'
  | 'take_profit_near'
  | 'take_profit_triggered'
  | 'risk_changed'
  | 'agent_degraded'

export interface TodayActionEvent {
  stockCode: string
  stockName: string
  eventType: TodayActionEventType
  severity: 'info' | 'warning' | 'danger' | 'success'
  message: string
  suggestedAction: string
  relatedPrice?: number
  currentPrice?: number | null
  distancePct?: number
}

export interface AgentDecisionTraceItem {
  agentKey: string
  title: string
  stance: 'support' | 'oppose' | 'neutral' | 'degraded'
  summary: string
  points: string[]
  lastRunAt?: string | null
}

export interface AgentDecisionTrace {
  stockCode?: string
  plainSummary: string
  supportingAgents: string[]
  opposingAgents: string[]
  neutralAgents: string[]
  degradedAgents: string[]
  items: AgentDecisionTraceItem[]
}

const NEAR_BUY_THRESHOLD_PCT = 2.5
const NEAR_EXIT_THRESHOLD_PCT = 1.5

function round(value: number | undefined | null, digits = 1) {
  if (value == null || Number.isNaN(value)) return undefined
  const base = 10 ** digits
  return Math.round(value * base) / base
}

export function formatSignedPct(value: number | undefined | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
}

export function formatAbsPct(value: number | undefined | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return `${Math.abs(value).toFixed(1)}%`
}

function money(value: number | undefined | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return value.toFixed(2)
}

function distanceToPricePct(current: number | null | undefined, target: number | null | undefined) {
  if (!current || !target || current <= 0) return undefined
  return ((target - current) / current) * 100
}

function distanceToRangePct(current: number | null | undefined, range: [number, number] | null | undefined) {
  if (!current || !range || current <= 0) return undefined
  const [low, high] = range
  if (current >= low && current <= high) return 0
  const target = current > high ? high : low
  return distanceToPricePct(current, target)
}

function allPlaybooks(data: TomorrowPlaybookResponse | null, selected?: TradePlaybook | null) {
  const map = new Map<string, TradePlaybook>()
  const groups = [
    ...(data?.executableNow || []),
    ...(data?.waitForPullback || []),
    ...(data?.waitForBreakout || []),
    ...(data?.holdWatch || []),
    ...(data?.reduceOrSell || []),
    ...(data?.avoid || []),
  ]
  groups.forEach(item => map.set(item.stockCode, item))
  if (selected) map.set(selected.stockCode, selected)
  return Array.from(map.values())
}

function actionTypeFor(playbook: TradePlaybook): ActionableActionType {
  if (playbook.actionCategory === 'executable_now') return 'buy_now'
  if (playbook.actionCategory === 'wait_for_pullback') return 'near_buy'
  if (playbook.actionCategory === 'wait_for_breakout') return 'wait_breakout'
  if (playbook.actionCategory === 'reduce') return 'reduce'
  if (playbook.actionCategory === 'sell') return 'sell'
  if (playbook.actionCategory === 'avoid') return 'avoid'
  return 'hold'
}

function riskScore(playbook: TradePlaybook) {
  const map: Record<string, number> = { low: 20, medium: 45, high: 75, extreme: 92 }
  return map[String(playbook.riskLevel || '').toLowerCase()] ?? 50
}

function triggerDistance(playbook: TradePlaybook, actionType: ActionableActionType) {
  if (actionType === 'buy_now' || actionType === 'near_buy' || actionType === 'wait_pullback') {
    return distanceToRangePct(playbook.currentPrice, playbook.buyPlan.idealBuyRange)
  }
  if (actionType === 'wait_breakout') return distanceToPricePct(playbook.currentPrice, playbook.buyPlan.breakoutBuyAbove)
  if (actionType === 'reduce' || actionType === 'sell') {
    return distanceToPricePct(playbook.currentPrice, playbook.sellPlan.stopLossPrice || playbook.sellPlan.takeProfitPrice1)
  }
  return undefined
}

function triggerPrice(playbook: TradePlaybook, actionType: ActionableActionType) {
  if (actionType === 'wait_breakout') return playbook.buyPlan.breakoutBuyAbove || undefined
  if (actionType === 'reduce' || actionType === 'sell') return playbook.sellPlan.stopLossPrice || playbook.sellPlan.takeProfitPrice1 || undefined
  return undefined
}

function oneLineAction(playbook: TradePlaybook, actionType: ActionableActionType, distancePct?: number) {
  const current = money(playbook.currentPrice)
  const range = playbook.buyPlan.idealBuyRange
  if (actionType === 'buy_now' && range) {
    return `当前 ${current} 已在计划买入区 ${money(range[0])}-${money(range[1])}，只适合按仓位上限小仓观察。`
  }
  if ((actionType === 'near_buy' || actionType === 'wait_pullback') && range) {
    return `当前 ${current}，距离低吸区 ${money(range[0])}-${money(range[1])} 约 ${formatAbsPct(distancePct)}，回落到计划内且未放量下跌再考虑。`
  }
  if (actionType === 'wait_breakout') {
    return `当前 ${current}，距离突破确认价 ${money(playbook.buyPlan.breakoutBuyAbove)} 约 ${formatAbsPct(distancePct)}，需要放量确认后再看。`
  }
  if (actionType === 'reduce' || actionType === 'sell') {
    return `当前 ${current}，若已持有需优先看止损 ${money(playbook.sellPlan.stopLossPrice)} 与目标 ${money(playbook.sellPlan.takeProfitPrice1)}。`
  }
  if (actionType === 'avoid') return `当前 ${current}，风险或性价比不足，今日不新增买入。`
  return `当前 ${current}，以持有观察和计划内价位为主，不追高。`
}

function agentConsensus(response: StockTradePlaybookResponse | null | undefined, playbook: TradePlaybook) {
  if (response?.playbook.stockCode !== playbook.stockCode) return undefined
  const views = response.agentViews || {}
  const supportingAgents: string[] = []
  const opposingAgents: string[] = []
  Object.entries(views).forEach(([key, view]) => {
    if (!view) return
    const stance = String(view.stance || '').toLowerCase()
    if (['support', 'positive', 'buy', 'strong_buy', 'low'].includes(stance)) supportingAgents.push(view.title || key)
    else if (['risk', 'negative', 'sell', 'strong_sell', 'high', 'extreme'].includes(stance)) opposingAgents.push(view.title || key)
  })
  return { supportingAgents, opposingAgents, degradedAgents: [] }
}

function toPlan(playbook: TradePlaybook, stockResponse?: StockTradePlaybookResponse | null): ActionableStockPlan {
  const actionType = actionTypeFor(playbook)
  const distancePct = round(triggerDistance(playbook, actionType), 1)
  const risk = riskScore(playbook)
  const priorityScore = Math.max(0, Math.min(100, Math.round((playbook.confidenceScore || 0) - risk * 0.25 - Math.abs(distancePct || 0) * 2)))
  return {
    stockCode: playbook.stockCode,
    stockName: playbook.stockName,
    actionType,
    actionLabel: playbook.actionLabel,
    currentPrice: playbook.currentPrice,
    triggerPrice: triggerPrice(playbook, actionType),
    triggerRange: playbook.buyPlan.idealBuyRange || undefined,
    distanceToTriggerPct: distancePct,
    stopLossPrice: playbook.sellPlan.stopLossPrice,
    takeProfitPrice1: playbook.sellPlan.takeProfitPrice1,
    takeProfitPrice2: playbook.sellPlan.takeProfitPrice2,
    priorityScore,
    confidenceScore: playbook.confidenceScore || 0,
    riskScore: risk,
    oneLineAction: oneLineAction(playbook, actionType, distancePct),
    reason: playbook.reasons?.[0]?.plainText || playbook.plainSummary,
    riskWarning: playbook.riskSummary,
    agentConsensus: agentConsensus(stockResponse, playbook),
  }
}

function byPriority(left: ActionableStockPlan, right: ActionableStockPlan) {
  const leftDistance = Math.abs(left.distanceToTriggerPct ?? 99)
  const rightDistance = Math.abs(right.distanceToTriggerPct ?? 99)
  return right.priorityScore - left.priorityScore || leftDistance - rightDistance
}

function deriveMarketMode(plans: ActionableStockPlan[]): ActionableMarketMode {
  if (plans.some(item => item.actionType === 'buy_now')) return 'active'
  if (plans.some(item => item.actionType === 'near_buy' || item.actionType === 'wait_breakout')) return 'selective'
  if (plans.some(item => item.actionType === 'sell' || item.actionType === 'reduce')) return 'defensive'
  if (plans.some(item => item.actionType === 'avoid')) return 'avoid'
  return 'wait'
}

export function buildActionableTradingDashboard(data: TomorrowPlaybookResponse | null, stockResponse?: StockTradePlaybookResponse | null): ActionableTradingDashboard {
  const plans = allPlaybooks(data, stockResponse?.playbook).map(item => toPlan(item, stockResponse)).sort(byPriority)
  const executableBuys = plans.filter(item => item.actionType === 'buy_now')
  const nearBuyCandidates = plans.filter(item => item.actionType === 'near_buy' || item.actionType === 'wait_pullback').sort(byPriority)
  const breakoutWatch = plans.filter(item => item.actionType === 'wait_breakout').sort(byPriority)
  const holdingActions = plans.filter(item => item.actionType === 'hold').sort(byPriority)
  const sellOrReduce = plans.filter(item => item.actionType === 'sell' || item.actionType === 'reduce').sort(byPriority)
  const avoidList = plans.filter(item => item.actionType === 'avoid').sort(byPriority)
  const noActionReason = executableBuys.length
    ? undefined
    : `当前没有满足立即买入条件的股票；可重点盯 ${nearBuyCandidates.length} 只接近买点、${breakoutWatch.length} 只突破确认、${sellOrReduce.length} 只减仓/止损信号。`
  const plainConclusion = executableBuys.length
    ? `当前有 ${executableBuys.length} 只股票进入计划买入区，仍需按仓位和止损执行。`
    : noActionReason || '当前样本不足，先补齐交易剧本数据。'
  return {
    asOfDate: data?.asOfDate || stockResponse?.playbook.asOfDate || new Date().toISOString().slice(0, 10),
    targetTradeDate: data?.targetTradeDate || stockResponse?.playbook.targetTradeDate || new Date().toISOString().slice(0, 10),
    summary: {
      plainConclusion,
      marketMode: deriveMarketMode(plans),
      actionableCount: executableBuys.length,
      nearBuyCount: nearBuyCandidates.length + breakoutWatch.length,
      sellSignalCount: sellOrReduce.length,
      avoidCount: avoidList.length,
    },
    executableBuys,
    nearBuyCandidates,
    breakoutWatch,
    holdingActions,
    sellOrReduce,
    avoidList,
    noActionReason,
  }
}

export function buildTodayActionEvents(dashboard: ActionableTradingDashboard, statuses: AgentStatusSnapshot[] = []): TodayActionEvent[] {
  const events: TodayActionEvent[] = []
  const addPlanEvent = (plan: ActionableStockPlan, eventType: TodayActionEventType, severity: TodayActionEvent['severity'], message: string, suggestedAction: string, relatedPrice?: number | null) => {
    events.push({
      stockCode: plan.stockCode,
      stockName: plan.stockName,
      eventType,
      severity,
      message,
      suggestedAction,
      relatedPrice: relatedPrice ?? undefined,
      currentPrice: plan.currentPrice,
      distancePct: plan.distanceToTriggerPct,
    })
  }

  dashboard.executableBuys.slice(0, 4).forEach(plan => addPlanEvent(plan, 'buy_zone_reached', 'success', `${plan.stockName} 已进入计划买入区。`, '仅在计划仓位内小仓观察，并设置止损。', plan.triggerRange?.[1]))
  dashboard.nearBuyCandidates.filter(plan => Math.abs(plan.distanceToTriggerPct ?? 99) <= NEAR_BUY_THRESHOLD_PCT).slice(0, 4).forEach(plan => addPlanEvent(plan, 'buy_zone_near', 'info', `${plan.stockName} 距离低吸区约 ${formatAbsPct(plan.distanceToTriggerPct)}。`, '加入今日盯盘，未回到计划区不追。', plan.triggerRange?.[1]))
  dashboard.breakoutWatch.filter(plan => Math.abs(plan.distanceToTriggerPct ?? 99) <= NEAR_BUY_THRESHOLD_PCT).slice(0, 4).forEach(plan => addPlanEvent(plan, 'breakout_near', 'info', `${plan.stockName} 距离突破价约 ${formatAbsPct(plan.distanceToTriggerPct)}。`, '只在放量确认后观察，不用盘中临时追高。', plan.triggerPrice))

  const exitPlans = [...dashboard.holdingActions, ...dashboard.sellOrReduce]
  exitPlans.forEach(plan => {
    const stopDistance = distanceToPricePct(plan.currentPrice, plan.stopLossPrice)
    const takeDistance = distanceToPricePct(plan.currentPrice, plan.takeProfitPrice1)
    if (stopDistance != null && stopDistance >= -NEAR_EXIT_THRESHOLD_PCT && stopDistance <= 0) {
      addPlanEvent(plan, 'stop_loss_near', 'warning', `${plan.stockName} 距离止损价约 ${formatAbsPct(stopDistance)}。`, '若已持有，需要提前设好减仓或止损条件。', plan.stopLossPrice)
    }
    if (stopDistance != null && stopDistance > 0) {
      addPlanEvent(plan, 'stop_loss_triggered', 'danger', `${plan.stockName} 已低于计划止损价。`, '若已持有，本轮短线计划应视为失效。', plan.stopLossPrice)
    }
    if (takeDistance != null && takeDistance <= NEAR_EXIT_THRESHOLD_PCT && takeDistance >= 0) {
      addPlanEvent(plan, 'take_profit_near', 'success', `${plan.stockName} 距离第一目标约 ${formatAbsPct(takeDistance)}。`, '若已持有，可准备分批止盈或上移止损。', plan.takeProfitPrice1)
    }
    if (takeDistance != null && takeDistance < 0) {
      addPlanEvent(plan, 'take_profit_triggered', 'success', `${plan.stockName} 已触及或超过第一目标。`, '避免恋战，按计划考虑分批止盈。', plan.takeProfitPrice1)
    }
  })

  statuses.filter(item => ['failed', 'degraded', 'disabled'].includes(item.status)).slice(0, 3).forEach(item => {
    events.push({
      stockCode: 'AGENT',
      stockName: item.displayName,
      eventType: 'agent_degraded',
      severity: item.status === 'failed' ? 'danger' : 'warning',
      message: `${item.displayName} 当前状态为 ${item.status}。`,
      suggestedAction: '查看 Agent 日志，确认该 Agent 是否影响当前交易剧本。',
    })
  })

  return events.sort((left, right) => severityRank(right.severity) - severityRank(left.severity)).slice(0, 10)
}

function severityRank(severity: TodayActionEvent['severity']) {
  return { danger: 4, warning: 3, success: 2, info: 1 }[severity]
}

function traceStance(view: PlaybookAgentView | null | undefined, status?: AgentStatusSnapshot): AgentDecisionTraceItem['stance'] {
  if (status && ['failed', 'degraded', 'disabled'].includes(status.status)) return 'degraded'
  const stance = String(view?.stance || '').toLowerCase()
  if (['support', 'positive', 'buy', 'strong_buy', 'low'].includes(stance)) return 'support'
  if (['risk', 'negative', 'sell', 'strong_sell', 'high', 'extreme'].includes(stance)) return 'oppose'
  return 'neutral'
}

export function buildAgentDecisionTrace(response: StockTradePlaybookResponse | null, statuses: AgentStatusSnapshot[] = []): AgentDecisionTrace {
  const views = response?.agentViews || {}
  const statusMap = new Map(statuses.map(item => [item.agentName, item]))
  const items = Object.entries(views).filter(([, view]) => !!view).map(([key, view]) => {
    const title = view?.title || key
    const matchedStatus = Array.from(statusMap.values()).find(status => title.includes(status.displayName.replace(' Agent', '')) || title.includes(status.agentName.replace('Agent', '')))
    return {
      agentKey: key,
      title,
      stance: traceStance(view, matchedStatus),
      summary: view?.points?.[0] || '该 Agent 暂无明确说明。',
      points: view?.points || [],
      lastRunAt: matchedStatus?.lastRunAt,
    }
  })
  const supportingAgents = items.filter(item => item.stance === 'support').map(item => item.title)
  const opposingAgents = items.filter(item => item.stance === 'oppose').map(item => item.title)
  const neutralAgents = items.filter(item => item.stance === 'neutral').map(item => item.title)
  const degradedAgents = items.filter(item => item.stance === 'degraded').map(item => item.title)
  const plainSummary = response
    ? `当前 ${response.playbook.stockName} 结论由 ${items.length} 个 Agent 视角参与，${supportingAgents.length} 个支持，${opposingAgents.length} 个提示风险，${degradedAgents.length} 个降级。`
    : '请选择股票后查看 Agent 决策链。'
  return {
    stockCode: response?.playbook.stockCode,
    plainSummary,
    supportingAgents,
    opposingAgents,
    neutralAgents,
    degradedAgents,
    items,
  }
}