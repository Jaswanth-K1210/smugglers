import { describe, expect, it } from 'vitest'
import { guessIdentity } from './identity'
import type { AisSilentShip, SearchShip } from './services/api'

const ship = (extra: Partial<SearchShip> = {}): SearchShip => ({
  id: 0, lat: 25.2, lon: 56.5, length_m: 240, beam_m: 40, conf: 0.6, category: 'AIS_UNMATCHED', n_ais: 0,
  reasons: [], chip_png: null, ...extra })
const cand = (name: string, size: 'consistent' | 'mismatch' | null, plausible = true) => ({
  id: 'g1', name, source: 'Global Fishing Watch', distance_m: 1800, minutes_from_pass: -35, speed_needed_kn: 9,
  ais_length_m: 245, size, plausible, mmsi: '538001', flag: 'MHL' })
const silent: AisSilentShip[] = [{ key: 'k1', mmsi: '636', name: 'QUIET ONE', flag: 'LBR', imo: '9300001', callsign: null, type: 'tanker',
  off: { time: 'a', lat: 25, lon: 56, hours_before: 3 }, on: { time: 'b', lat: 25.4, lon: 57, hours_after: 2 }, silent_h: 5, could_be: [0] }]

describe('which ship a radar detection without AIS could be', () => {
  it('prefers a nearby AIS ship whose position and length both fit', () => {
    const g = guessIdentity(ship({ ais_candidates: [cand('FITS WELL', 'consistent')], ais_silent_match: ['k1'] }), silent)!
    expect(g.name).toBe('FITS WELL')
    expect(g.strength).toBe('stronger')
    expect(g.others).toEqual(['QUIET ONE'])
  })
  it('falls back to a ship whose AIS was silent across the pass', () => {
    const g = guessIdentity(ship({ ais_silent_match: ['k1'] }), silent)!
    expect(g.name).toBe('QUIET ONE')
    expect(g.detail).toBe('LBR · tanker · IMO 9300001')
    expect(g.basis).toMatch(/silent across the pass/)
  })
  it('never offers a ship whose length does not fit, an implausible one, or a ship that has AIS', () => {
    expect(guessIdentity(ship({ ais_candidates: [cand('TOO SMALL', 'mismatch'), cand('TOO FAR', null, false)] }))).toBeNull()
    expect(guessIdentity(ship({ category: 'AIS_VISIBLE', ais_silent_match: ['k1'] }), silent)).toBeNull()
  })
})
