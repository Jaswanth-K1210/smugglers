import React, { useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { ChevronDown } from 'lucide-react'
import { formatDistanceToNow, parseISO } from 'date-fns'

export const EventTable: React.FC = () => {
  const events = useDashboardStore((s) => s.getFilteredEvents())
  const setSelectedEvent = useDashboardStore((s) => s.setSelectedEvent)
  const [sortBy, setSortBy] = useState<'confidence' | 'date'>('confidence')

  const sortedEvents = [...events].sort((a, b) => {
    if (sortBy === 'confidence') {
      return b.confidence - a.confidence
    }
    return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  }).slice(0, 20)

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'AIS_VISIBLE':
        return 'badge-ais-visible'
      case 'AIS_PARTIAL':
        return 'badge-partial'
      case 'AIS_UNMATCHED':
        return 'badge-dark'
      default:
        return 'badge-ais-visible'
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'AIS_VISIBLE':
        return 'Visible'
      case 'AIS_PARTIAL':
        return 'Partial'
      case 'AIS_UNMATCHED':
        return 'Dark'
      default:
        return status
    }
  }

  return (
    <div className="glass-effect card-shadow rounded-lg overflow-hidden">
      <div className="p-4 border-b border-slate-700/50">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Recent Events</h2>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="input-field text-xs py-1"
          >
            <option value="confidence">Sort by Confidence</option>
            <option value="date">Sort by Date</option>
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50 bg-slate-800/30">
              <th className="px-4 py-3 text-left font-semibold text-slate-300">Time</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-300">Status</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-300">Region</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-300">Distance</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-300">Confidence</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-300">GFW</th>
            </tr>
          </thead>
          <tbody>
            {sortedEvents.map((event) => (
              <tr
                key={event.id}
                onClick={() => setSelectedEvent(event)}
                className="border-b border-slate-700/20 hover:bg-slate-800/30 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3 text-slate-300">
                  {formatDistanceToNow(parseISO(event.timestamp), { addSuffix: true })}
                </td>
                <td className="px-4 py-3">
                  <span className={getStatusColor(event.status)}>
                    {getStatusLabel(event.status)}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-300">{event.region}</td>
                <td className="px-4 py-3 text-slate-300">{event.distance}m</td>
                <td className="px-4 py-3">
                  <span className="inline-block w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                    <span
                      className="h-full bg-gradient-to-r from-ocean-400 to-ocean-600 block"
                      style={{ width: `${event.confidence * 100}%` }}
                    ></span>
                  </span>
                  <span className="ml-2 text-slate-400">{(event.confidence * 100).toFixed(0)}%</span>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    event.gfw_match ? 'bg-green-500/20 text-green-300' : 'bg-slate-700 text-slate-400'
                  }`}>
                    {event.gfw_match ? 'Match' : 'None'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sortedEvents.length === 0 && (
        <div className="p-8 text-center text-slate-400">
          <p>No events found with current filters</p>
        </div>
      )}
    </div>
  )
}
