import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchTomorrowPlaybook, fetchTradePlaybook } from '../tradePlaybook'

const mockFetch = vi.fn()

describe('tradePlaybook api helpers', () => {
  beforeEach(() => {
    mockFetch.mockReset()
    vi.stubGlobal('fetch', mockFetch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetches tomorrow playbook with the requested limit', async () => {
    const payload = { asOfDate: '2026-04-26', executableNow: [] }
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    })

    await expect(fetchTomorrowPlaybook(7)).resolves.toBe(payload)

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8090/api/dashboard/tomorrow-playbook?limit=7',
      { cache: 'no-store' },
    )
  })

  it('fetches stock playbook with an encoded stock code', async () => {
    const payload = { playbook: { stockCode: '002460.SZ' } }
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    })

    await expect(fetchTradePlaybook('002460.SZ')).resolves.toBe(payload)

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8090/api/stocks/002460.SZ/trade-playbook',
      { cache: 'no-store' },
    )
  })

  it('throws response text when the request fails', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      text: () => Promise.resolve('playbook unavailable'),
    })

    await expect(fetchTomorrowPlaybook()).rejects.toThrow('playbook unavailable')
  })
})