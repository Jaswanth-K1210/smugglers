import React, { useEffect, useState } from 'react'
import { apiService, MySearches as Data, PastSearch } from '../services/api'
import { boxKm } from './AreaSearch'

const when = (t: number) => new Date(t * 1000).toUTCString().slice(5, 22)
const STATE: Record<PastSearch['status'], string> = {
  done: 'text-signal', running: 'text-partial', queued: 'text-partial', error: 'text-unmatched',
}

/** Left drawer: the user's own searches, with today's allowance and totals; a click reopens one. */
export const MySearches: React.FC<{ open: boolean; onClose: () => void; onOpen: (s: PastSearch) => void }> = ({ open, onClose, onOpen }) => {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let live = true
    setError(null)
    apiService.getMySearches()
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e instanceof Error ? e.message : 'Could not load your searches.'))
    return () => { live = false }
  }, [open])

  if (!open) return null
  const rows = data?.searches ?? []
  const done = rows.filter((r) => r.status === 'done')
  const sum = (k: 'ships' | 'ais_unmatched' | 'sts_pairs') => done.reduce((n, r) => n + (r.summary?.[k] ?? 0), 0)
  const stats: [string, React.ReactNode][] = data ? [
    ['Searches', rows.length],
    ['Today', `${data.today.searches} / ${data.today.daily_searches}`],
    ['Work today', `${data.today.units} / ${data.today.daily_units}`],
    ['Ships found', sum('ships').toLocaleString()],
    ['No AIS', sum('ais_unmatched').toLocaleString()],
    ['Pairs', sum('sts_pairs')],
  ] : []

  return (
    <aside className="fixed bottom-0 left-0 top-10 z-[1100] flex w-[360px] max-w-full flex-col border-r border-rule bg-surface shadow-2xl"
      role="dialog" aria-label="My searches">
      <header className="flex items-center justify-between border-b border-rule px-3 py-2">
        <h2 className="text-[11px] font-bold uppercase tracking-wider text-ink">My searches</h2>
        <button onClick={onClose} aria-label="Close my searches" className="px-1 text-xl leading-none text-ink-2 hover:text-ink">×</button>
      </header>
      {error && <p role="alert" className="p-3 text-xs text-unmatched">{error}</p>}
      {!data && !error && <p className="p-3 text-xs text-ink-3">Loading…</p>}
      {data && (
        <>
          <dl className="grid grid-cols-3 border-b border-rule text-center">
            {stats.map(([k, v]) => (
              <div key={k} className="border-b border-r border-rule px-1 py-2 [&:nth-child(3n)]:border-r-0">
                <dd className="text-base font-bold text-ink">{v}</dd>
                <dt className="text-[9px] uppercase tracking-wider text-ink-3">{k}</dt>
              </div>
            ))}
          </dl>
          <ol className="flex-1 overflow-y-auto">
            {!rows.length && <li className="p-3 text-xs text-ink-2">No searches yet. Draw an area on the map and press Go.</li>}
            {rows.map((r) => {
              const [w, h] = r.bbox ? boxKm(r.bbox) : [0, 0]
              return (
                <li key={r.job_id} className="border-b border-rule">
                  <button onClick={() => onOpen(r)} className="block w-full px-3 py-2 text-left hover:bg-white/[0.03]">
                    <span className="flex items-center justify-between text-[11px]">
                      <span className="text-ink">{when(r.created)} UTC</span>
                      <span className={`uppercase ${STATE[r.status]}`}>{r.status}</span>
                    </span>
                    <span className="block text-[11px] text-ink-3">
                      {w.toFixed(0)} × {h.toFixed(0)} km at {r.bbox[1].toFixed(2)}°, {r.bbox[0].toFixed(2)}°
                      {r.period ? ` · ${r.period[0]} to ${r.period[1]}` : ''}
                    </span>
                    {r.summary && (
                      <span className="block text-[11px] text-ink-2">
                        {r.summary.passes ?? '?'} pass{r.summary.passes === 1 ? '' : 'es'} · {r.summary.ships ?? 0} ships ·{' '}
                        <span className={r.summary.ais_unmatched ? 'text-unmatched' : ''}>{r.summary.ais_unmatched ?? 0} no AIS</span>
                        {r.summary.sts_pairs ? ` · ${r.summary.sts_pairs} pairs` : ''}
                      </span>
                    )}
                    {r.status === 'error' && r.error && <span className="block truncate text-[11px] text-unmatched">{r.error}</span>}
                  </button>
                </li>
              )
            })}
          </ol>
          <p className="border-t border-rule px-3 py-2 text-[10px] text-ink-3">
            Saved results keep every ship and its reasons; radar image chips are not kept.
          </p>
        </>
      )}
    </aside>
  )
}
