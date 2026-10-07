import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS, STATUS_ORDER } from '../status'
import { SHIP_GROUPS } from './Map'
import { Panel } from './Panel'

export const FilterPanel: React.FC<{ hidden: Set<string>; onToggleGroup: (id: string) => void }> = ({ hidden, onToggleGroup }) => {
  const filter = useDashboardStore((s) => s.filter)
  const setFilter = useDashboardStore((s) => s.setFilter)
  const setSearchQuery = useDashboardStore((s) => s.setSearchQuery)
  const events = useDashboardStore((s) => s.events)
  const regions = Array.from(new Set(events.map((e) => e.region)))

  return (
    <Panel title="Filters" bodyClassName="space-y-4 p-3">
      <fieldset>
        <legend className="label">Live ships on the map</legend>
        <div className="grid grid-cols-2 gap-1">
          {SHIP_GROUPS.map((g) => (
            <button key={g.id} onClick={() => onToggleGroup(g.id)} aria-pressed={!hidden.has(g.id)}
              className={`flex items-center gap-2 border px-2 py-1 text-left text-[11px] ${hidden.has(g.id) ? 'border-rule text-ink-3 line-through' : 'border-rule text-ink-2 hover:text-ink'}`}>
              <svg width="10" height="10" viewBox="-6 -8 12 14" aria-hidden="true">
                <path d="M0 -7 L4.2 5 L0 2.6 L-4.2 5 Z" fill={hidden.has(g.id) ? 'transparent' : g.fill} stroke={g.stroke} strokeWidth="1.2" />
              </svg>
              {g.label}
            </button>
          ))}
        </div>
      </fieldset>

      <div>
        <label htmlFor="status" className="label">Published candidates: AIS evidence</label>
        <select id="status" className="field" value={filter.status} onChange={(e) => setFilter({ status: e.target.value })}>
          <option value="all">All categories</option>
          {STATUS_ORDER.map((k) => <option key={k} value={k}>{STATUS[k].label}</option>)}
        </select>
      </div>

      <div>
        <label htmlFor="region" className="label">Region</label>
        <select id="region" className="field" value={filter.region} onChange={(e) => setFilter({ region: e.target.value })}>
          <option value="all">All regions</option>
          {regions.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>

      <button className="btn-quiet w-full"
        onClick={() => { setFilter({ status: 'all', minConfidence: 0, region: 'all' }); setSearchQuery('') }}>
        Clear filters
      </button>
    </Panel>
  )
}
