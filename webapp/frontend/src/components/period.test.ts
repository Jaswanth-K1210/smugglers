import { describe, expect, it } from 'vitest'
import { defaultPeriod, periodError } from './AreaSearch'
import { isFailedPass, passesOf } from '../services/api'

describe('time-period limits (mirror src/limits.py)', () => {
  it('defaults to the last 12 days ending today', () => {
    const [s, e] = defaultPeriod()
    expect(e).toBe(new Date().toISOString().slice(0, 10))
    expect((Date.parse(e) - Date.parse(s)) / 86400000).toBe(11)
  })
  it('refuses bad periods with a sentence', () => {
    expect(periodError(['2026-09-10', '2026-09-01'])).toMatch(/before the start/)
    expect(periodError(['2026-09-01', '2999-01-01'])).toMatch(/future/)
    expect(periodError(['2014-01-01', '2014-01-20'])).toMatch(/3 Oct 2014/)
    expect(periodError(['', '2026-09-01'])).toMatch(/Pick a start/)
  })
  it('accepts a period of any length (the estimate shows the cost)', () => {
    expect(periodError(['2025-01-01', '2026-08-31'])).toBeNull()
  })
})

describe('passes of a search result', () => {
  const single = { scene: { id: 'A', time: '2026-09-27T02:15:00Z' }, ships: [], sts: [], cached: false, note: '',
    bbox: [0, 0, 1, 1] as [number, number, number, number],
    counts: { ships: 0, ais_unmatched: 0, sts_pairs: 0, sts_pairs_with_silent_hull: 0 } }
  it('treats a single-pass result as one pass', () => {
    expect(passesOf(single)).toHaveLength(1)
    expect(passesOf(null)).toEqual([])
  })
  it('keeps failed passes, marked as failed', () => {
    const failed = { scene: { id: 'B', time: '2026-09-25T14:16:00Z' }, error: 'HTTPError' }
    const period = { passes: [single, failed], passes_found: 3, passes_searched: 2, passes_failed: 1, recurring: [],
      counts: { ships: 0, ais_unmatched: 0, ais_unmatched_spots: 0, weak_candidates: 0, sts_pairs: 0 }, note: null }
    const ps = passesOf(period)
    expect(ps.map(isFailedPass)).toEqual([false, true])
  })
})

describe('box drawn too large', () => {
  it('shrinks to a 50 km box at its centre, inside the limits', async () => {
    const { shrinkBox, boxKm } = await import('./AreaSearch')
    const huge: [number, number, number, number] = [50, 10, 70, 22]            // ~2,100 x 1,300 km
    const [w, h] = boxKm(shrinkBox(huge))
    expect(Math.round(w)).toBe(50)
    expect(Math.round(h)).toBe(50)
    const b = shrinkBox(huge)
    expect(((b[0] + b[2]) / 2).toFixed(6)).toBe('60.000000')
  })
})
