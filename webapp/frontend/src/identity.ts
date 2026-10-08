import type { AisSilentShip, SearchShip } from './services/api'

/** A guess at which ship a radar detection without AIS could be. Always "possible", never an identification. */
export interface IdentityGuess {
  name: string
  mmsi: string | null
  detail: string            // flag, type, IMO
  basis: string             // why this ship, in one sentence
  strength: 'stronger' | 'weaker'
  others: string[]          // other possible names, best first
}

const hrs = (h: number) => (h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(h < 10 ? 1 : 0)} h`)

/** Ranks the evidence already in a search result:
 *  3  a nearby AIS ship whose report, carried forward at its speed, fits here, and whose length fits the hull
 *  2  a ship whose AIS was silent across the pass and could have been here (best detour first)
 *  1  a nearby AIS ship that fits here, length unknown
 *  A nearby ship whose length clearly does not fit is never offered. */
export function guessIdentity(ship: SearchShip, silent: AisSilentShip[] = []): IdentityGuess | null {
  if (ship.category !== 'AIS_UNMATCHED') return null
  const opts: (IdentityGuess & { score: number })[] = []
  for (const c of ship.ais_candidates ?? []) {
    if (!c.plausible || !c.name || c.size === 'mismatch') continue
    const when = c.minutes_from_pass < 0 ? `${-c.minutes_from_pass} min before` : `${c.minutes_from_pass} min after`
    opts.push({
      name: c.name, mmsi: c.mmsi ?? null, detail: [c.flag, c.ais_length_m && `${c.ais_length_m} m`].filter(Boolean).join(' · '),
      basis: `Reported AIS ${when} the pass; carried forward at its speed it lands ${(c.distance_m / 1000).toFixed(1)} km from here` +
        (c.size === 'consistent' ? ', and its reported length fits the radar hull.' : '.'),
      strength: c.size === 'consistent' ? 'stronger' : 'weaker', score: c.size === 'consistent' ? 3 : 1, others: [],
    })
  }
  ;(ship.ais_silent_match ?? []).forEach((key, i) => {
    const r = silent.find((x) => x.key === key)
    if (!r) return
    opts.push({
      name: r.name ?? (r.mmsi ? `MMSI ${r.mmsi}` : 'Unnamed ship'), mmsi: r.mmsi,
      detail: [r.flag, r.type, r.imo && `IMO ${r.imo}`].filter(Boolean).join(' · '),
      basis: `Its AIS was silent across the pass (off ${hrs(r.off.hours_before)} before, back on ${hrs(r.on.hours_after)} after) ` +
        'and it could have been here at the pass time.',
      strength: 'weaker', score: 2 - i * 0.1, others: [],
    })
  })
  if (!opts.length) return null
  opts.sort((a, b) => b.score - a.score)
  const [best, ...rest] = opts
  const { score: _score, ...guess } = best
  return { ...guess, others: [...new Set(rest.map((o) => o.name).filter((n) => n !== best.name))].slice(0, 3) }
}
