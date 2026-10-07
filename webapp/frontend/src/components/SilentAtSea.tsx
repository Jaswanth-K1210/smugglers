import React, { useEffect, useState } from 'react'
import { apiService, SilentFeed, SilentShip } from '../services/api'
import { Panel } from './Panel'

// 'NO' -> 🇳🇴 (regional indicator letters)
const flagEmoji = (iso2: string) => String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 127397 + c.charCodeAt(0)))
const hours = (h: number) => (h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(h < 10 ? 1 : 0)} h`)
const TABS = [['silent', 'Silent now'], ['back', 'Back on'], ['all', 'All']] as const

/** Worldwide ranking: ships whose AIS went silent at sea while other ships nearby were still heard. */
export const SilentAtSea: React.FC<{ className?: string; onShip: (s: SilentShip) => void }> = ({ className, onShip }) => {
  const [tab, setTab] = useState<'silent' | 'back' | 'all'>('silent')
  const [feed, setFeed] = useState<SilentFeed | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // refreshes every minute; a failed load (server waking or restarting) retries in 30 s
    let live = true, timer: ReturnType<typeof setTimeout>
    const load = () => apiService.getSilentShips(tab)
      .then((d) => { if (!live) return; setFeed(d); setError(null); timer = setTimeout(load, 60000) })
      .catch((e) => { if (!live) return; setError(`${e instanceof Error ? e.message : 'Could not load'}. Retrying…`); timer = setTimeout(load, 30000) })
    setFeed(null)
    load()
    return () => { live = false; clearTimeout(timer) }
  }, [tab])

  const ships = feed?.ships ?? []
  const rule = feed?.rule
  return (
    <Panel title="AIS stopped at sea, worldwide" count={feed ? ships.length : undefined} className={className} bodyClassName="flex flex-col"
      right={<span className="text-[10px] text-ink-3">last 24 h</span>}>
      <div className="flex gap-1 border-b border-rule px-3 py-2" role="tablist" aria-label="Which ships">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={tab === id ? 'pill-live' : 'pill text-ink-2 hover:border-[#444]'}>{label}</button>
        ))}
      </div>
      <ol className="max-h-80 flex-1 overflow-y-auto">
        {!feed && !error && <li className="px-3 py-3 text-xs text-ink-3">Loading…</li>}
        {error && <li className="px-3 py-3 text-xs text-partial">{error}</li>}
        {feed && !ships.length && (
          <li className="px-3 py-3 text-xs text-ink-2">
            {tab === 'back' ? 'No ship has come back on yet.' : 'No ship has gone silent at sea yet.'} The list is collected from
            the live feed since the server started {hours(feed.since_s / 3600)} ago.
          </li>
        )}
        {ships.map((s, i) => (
          <li key={s.mmsi} className="border-b border-rule last:border-b-0">
            <button onClick={() => onShip(s)} className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-white/[0.03]">
              <span className="w-5 shrink-0 pt-0.5 text-right text-[11px] text-ink-3">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-sans text-[13px] text-ink">
                  {s.flag && <span title={s.flag.country}>{flagEmoji(s.flag.iso2)} </span>}{s.name || `MMSI ${s.mmsi}`}
                  <span className="text-[11px] text-ink-3"> {[s.type, s.length_m && `${s.length_m} m`].filter(Boolean).join(' · ')}</span>
                </span>
                <span className="block text-[11px] text-ink-2">
                  Last heard {hours(s.off.ago_h)} ago at {s.sog.toFixed(0)} kn, course {Math.round(s.cog)}°
                  {s.destination ? `, bound for ${s.destination}` : ''}
                </span>
                {s.on && <span className="block text-[11px] text-signal">Back on after {hours(s.silent_h)}, {s.on.moved_km.toFixed(0)} km away</span>}
              </span>
              <span className={`shrink-0 border px-1.5 py-0.5 text-[11px] ${s.on ? 'border-rule text-ink-2' : s.silent_h >= 3 ? 'border-unmatched/50 text-unmatched' : 'border-partial/50 text-partial'}`}
                title="How long its AIS was silent">
                {hours(s.silent_h)}
              </span>
            </button>
          </li>
        ))}
      </ol>
      {rule && (
        <p className="border-t border-rule px-3 py-2 text-[10px] leading-relaxed text-ink-3">
          Under way at ≥ {rule.min_kn} kn, then nothing for {rule.after_min} min while ≥ {rule.min_heard} other ships were still
          heard within {rule.heard_km} km of where it was and of where it should be by now. Ships that simply sailed out of
          receiver range are left out. A silence is a lead, not proof: AIS also drops out through faults and collisions.
        </p>
      )}
    </Panel>
  )
}
