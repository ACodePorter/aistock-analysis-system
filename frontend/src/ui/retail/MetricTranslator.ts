type MetricContext = Record<string, any>

function asNumber(value: unknown): number | null {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function asPercent(value: unknown): number | null {
  const number = asNumber(value)
  if (number == null) return null
  return Math.abs(number) <= 1 ? number * 100 : number
}

export function explainMetricForRetailUser(metricName: string, value: unknown, context: MetricContext = {}): string {
  const key = metricName.toLowerCase().replace(/[_\s-]/g, '')
  const number = asNumber(value)
  const percent = asPercent(value)

  if (key.includes('directionaccuracy') || key.includes('方向准确率')) {
    if (percent == null) return '方向准确率样本不足，不能用它单独决定买卖。'
    if (percent < 45) return `最近模型判断涨跌方向不太稳定（约${percent.toFixed(0)}%），因此不建议重仓相信单次预测。`
    if (percent < 58) return `最近模型方向判断一般（约${percent.toFixed(0)}%），适合作为辅助参考。`
    return `最近模型方向判断相对较好（约${percent.toFixed(0)}%），但仍需要配合止损和仓位控制。`
  }

  if (key.includes('mape') || key.includes('价格误差')) {
    if (percent == null) return '价格误差样本不足，预测价格只能保守参考。'
    if (percent >= 8) return `最近价格预测误差偏大（约${percent.toFixed(1)}%），建议只作为参考，不适合激进买入。`
    if (percent >= 4) return `最近价格预测误差中等（约${percent.toFixed(1)}%），价位区间比单点价格更值得参考。`
    return `最近价格预测误差较小（约${percent.toFixed(1)}%），但仍不能代表未来一定按模型运行。`
  }

  if (key.includes('intervalhit') || key.includes('区间命中率')) {
    if (percent == null) return '预测区间样本不足，暂时不能评价区间可靠性。'
    if (percent >= 80) return `最近实际价格大多落在模型预测范围内（约${percent.toFixed(0)}%），价格波动范围参考价值较高。`
    if (percent >= 55) return `预测区间有一定参考价值（约${percent.toFixed(0)}%），但需要给价格波动留余地。`
    return `预测区间命中率偏低（约${percent.toFixed(0)}%），不宜把上下沿当成硬目标。`
  }

  if (key.includes('riskscore') || key.includes('风险评分')) {
    if (number == null) return '风险评分不足，按中性偏谨慎处理。'
    if (number >= 70) return `当前风险偏高（${number.toFixed(0)}/100），适合观望或小仓，不适合重仓。`
    if (number >= 45) return `当前风险中等（${number.toFixed(0)}/100），可以看机会，但必须设置止损。`
    return `当前风险相对较低（${number.toFixed(0)}/100），仍需控制单只股票仓位。`
  }

  if (key === 'rsi' || key.includes('rsi')) {
    if (number == null) return 'RSI 暂无有效数据。'
    if (number >= 70) return `RSI 约${number.toFixed(0)}，短线可能偏热，不适合追高。`
    if (number <= 30) return `RSI 约${number.toFixed(0)}，短线可能偏冷，可以观察是否出现止跌。`
    return `RSI 约${number.toFixed(0)}，短线热度处在相对中性区间。`
  }

  if (key.includes('macd')) {
    if (number == null) return 'MACD 暂无有效数据。'
    return number > 0 ? 'MACD 偏多，说明短线动能有改善迹象。' : 'MACD 偏弱，说明短线动能还没有明显转强。'
  }

  if (key.includes('mainnet') || key.includes('主力净流入')) {
    if (number == null) return '主力资金数据不足，不能判断资金是否持续流入。'
    if (number > 0) return '资金行为显示主力可能在净流入，但还需要看是否连续。'
    if (number < 0) return '资金行为显示主力可能在净流出，短线需要更谨慎。'
    return '主力资金基本持平，对短线方向帮助有限。'
  }

  if (key.includes('snr') || key.includes('信噪比')) {
    if (number == null) return '信噪比不足，暂时不适合把模型信号看得太重。'
    if (number >= 1.5) return '信号相对噪声更明显，模型判断可作为较重要参考。'
    return '信号噪声较多，短线判断更容易反复。'
  }

  const label = context.label || metricName
  return `${label} 当前值为 ${value ?? '暂无'}，建议结合趋势、资金和风险一起看。`
}