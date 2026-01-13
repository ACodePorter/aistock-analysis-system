import { describe, it, expect } from 'vitest'
import { sliceByTimeRange, TRADING_DAY_RANGE } from '../utils/rangeSlice'

// Additional comprehensive tests to ensure consistency if mapping changes.
describe('TRADING_DAY_RANGE mapping + sliceByTimeRange', () => {
  const make = (n:number) => Array.from({length:n}, (_,i)=>({ idx: i+1 }))

  Object.entries(TRADING_DAY_RANGE).forEach(([key, limit]) => {
    if(!limit) return // skip 'all'
    it(`timeRange ${key} limits to last ${limit} rows`, () => {
      const src = make(limit + 10)
      const out = sliceByTimeRange(src, key)
      expect(out.length).toBe(limit)
      expect(out[0].idx).toBe(src.length - limit + 1)
      expect(out[out.length-1].idx).toBe(src.length)
    })
  })

  it('does not mutate original array', () => {
    const src = make(30)
    const copy = src.slice()
    sliceByTimeRange(src, '5d')
    expect(src).toEqual(copy)
  })

  it('returns shallow copy when not truncated', () => {
    const src = make(4)
    const out = sliceByTimeRange(src, '5d')
    expect(out).not.toBe(src)
    expect(out).toEqual(src)
  })
})
