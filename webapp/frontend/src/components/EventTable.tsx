import React, { useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS } from '../status'
import { Panel } from './Panel'

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
    <Panel
      title="Candidates"
      count={events.length}
      bodyClassName=""
      right={
        <select aria-label="Sort candidates" value={sortBy} onChange={(e) => setSortBy(e.target.value as any)}
          className="border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] uppercase text-ink-2 focus:outline-none">
          <option value="confidence">By confidence</option>
          <option value="date">Newest</option>
        </select>
      }
    >
      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-paper text-[10px] uppercase tracking-wider text-ink-3">
              <tr>
                {['Image time', 'AIS evidence', 'Region', 'Length', 'Confidence', 'GFW'].map((h) => (
                  <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="cursor-pointer border-t border-rule hover:bg-[#1E1E1E]" onClick={() => setSelectedEvent(e)}>
                  <td className="whitespace-nowrap px-3 py-2">
                    <button className="text-left text-ink hover:text-signal" onClick={() => setSelectedEvent(e)}>{formatTime(e.timestamp)}</button>
                  </td>
                  <td className="px-3 py-2"><StatusTag status={e.status} /></td>
                  <td className="whitespace-nowrap px-3 py-2">{e.region}</td>
                  <td className="px-3 py-2">{e.length_estimate} m</td>
                  <td className="px-3 py-2">{Math.round(e.confidence * 100)}%</td>
                  <td className="px-3 py-2 text-ink-2">{e.gfw_match ? 'Encounter' : 'None'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-3 py-8 text-center text-ink-2">
          {useDashboardStore.getState().events.length ? 'No candidates match these filters. Clear filters to see all.' : 'No candidates published yet.'}
        </p>
      )}
    </Panel>
  )
}
