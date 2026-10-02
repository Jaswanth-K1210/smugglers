import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { X, MapPin, Clock, Ship, AlertCircle } from 'lucide-react'
import { formatISO, parseISO, format } from 'date-fns'

export const EventDetail: React.FC = () => {
  const selectedEvent = useDashboardStore((s) => s.selectedEvent)
  const setSelectedEvent = useDashboardStore((s) => s.setSelectedEvent)

  if (!selectedEvent) return null

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'AIS_VISIBLE':
        return <div className="w-3 h-3 rounded-full bg-green-500"></div>
      case 'AIS_PARTIAL':
        return <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
      case 'AIS_UNMATCHED':
        return <div className="w-3 h-3 rounded-full bg-red-500"></div>
      default:
        return null
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'AIS_VISIBLE':
        return 'AIS Visible'
      case 'AIS_PARTIAL':
        return 'Partially Visible'
      case 'AIS_UNMATCHED':
        return 'Dark Candidate'
      default:
        return status
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-end sm:items-center justify-center p-4">
      <div className="glass-effect card-shadow rounded-lg w-full max-w-md max-h-96 overflow-y-auto">
        <div className="p-6 border-b border-slate-700/50 flex items-center justify-between sticky top-0 bg-slate-900/80">
          <h2 className="font-semibold">Event Details</h2>
          <button
            onClick={() => setSelectedEvent(null)}
            className="p-1 hover:bg-slate-700 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-lg">
            {getStatusIcon(selectedEvent.status)}
            <div>
              <p className="text-xs text-slate-400">Status</p>
              <p className="font-semibold">{getStatusLabel(selectedEvent.status)}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 bg-slate-800/50 rounded-lg">
              <p className="text-xs text-slate-400 mb-1 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                Time
              </p>
              <p className="text-sm font-medium">{format(parseISO(selectedEvent.timestamp), 'MMM d, HH:mm')}</p>
            </div>
            <div className="p-3 bg-slate-800/50 rounded-lg">
              <p className="text-xs text-slate-400 mb-1">Confidence</p>
              <p className="text-sm font-medium">{(selectedEvent.confidence * 100).toFixed(1)}%</p>
            </div>
          </div>

          <div className="p-3 bg-slate-800/50 rounded-lg">
            <p className="text-xs text-slate-400 mb-1 flex items-center gap-1">
              <MapPin className="w-3 h-3" />
              Location
            </p>
            <p className="text-sm font-medium">{selectedEvent.lat.toFixed(4)}, {selectedEvent.lon.toFixed(4)}</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 bg-slate-800/50 rounded-lg">
              <p className="text-xs text-slate-400 mb-1">Distance</p>
              <p className="text-sm font-medium">{selectedEvent.distance}m</p>
            </div>
            <div className="p-3 bg-slate-800/50 rounded-lg">
              <p className="text-xs text-slate-400 mb-1">Duration</p>
              <p className="text-sm font-medium">{selectedEvent.duration}h</p>
            </div>
          </div>

          <div className="p-3 bg-slate-800/50 rounded-lg">
            <p className="text-xs text-slate-400 mb-2 flex items-center gap-1">
              <Ship className="w-3 h-3" />
              Vessels
            </p>
            <div className="space-y-1 text-sm">
              <p><span className="text-slate-400">Vessel 1:</span> {selectedEvent.vessel1_mmsi}</p>
              <p><span className="text-slate-400">Vessel 2:</span> {selectedEvent.vessel2_mmsi}</p>
            </div>
          </div>

          <div className="p-3 bg-slate-800/50 rounded-lg">
            <p className="text-xs text-slate-400 mb-1">GFW Match</p>
            <p className={`text-sm font-medium ${selectedEvent.gfw_match ? 'text-green-400' : 'text-slate-400'}`}>
              {selectedEvent.gfw_match ? 'Corroborated' : 'Not matched'}
            </p>
          </div>

          <button className="btn-primary w-full" onClick={() => setSelectedEvent(null)}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
