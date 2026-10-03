import React, { useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS } from '../status'

export const StatusTag: React.FC<{ status: keyof typeof STATUS }> = ({ status }) => (
  <span className="inline-flex items-center gap-2 whitespace-nowrap">
    <span className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS[status]?.color }} />
    {STATUS[status]?.label ?? status}
  </span>
)

export const formatTime = (ts: string) => {
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts : d.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC'
}

export const EventTable: React.FC = () => {
  const events = useDashboardStore((s) => s.getFilteredEvents())
  const setSelectedEvent = useDashboardStore((s) => s.setSelectedEvent)
  const [sortBy, setSortBy] = useState<'confidence' | 'date'>('confidence')

  const rows = [...events].sort((a, b) =>
    sortBy === 'confidence'
      ? (b.confidence ?? 0) - (a.confidence ?? 0)
      : (new Date(b.timestamp).getTime() || 0) - (new Date(a.timestamp).getTime() || 0)
  ).slice(0, 50)

  return (
    <section className="panel overflow-hidden">
      <div className="flex items-center justify-between gap-4 border-b border-rule px-5 py-4">
        <h2 className="panel-title">Candidates <span className="font-sans text-sm font-normal text-ink-2">{events.length}</span></h2>
        <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-ink-2">
          Sort by
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)} className="field w-auto py-1">
            <option value="confidence">Confidence</option>
            <option value="date">Newest</option>
          </select>
        </label>
      </div>

      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-paper font-mono text-[11px] uppercase tracking-wider text-ink-2">
              <tr>
                {['Image time', 'AIS evidence', 'Region', 'Length', 'Confidence', 'GFW'].map((h) => (
                  <th key={h} className="whitespace-nowrap px-5 py-2.5 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="cursor-pointer border-t border-rule hover:bg-shoal/60" onClick={() => setSelectedEvent(e)}>
                  <td className="whitespace-nowrap px-5 py-3">
                    <button className="text-left text-signal hover:underline" onClick={() => setSelectedEvent(e)}>{formatTime(e.timestamp)}</button>
                  </td>
                  <td className="px-5 py-3"><StatusTag status={e.status} /></td>
                  <td className="whitespace-nowrap px-5 py-3">{e.region}</td>
                  <td className="px-5 py-3">{e.length_estimate} m</td>
                  <td className="px-5 py-3">{Math.round(e.confidence * 100)}%</td>
                  <td className="px-5 py-3 text-ink-2">{e.gfw_match ? 'Encounter' : 'None'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-5 py-10 text-center text-ink-2">
          {useDashboardStore.getState().events.length ? 'No candidates match these filters. Clear filters to see all.' : 'No candidates published yet.'}
        </p>
      )}
    </section>
  )
}
