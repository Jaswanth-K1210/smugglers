import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS, STATUS_ORDER } from '../status'
import { Panel } from './Panel'

export const FilterPanel: React.FC = () => {
  const filter = useDashboardStore((s) => s.filter)
  const setFilter = useDashboardStore((s) => s.setFilter)
  const setSearchQuery = useDashboardStore((s) => s.setSearchQuery)
  const events = useDashboardStore((s) => s.events)
  const regions = Array.from(new Set(events.map((e) => e.region)))

  return (
    <Panel title="Filter" bodyClassName="space-y-4 p-3">

      <div>
        <label htmlFor="status" className="label">AIS evidence</label>
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

      <div>
        <label htmlFor="conf" className="label">
          Minimum confidence <span className="font-normal text-ink-2">{Math.round(filter.minConfidence * 100)}%</span>
        </label>
        <input id="conf" type="range" min="0" max="100" className="w-full accent-[#44FF88]"
          value={filter.minConfidence * 100}
          onChange={(e) => setFilter({ minConfidence: parseInt(e.target.value) / 100 })} />
      </div>

      <button className="btn-quiet w-full"
        onClick={() => { setFilter({ status: 'all', minConfidence: 0, region: 'all' }); setSearchQuery('') }}>
        Clear filters
      </button>
    </Panel>
  )
}
