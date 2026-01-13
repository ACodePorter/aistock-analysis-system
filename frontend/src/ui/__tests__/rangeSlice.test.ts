import { describe, it, expect } from 'vitest'
import { slice5d, sliceByTimeRange } from '../utils/rangeSlice'

describe('slice5d legacy helper', () => {
  it('returns last 5 elements preserving order', () => {
    const src = [1,2,3,4,5,6,7]
    expect(slice5d(src)).toEqual([3,4,5,6,7])
  })
  it('returns all if less than 5', () => {
    const src = [10,11,12]
    expect(slice5d(src)).toEqual([10,11,12])
  })
})

describe('sliceByTimeRange generic', () => {
  const make = (n:number) => Array.from({length:n}, (_,i)=>i+1)
  const cases: [string, number, number][] = [
    ['5d', 30, 5],
    ['1m', 60, 22],
    ['3m', 120, 66],
    ['6m', 200, 132],
    ['1y', 400, 250],
  ]
  cases.forEach(([range, total, expectLen])=>{
    it(`range ${range} keeps last ${expectLen}`, () => {
      const src = make(total)
      const out = sliceByTimeRange(src, range)
      expect(out.length).toBe(expectLen)
      // last element preserved
      expect(out[out.length-1]).toBe(total)
    })
  })
  it('all returns full dataset', () => {
    const src = make(37)
    expect(sliceByTimeRange(src, 'all')).toEqual(src)
  })
  it('unknown range returns full dataset', () => {
    const src = make(18)
    expect(sliceByTimeRange(src, 'unknown')).toEqual(src)
  })
  it('short dataset not truncated', () => {
    const src = make(3)
    expect(sliceByTimeRange(src, '5d')).toEqual(src)
  })
})

