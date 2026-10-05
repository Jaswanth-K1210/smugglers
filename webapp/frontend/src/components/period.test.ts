import { describe, expect, it } from 'vitest'
import { defaultPeriod, periodError, MAX_PERIOD_DAYS } from './AreaSearch'
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
    expect(periodError(['2026-08-01', '2026-09-15'])).toMatch(new RegExp(`at most ${MAX_PERIOD_DAYS} days`))
    expect(periodError(['', '2026-09-01'])).toMatch(/Pick a start/)
  })
  it('accepts exactly 31 days', () => {
    expect(periodError(['2026-08-01', '2026-08-31'])).toBeNull()
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
