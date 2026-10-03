import React, { useEffect, useState } from 'react'
import { useDashboardStore, STSEvent } from '../store/dashboardStore'
import { apiService } from '../services/api'
import MapComponent from './Map'
import { EventTable } from './EventTable'
import { ConfidenceChart, TimeSeriesChart } from './Charts'
import { FilterPanel } from './Filters'
import { DetectionUpload } from './DetectionUpload'
import { EventDetail } from './EventDetail'
import { CategoryBar, Wordmark, useUtcClock } from './Landing'

const download = (text: string, type: string, ext: string) => {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = `sts-candidates-${new Date().toISOString().slice(0, 10)}.${ext}`
  a.click()
  URL.revokeObjectURL(url)
}

const toCSV = (events: STSEvent[]) => {
  const cols: (keyof STSEvent)[] = ['id', 'timestamp', 'status', 'region', 'lat', 'lon', 'distance', 'duration', 'confidence', 'gfw_match', 'vessel1_mmsi', 'vessel2_mmsi']
  return [cols.join(','), ...events.map((e) => cols.map((c) => `"${String(e[c]).replace(/"/g, '""')}"`).join(','))].join('\n')
}

export const Dashboard: React.FC = () => {
  const events = useDashboardStore((s) => s.events)
  const user = useDashboardStore((s) => s.user)
  const logout = useDashboardStore((s) => s.logout)
  const setEvents = useDashboardStore((s) => s.setEvents)
  const filtered = useDashboardStore((s) => s.getFilteredEvents())

  const clock = useUtcClock()
  const [link, setLink] = useState<{ ok: boolean; at: string } | null>(null)

  useEffect(() => {
    const load = () => apiService.getEvents()
      .then((data) => { setEvents(data); setLink({ ok: true, at: new Date().toISOString().slice(11, 19) + 'Z' }) })
      .catch((e) => { console.error('Failed to load events:', e); setLink((l) => ({ ok: false, at: l?.at ?? 'never' })) })
    load()
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [setEvents])

  const counts = events.reduce<Record<string, number>>((m, e) => ({ ...m, [e.status]: (m[e.status] || 0) + 1 }), {})
  const meanConf = events.length ? events.reduce((s, e) => s + (e.confidence || 0), 0) / events.length : 0
  const stats: [string, string | number][] = [
    ['Candidates', events.length],
    ['AIS unmatched', counts.AIS_UNMATCHED || 0],
    ['GFW corroborated', events.filter((e) => e.gfw_match).length],
    ['Mean confidence', `${Math.round(meanConf * 100)}%`],
  ]

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-paper/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between gap-4 px-4 sm:px-6">
          <div className="flex items-center gap-4">
            <Wordmark />
            <span className="hidden border-l border-rule pl-4 font-mono text-xs uppercase tracking-wider text-signal sm:block">Ops console</span>
          </div>
          <div className="flex items-center gap-5 font-mono text-xs uppercase tracking-wider">
            <span className="hidden items-center gap-2 text-ink-2 md:flex">
              <span className={`live-dot h-1.5 w-1.5 rounded-full ${link?.ok === false ? 'bg-unmatched' : 'bg-signal'}`} />
              {link?.ok === false ? `Feed lost, last sync ${link.at}` : `Feed live${link ? `, sync ${link.at}` : ''}`}
            </span>
            <span className="hidden text-ink lg:block">{clock}</span>
            <span className="hidden border-l border-rule pl-5 normal-case tracking-normal text-ink-2 sm:block">{user?.name}</span>
            <button
              onClick={() => { logout(); window.location.hash = '#/' }}
              className="uppercase text-ink hover:text-signal"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] space-y-6 px-4 py-6 sm:px-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <dl className="flex flex-wrap gap-x-10 gap-y-3">
            {stats.map(([label, value]) => (
              <div key={label}>
                <dt className="font-mono text-[11px] uppercase tracking-wider text-ink-2">{label}</dt>
                <dd className="font-mono text-3xl font-bold text-ink">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="flex gap-2">
            <button className="btn-quiet" disabled={!filtered.length}
              onClick={() => download(toCSV(filtered), 'text/csv', 'csv')}>Export CSV</button>
            <button className="btn-quiet" disabled={!filtered.length}
              onClick={() => download(JSON.stringify(filtered, null, 2), 'application/json', 'json')}>Export JSON</button>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
          <aside className="space-y-6">
            <FilterPanel />
            <DetectionUpload />
          </aside>

          <div className="min-w-0 space-y-6">
            <MapComponent />
            <div className="grid items-start gap-6 xl:grid-cols-3">
              <section className="panel p-5">
                <h2 className="panel-title mb-4">AIS evidence</h2>
                {events.length ? <CategoryBar counts={counts} /> : <p className="text-sm text-ink-2">No candidates loaded.</p>}
              </section>
              <ConfidenceChart />
              <TimeSeriesChart />
            </div>
            <EventTable />
          </div>
        </div>
      </main>

      <EventDetail />
    </div>
  )
}
