import React from 'react'

function finiteOrNull(value: unknown): number | null {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function directionLabel(direction: unknown): string | null {
  if (direction === 'bullish') return '看涨'
  if (direction === 'bearish') return '看跌'
  if (direction === 'sideways') return '震荡'
  return null
}

function evaluationStatusLabel(status: unknown): string | null {
  if (status === 'pending_target_date') return '等待验证'
  if (status === 'missing_actual_price') return '缺少收盘价'
  if (status === 'invalid_prediction_data') return '预测无效'
  return null
}

/**
 * CustomChartTooltip
 *
 * 价格走势 & 预测区间图的 tooltip。与 utils/mergePriceAndPredictions 强耦合：
 *   - 同一个 X 轴日期可能出现 2~3 行：historical / historical_anchor / prediction
 *   - 'historical_anchor' 只是为了让收盘线和预测线视觉相连的桥接行（yhat=lastClose），
 *     必须从 tooltip 中过滤掉，否则会出现 "实际收盘 ¥X / 预测均值 ¥X / 区间(X~X)"
 *     这种全部数值相同的视觉错觉（2026-04-24 截图反馈的真实 bug）。
 *   - 'historical' 行只贡献 close；'prediction' 行只贡献 yhat/yl/yu/actual。
 */
export const CustomChartTooltip: React.FC<any> = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null

  const rawRows: any[] = payload
    .map((p: any) => p?.payload)
    .filter((r: any) => r)
  const anchorRow = rawRows.find((r: any) => r.type === 'historical_anchor')
  const rows: any[] = rawRows.filter((r: any) => r.type !== 'historical_anchor')

  if (rows.length === 0 && !anchorRow) return null

  const histRow = rows.find((r: any) => r.type === 'historical')
  const predRow = rows.find((r: any) => r.type === 'prediction')
  const data = predRow ?? histRow ?? anchorRow ?? rows[0]

  const close = finiteOrNull(histRow?.close ?? anchorRow?.forecastBasePrice)
  const yhat = finiteOrNull(predRow?.forecastMean ?? predRow?.forecastMeanExpired ?? predRow?.yhat ?? predRow?.yhat_expired)
  const yl = finiteOrNull(predRow?.forecastLower ?? predRow?.forecastLowerExpired ?? predRow?.yl ?? predRow?.yl_expired)
  const yu = finiteOrNull(predRow?.forecastUpper ?? predRow?.forecastUpperExpired ?? predRow?.yu ?? predRow?.yu_expired)
  const actual = predRow?.actual ?? null
  const errorPct = predRow?.error_pct
  const directionOk = predRow?.direction_ok
  const isExpired = predRow?.predictionStatus === 'expired'
  const signalLevel = predRow?.signal_level
  const directionSnr = predRow?.direction_snr
  const forecastReturnPct = finiteOrNull(predRow?.forecastReturnPct)
  const forecastDirection = directionLabel(predRow?.forecastDirection)
  const d1Yhat = histRow?.history_d1_yhat ?? null
  const d5Yhat = histRow?.history_d5_yhat ?? null

  const renderHistoryPrediction = (
    label: string,
    value: number | null,
    errorPct?: number | null,
    signedErrorPct?: number | null,
    directionOk?: boolean | null,
    intervalHit?: boolean | null,
    status?: string | null,
    color: string = '#f59e0b',
  ) => {
    if (value == null) return null
    const statusLabel = evaluationStatusLabel(status)
    return (
      <div style={{marginBottom: 4}}>
        <span style={{color: 'rgba(226, 232, 240, 0.7)'}}>{label}: </span>
        <span style={{fontWeight: 500, color}}>¥{Number(value).toFixed(2)}</span>
        {errorPct != null && (
          <span style={{marginLeft: 6, color: Number(errorPct) < 5 ? '#10b981' : '#f59e0b'}}>
            偏差 {signedErrorPct != null ? `${Number(signedErrorPct) >= 0 ? '+' : ''}${Number(signedErrorPct).toFixed(2)}%` : `${Number(errorPct).toFixed(2)}%`}
          </span>
        )}
        {statusLabel && <span style={{marginLeft: 6, color: '#f59e0b'}}>{statusLabel}</span>}
        {directionOk != null && (
          <span style={{marginLeft: 6, color: directionOk ? '#10b981' : '#ef4444'}}>
            {directionOk ? '方向对' : '方向错'}
          </span>
        )}
        {intervalHit != null && (
          <span style={{marginLeft: 6, color: intervalHit ? '#10b981' : '#ef4444'}}>
            {intervalHit ? '命中区间' : '区间外'}
          </span>
        )}
      </div>
    )
  }

  return (
    <div data-testid="custom-chart-tooltip" style={{
      background: 'rgba(30, 41, 59, 0.95)',
      border: '1px solid rgba(148, 163, 184, 0.3)',
      borderRadius: 6,
      padding: '8px 12px',
      fontSize: 11,
      color: '#e2e8f0',
      boxShadow: '0 4px 12px rgba(0, 0, 0, 0.6)',
      minWidth: 180,
      lineHeight: 1.4,
    }}>
      <div style={{fontWeight: 600, marginBottom: 6, color: '#f1f5f9'}}>{data.date}</div>

      {close != null && (
        <div style={{marginBottom: 4}}>
          <span style={{color: 'rgba(226, 232, 240, 0.7)'}}>实际收盘: </span>
          <span style={{fontWeight: 500}}>¥{Number(close).toFixed(2)}</span>
        </div>
      )}

      {anchorRow && !predRow && (
        <div style={{
          marginBottom: 4,
          paddingTop: close != null ? 4 : 0,
          color: 'rgba(226, 232, 240, 0.7)',
        }}>
          <div><span style={{color: '#cbd5e1'}}>类型: </span>预测起点</div>
          <div style={{fontSize: 10, marginTop: 2}}>该点用于连接历史价格与未来预测，不参与未来收益统计</div>
        </div>
      )}

      {yhat != null && (
        <div style={{marginBottom: 4}}>
          <span style={{color: 'rgba(226, 232, 240, 0.7)'}}>预测主线: </span>
          <span style={{fontWeight: 500, color: isExpired ? '#9ca3af' : '#8884d8'}}>
            ¥{Number(yhat).toFixed(2)}
          </span>
          {isExpired && <span style={{marginLeft: 6, color: '#9ca3af', fontSize: 9}}>已过期</span>}
        </div>
      )}

      {yl != null && yu != null && (
        <div style={{marginBottom: 4, fontSize: 10, color: 'rgba(226, 232, 240, 0.6)'}}>
          区间: ({Number(yl).toFixed(2)} ~ {Number(yu).toFixed(2)})
        </div>
      )}

      {predRow && (forecastReturnPct != null || forecastDirection) && (
        <div style={{marginBottom: 4, fontSize: 10, color: 'rgba(226, 232, 240, 0.65)'}}>
          {forecastReturnPct != null && (
            <span>相对预测起点: {forecastReturnPct >= 0 ? '+' : ''}{forecastReturnPct.toFixed(2)}%</span>
          )}
          {forecastDirection && (
            <span style={{marginLeft: forecastReturnPct != null ? 8 : 0}}>方向倾向: {forecastDirection}</span>
          )}
          <div style={{marginTop: 2}}>类型: {isExpired ? '过期预测' : '未来预测'}</div>
        </div>
      )}

      {(d1Yhat != null || d5Yhat != null) && (
        <div style={{
          marginTop: 6,
          paddingTop: 6,
          borderTop: '1px solid rgba(148, 163, 184, 0.2)',
        }}>
          {renderHistoryPrediction(
            '历史预测D-1',
            d1Yhat,
            histRow?.history_d1_error_pct,
            histRow?.history_d1_signed_error_pct,
            histRow?.history_d1_direction_ok,
            histRow?.history_d1_interval_hit,
            histRow?.history_d1_status,
            '#f59e0b',
          )}
          {renderHistoryPrediction(
            '历史预测D-5',
            d5Yhat,
            histRow?.history_d5_error_pct,
            histRow?.history_d5_signed_error_pct,
            histRow?.history_d5_direction_ok,
            histRow?.history_d5_interval_hit,
            histRow?.history_d5_status,
            '#10b981',
          )}
        </div>
      )}

      {errorPct != null && actual != null && (
        <div style={{
          marginTop: 6,
          paddingTop: 6,
          borderTop: '1px solid rgba(148, 163, 184, 0.2)',
          marginBottom: 4
        }}>
          <div style={{marginBottom: 3}}>
            <span style={{color: 'rgba(226, 232, 240, 0.7)'}}>偏差: </span>
            <span style={{
              fontWeight: 600,
              color: errorPct < 2 ? '#10b981' : errorPct < 5 ? '#f59e0b' : '#ef4444'
            }}>
              {Number(errorPct).toFixed(2)}%
            </span>
          </div>
          {directionOk !== undefined && (
            <div>
              <span style={{color: 'rgba(226, 232, 240, 0.7)'}}>方向: </span>
              <span style={{
                fontWeight: 600,
                color: directionOk ? '#10b981' : '#ef4444'
              }}>
                {directionOk ? '✓ 正确' : '✗ 错误'}
              </span>
            </div>
          )}
        </div>
      )}

      {signalLevel && signalLevel !== 'neutral' && (
        <div style={{
          marginTop: 4,
          paddingTop: 4,
          borderTop: '1px solid rgba(148, 163, 184, 0.2)',
          fontSize: 10
        }}>
          <span style={{color: 'rgba(226, 232, 240, 0.7)'}}>信号等级: </span>
          <span style={{
            fontWeight: 600,
            color: String(signalLevel).includes('bullish') ? '#10b981' : '#ef4444'
          }}>
            {String(signalLevel).replace(/_/g, ' ')}
          </span>
          {directionSnr != null && (
            <div style={{marginTop: 2, color: 'rgba(226, 232, 240, 0.6)'}}>
              SNR: {Number(directionSnr).toFixed(2)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default CustomChartTooltip
