/**
 * Trading day limits for each supported UI time range.
 * These are approximate trading day counts (assumes ~22 trading days per month).
 * 'all' and unknown keys fall back to returning the full dataset.
 */
export const TRADING_DAY_RANGE: Record<string, number | undefined> = {
  '5d': 5,
  '1m': 22,
  '3m': 66,
  '6m': 132,
  '1y': 250,
  'all': undefined
}

/**
 * Slice an array of time‑ordered rows (oldest -> newest) to the last N trading
 * days for the given timeRange. If the input is already shorter than the cap
 * it is returned as‑is. The function is side‑effect free (never mutates input).
 *
 * NOTE: The array is expected to be chronological (ascending by date). If you
 * pass data in another order, sort it first. Predictions should be appended
 * AFTER slicing historical data so that visualization range is strict while
 * still showing future points.
 */
export function sliceByTimeRange<T>(rows: T[], timeRange: string): T[] {
  const limit = TRADING_DAY_RANGE[timeRange]
  if (!limit || rows.length <= limit) return rows.slice()
  return rows.slice(rows.length - limit)
}

/** Convenience helper specifically for 5d (used by legacy test). */
export function slice5d<T>(rows: T[]): T[] { return sliceByTimeRange(rows, '5d') }
