import React, { useEffect } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS } from '../status'
import { StatusTag, formatTime } from './EventTable'

export const EventDetail: React.FC = () => {
  const e = useDashboardStore((s) => s.selectedEvent)
  const close = () => useDashboardStore.getState().setSelectedEvent(null)

  useEffect(() => {
    const onKey = (k: KeyboardEvent) => k.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!e) return null

  const rows: [string, React.ReactNode][] = [
    ['Image time', formatTime(e.timestamp)],
    ['Position', `${e.lat.toFixed(4)}, ${e.lon.toFixed(4)}`],
    ['Region', e.region],
    ['Estimated length', `${e.length_estimate} m`],
    ['Confidence', `${(e.confidence * 100).toFixed(1)}%`],
    ['Vessel 1 MMSI', e.vessel1_mmsi],
    ['Vessel 2 MMSI', e.vessel2_mmsi],
    ['Global Fishing Watch', e.gfw_match ? 'Encounter event on record' : 'No encounter on record'],
  ]

  return (
    <div className="fixed inset-0 z-[1000] flex justify-end bg-black/70" onClick={close}>
      <aside role="dialog" aria-modal="true" aria-labelledby="detail-title"
        className="h-full w-full max-w-md overflow-y-auto bg-surface shadow-xl" onClick={(ev) => ev.stopPropagation()}>
        <div className="flex items-start justify-between border-b border-rule px-6 py-5">
          <div>
            <h2 id="detail-title" className="font-mono text-2xl font-semibold">Candidate {e.id}</h2>
            <p className="mt-1 text-sm"><StatusTag status={e.status} /></p>
          </div>
          <button onClick={close} autoFocus className="btn-quiet px-3 py-1.5">Close</button>
        </div>
        <p className="border-b border-rule bg-paper px-6 py-4 text-sm leading-relaxed text-ink-2">{STATUS[e.status]?.meaning}</p>
        <dl className="divide-y divide-rule px-6">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[10rem_1fr] gap-4 py-3 text-sm">
              <dt className="text-ink-2">{k}</dt>
              <dd className="break-words text-ink">{v}</dd>
            </div>
          ))}
        </dl>
      </aside>
    </div>
  )
}
