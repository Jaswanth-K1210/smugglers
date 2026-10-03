import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS, STATUS_ORDER } from '../status'

export const FilterPanel: React.FC = () => {
  const filter = useDashboardStore((s) => s.filter)
  const setFilter = useDashboardStore((s) => s.setFilter)
  const searchQuery = useDashboardStore((s) => s.searchQuery)
  const setSearchQuery = useDashboardStore((s) => s.setSearchQuery)
  const events = useDashboardStore((s) => s.events)
  const regions = Array.from(new Set(events.map((e) => e.region)))

  return (
    <section className="panel space-y-5 p-5">
      <h2 className="panel-title">Filter</h2>

      <div>
        <label htmlFor="q" className="label">Search</label>
        <input id="q" className="field" placeholder="MMSI, region or ID"
          value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
      </div>

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
        <input id="conf" type="range" min="0" max="100" className="w-full accent-[#3BF08A]"
          value={filter.minConfidence * 100}
          onChange={(e) => setFilter({ minConfidence: parseInt(e.target.value) / 100 })} />
      </div>

      <button className="btn-quiet w-full"
        onClick={() => { setFilter({ status: 'all', minConfidence: 0, region: 'all' }); setSearchQuery('') }}>
        Clear filters
      </button>
    </section>
  )
}
