import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { Filter } from 'lucide-react'

export const FilterPanel: React.FC = () => {
  const filter = useDashboardStore((s) => s.filter)
  const setFilter = useDashboardStore((s) => s.setFilter)
  const events = useDashboardStore((s) => s.events)

  const regions = Array.from(new Set(events.map((e) => e.region)))

  return (
    <div className="glass-effect card-shadow rounded-lg p-4 space-y-4">
      <div className="flex items-center gap-2 pb-3 border-b border-slate-700/50">
        <Filter className="w-4 h-4 text-ocean-400" />
        <h3 className="font-semibold">Filters</h3>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Status</label>
        <select
          value={filter.status}
          onChange={(e) => setFilter({ status: e.target.value })}
          className="input-field w-full"
        >
          <option value="all">All Statuses</option>
          <option value="AIS_VISIBLE">AIS Visible</option>
          <option value="AIS_PARTIAL">Partially Visible</option>
          <option value="AIS_UNMATCHED">Dark Candidates</option>
        </select>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Region</label>
        <select
          value={filter.region}
          onChange={(e) => setFilter({ region: e.target.value })}
          className="input-field w-full"
        >
          <option value="all">All Regions</option>
          {regions.map((region) => (
            <option key={region} value={region}>
              {region}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">
          Min. Confidence: {(filter.minConfidence * 100).toFixed(0)}%
        </label>
        <input
          type="range"
          min="0"
          max="100"
          value={filter.minConfidence * 100}
          onChange={(e) => setFilter({ minConfidence: parseInt(e.target.value) / 100 })}
          className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-ocean-600"
        />
      </div>

      <button
        onClick={() => setFilter({
          status: 'all',
          minConfidence: 0.5,
          region: 'all'
        })}
        className="btn-secondary w-full"
      >
        Reset Filters
      </button>
    </div>
  )
}
