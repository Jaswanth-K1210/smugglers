import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import type { LiveVessel } from '../services/api'
import { STATUS } from '../status'
import { Panel } from './Panel'

export const SearchBox: React.FC<{ live: LiveVessel[]; onFocus: (p: { lat: number; lon: number }) => void }> = ({ live, onFocus }) => {
  const q = useDashboardStore((s) => s.searchQuery)
  const setQ = useDashboardStore((s) => s.setSearchQuery)
  const candidates = useDashboardStore((s) => s.getFilteredEvents())
  const needle = q.trim().toLowerCase()

  const ships = needle
    ? live.filter((v) => v.mmsi.includes(needle) || (v.name || '').toLowerCase().includes(needle)).slice(0, 6)
    : []
  const cands = needle ? candidates.slice(0, 4) : []

  return (
    <Panel title="Search" bodyClassName="p-3">
      <input className="field" placeholder="Ship name, MMSI or region" aria-label="Search ships and candidates"
        value={q} onChange={(e) => setQ(e.target.value)} />
      {needle && (
        <ul className="mt-2 max-h-56 overflow-y-auto text-xs">
          {ships.map((v) => (
            <li key={v.mmsi}>
              <button onClick={() => onFocus(v)} className="flex w-full items-center gap-2 py-1.5 text-left hover:text-signal">
                <span className="h-1.5 w-1.5 rounded-full bg-ink" />
                <span className="flex-1 truncate">{v.name || 'Unnamed'}</span>
                <span className="text-ink-3">{v.mmsi}</span>
              </button>
            </li>
          ))}
          {cands.map((e) => (
            <li key={e.id}>
              <button onClick={() => onFocus(e)} className="flex w-full items-center gap-2 py-1.5 text-left hover:text-signal">
                <span className="h-2 w-2" style={{ background: STATUS[e.status]?.color }} />
                <span className="flex-1 truncate">Candidate {e.id}, {e.region}</span>
                <span className="text-ink-3">{Math.round(e.confidence * 100)}%</span>
              </button>
            </li>
          ))}
          {!ships.length && !cands.length && <li className="py-1.5 text-ink-3">Nothing matches “{q}”.</li>}
        </ul>
      )}
    </Panel>
  )
}
