import { describe, expect, it } from 'vitest'
import { explainMetricForRetailUser } from '../MetricTranslator'

describe('explainMetricForRetailUser', () => {
  it('explains direction accuracy as a percentage', () => {
    expect(explainMetricForRetailUser('direction_accuracy', 0.62)).toContain('62%')
    expect(explainMetricForRetailUser('direction_accuracy', 0.42)).toContain('不太稳定')
  })

  it('explains MAPE without implying certainty', () => {
    const text = explainMetricForRetailUser('mape', 0.085)
    expect(text).toContain('误差偏大')
    expect(text).toContain('只作为参考')
  })

  it('explains risk score for retail users', () => {
    expect(explainMetricForRetailUser('risk_score', 76)).toContain('不适合重仓')
    expect(explainMetricForRetailUser('风险评分', 28)).toContain('控制单只股票仓位')
  })

  it('explains technical and fund-flow metrics', () => {
    expect(explainMetricForRetailUser('RSI', 72)).toContain('不适合追高')
    expect(explainMetricForRetailUser('MACD', -0.2)).toContain('短线动能')
    expect(explainMetricForRetailUser('主力净流入', -1200000)).toContain('净流出')
  })

  it('falls back to the provided label for unknown metrics', () => {
    expect(explainMetricForRetailUser('custom_metric', 12, { label: '自定义指标' })).toContain('自定义指标')
  })
})