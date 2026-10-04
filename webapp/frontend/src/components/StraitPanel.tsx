import React, { useEffect, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { apiService, StraitCrossing } from '../services/api'
import { Panel } from './Panel'

const flagEmoji = (iso2: string) => String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 127397 + c.charCodeAt(0)))
const tanker = (c: StraitCrossing) => /tanker|lng|lpg/i.test(c.category ?? '')

// How long a ship was not observed while crossing: a reception gap or AIS switched off,
// the feed cannot tell which. Colour marks length only, never a verdict.
const gapTone = (h: number | null) => (h ?? 0) >= 72 ? 'border-unmatched/50 bg-unmatched/10 text-unmatched'
  : (h ?? 0) >= 24 ? 'border-partial/50 bg-partial/10 text-partial' : 'border-rule text-ink-3'

export const StraitPanel: React.FC<{ className?: string; onShip: (name: string) => void }> = ({ className, onShip }) => {
  const [hours, setHours] = useState(48)
  const [sort, setSort] = useState<'gap' | 'new'>('gap')
  const [data, setData] = useState<{ crossings: StraitCrossing[]; source: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setData(null); setError(null)
    const load = () => apiService.getStraitCrossings(hours)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e instanceof Error ? e.message : 'Crossings are unavailable right now.'))
    load()
    const t = setInterval(load, 10 * 60 * 1000)
    return () => { live = false; clearInterval(t) }
  }, [hours])

  const rows = [...(data?.crossings ?? [])].sort((a, b) =>
    sort === 'gap' ? (b.unobserved_h ?? 0) - (a.unobserved_h ?? 0) : b.at.localeCompare(a.at))
  const inbound = rows.filter((c) => c.direction === 'inbound').length
  const longest = rows.reduce((m, c) => Math.max(m, c.unobserved_h ?? 0), 0)
  const stats: [string, string | number][] = [
    ['Into the Gulf', inbound], ['Out to sea', rows.length - inbound],
    ['Tankers', rows.filter(tanker).length], ['Longest unobserved', `${Math.round(longest)} h`],
  ]

  return (
    <Panel title="Strait of Hormuz crossings" count={data ? rows.length : undefined} className={className} bodyClassName="flex flex-col"
      right={
        <span className="flex gap-1">
          {[24, 48, 168].map((h) => (
            <button key={h} onClick={() => setHours(h)} aria-pressed={hours === h}
              className={hours === h ? 'pill-live' : 'pill text-ink-2 hover:border-[#444]'}>{h === 168 ? '7 d' : `${h} h`}</button>
          ))}
        </span>
      }>
      <dl className="grid grid-cols-4 border-b border-rule text-center">
        {stats.map(([k, v]) => (
          <div key={k} className="border-rule px-1 py-2 [&:not(:last-child)]:border-r">
            <dd className="text-lg font-bold text-ink">{data ? v : '–'}</dd>
            <dt className="text-[10px] uppercase tracking-wider text-ink-3">{k}</dt>
          </div>
        ))}
      </dl>
      <div className="flex items-center justify-between border-b border-rule px-3 py-1.5 text-[10px] uppercase tracking-wider text-ink-3">
        <span>Click a ship to find it on the map</span>
        <button onClick={() => setSort(sort === 'gap' ? 'new' : 'gap')} className="uppercase hover:text-ink">
          Sort: {sort === 'gap' ? 'longest unobserved' : 'newest'}
        </button>
      </div>
      <ul className="max-h-80 flex-1 overflow-y-auto">
        {!data && !error && <li className="px-3 py-3 text-xs text-ink-3">Loading crossings…</li>}
        {error && <li role="alert" className="px-3 py-3 text-xs text-unmatched">{error}</li>}
        {data && !rows.length && <li className="px-3 py-3 text-xs text-ink-2">No crossings in this period.</li>}
        {rows.map((c, i) => (
          <li key={`${c.name}-${c.at}-${i}`} className="border-b border-rule last:border-b-0">
            <button onClick={() => c.name && onShip(c.name)} disabled={!c.name}
              className="grid w-full grid-cols-[1.25rem_1fr_auto] items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.03]">
              <span aria-label={c.direction === 'inbound' ? 'Into the Persian Gulf' : 'Out to the Gulf of Oman'}
                className={`text-sm ${c.direction === 'inbound' ? 'text-signal' : 'text-[#5FE0E6]'}`}>
                {c.direction === 'inbound' ? '↖' : '↘'}
              </span>
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 truncate text-xs text-ink">
                  {c.flag && <span title={c.flag}>{flagEmoji(c.flag)}</span>}
                  <span className="truncate font-medium">{c.name ?? 'Unnamed'}</span>
                  {tanker(c) && <span className="badge !bg-[#F0473E]/20 !text-[#F0473E]">tanker</span>}
                </span>
                <span className="block truncate text-[10px] text-ink-3">
                  {c.category ?? 'Unknown type'}{c.dwt ? `, ${Math.round(c.dwt / 1000)}k t` : ''}
                  {c.destination ? `, to ${c.destination}` : ''}, {formatDistanceToNow(new Date(c.at), { addSuffix: true })}
                </span>
              </span>
              <span className={`whitespace-nowrap border px-1.5 py-0.5 text-[10px] ${gapTone(c.unobserved_h)}`}
                title="Hours the ship was not observed between leaving one gulf and appearing in the other: a coverage gap or AIS switched off; the feed cannot tell which.">
                {c.unobserved_h != null ? `${Math.round(c.unobserved_h)} h unobserved` : 'seen crossing'}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="border-t border-rule px-3 py-1.5 text-[10px] leading-snug text-ink-3">
        Unobserved time is a coverage gap or AIS switched off, not proof of either. Source: {data?.source ?? 'Hormuz Ship Monitor'}.
      </p>
    </Panel>
  )
}
