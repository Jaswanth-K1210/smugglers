import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { HealthCheck } from './HealthCheck'
import { Download, Share2 } from 'lucide-react'

export const Footer: React.FC = () => {
  const events = useDashboardStore((s) => s.events)

  const handleExportJSON = () => {
    const dataStr = JSON.stringify(events, null, 2)
    const dataBlob = new Blob([dataStr], { type: 'application/json' })
    const url = URL.createObjectURL(dataBlob)
    const link = document.createElement('a')
    link.href = url
    link.download = `sts-events-${new Date().toISOString().split('T')[0]}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleExportCSV = () => {
    const headers = ['ID', 'Time', 'Status', 'Region', 'Latitude', 'Longitude', 'Distance', 'Duration', 'Confidence', 'GFW Match']
    const rows = events.map(e => [
      e.id,
      e.timestamp,
      e.status,
      e.region,
      e.lat,
      e.lon,
      e.distance,
      e.duration,
      (e.confidence * 100).toFixed(1),
      e.gfw_match ? 'Yes' : 'No'
    ])

    const csv = [headers, ...rows].map(row => row.map(cell => `"${cell}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `sts-events-${new Date().toISOString().split('T')[0]}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <footer className="glass-effect card-shadow border-t border-ocean-500/20 mt-12">
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div>
            <h3 className="font-semibold mb-2">System Status</h3>
            <HealthCheck />
          </div>

          <div>
            <h3 className="font-semibold mb-3">Export Data</h3>
            <div className="space-y-2">
              <button
                onClick={handleExportJSON}
                className="btn-secondary w-full flex items-center justify-center gap-2"
              >
                <Download className="w-4 h-4" />
                JSON Export
              </button>
              <button
                onClick={handleExportCSV}
                className="btn-secondary w-full flex items-center justify-center gap-2"
              >
                <Download className="w-4 h-4" />
                CSV Export
              </button>
            </div>
          </div>

          <div>
            <h3 className="font-semibold mb-3">Information</h3>
            <div className="space-y-1 text-sm text-slate-400">
              <p>📊 Total Events: <span className="text-ocean-300">{events.length}</span></p>
              <p>🔄 Last Updated: <span className="text-ocean-300">Just now</span></p>
              <p>🌐 API: <span className="text-ocean-300">/api</span></p>
            </div>
          </div>
        </div>

        <div className="border-t border-slate-700/50 pt-6 flex items-center justify-between text-xs text-slate-500">
          <p>Dark STS Detector © 2026 • Anurag University</p>
          <a href="#" className="hover:text-ocean-400 transition-colors">Documentation</a>
        </div>
      </div>
    </footer>
  )
}
