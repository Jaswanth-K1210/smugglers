import React, { useCallback, useEffect, useState } from 'react'
import { useDashboardStore, STSEvent } from '../store/dashboardStore'
import { apiService, BBox, LiveFeed, SearchJob, VesselDetail } from '../services/api'
import MapComponent, { SHIP_GROUPS } from './Map'
import { AreaSearch } from './AreaSearch'
import { SearchBox } from './SearchBox'
import { News } from './News'
import { Menu } from './Menu'
import { VesselCard } from './VesselCard'
import { EventTable } from './EventTable'
import { ConfidenceChart, TimeSeriesChart } from './Charts'
import { FilterPanel } from './Filters'
import { DetectionUpload } from './DetectionUpload'
import { EventDetail } from './EventDetail'
import { CategoryBar, Wordmark, useUtcClock } from './Landing'
import { Panel } from './Panel'

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

const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

export const Dashboard: React.FC = () => {
  const events = useDashboardStore((s) => s.events)
  const user = useDashboardStore((s) => s.user)
  const logout = useDashboardStore((s) => s.logout)
  const setEvents = useDashboardStore((s) => s.setEvents)
  const filtered = useDashboardStore((s) => s.getFilteredEvents())
  const clock = useUtcClock()

  const [link, setLink] = useState<{ ok: boolean; at: string } | null>(null)
  const [bounds, setBounds] = useState<BBox | null>(null)
  const [feed, setFeed] = useState<LiveFeed | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [box, setBox] = useState<BBox | null>(null)
  const [job, setJob] = useState<SearchJob | null>(null)
  const [stages, setStages] = useState<string[]>([])
  const [openShip, setOpenShip] = useState<number | null>(null)
  const [focus, setFocus] = useState<{ lat: number; lon: number; zoom?: number } | null>(null)
  const [fit, setFit] = useState<BBox | null>(null)
  const [pickedMmsi, setPickedMmsi] = useState<string | null>(null)
  const [picked, setPicked] = useState<VesselDetail | null>(null)
  const onVesselLoaded = useCallback((v: VesselDetail) => setPicked(v), [])
  const [showTrack, setShowTrack] = useState(false)
  const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set())
  const toggleGroup = (id: string) => setHiddenGroups((h) => { const n = new Set(h); n.has(id) ? n.delete(id) : n.add(id); return n })
  const closeVessel = useCallback(() => { setPickedMmsi(null); setPicked(null); setShowTrack(false) }, [])

  // Published candidates
  useEffect(() => {
    const load = () => apiService.getEvents()
      .then((data) => { setEvents(data); setLink({ ok: true, at: new Date().toISOString().slice(11, 19) + 'Z' }) })
      .catch((e) => { console.error('Failed to load events:', e); setLink((l) => ({ ok: false, at: l?.at ?? 'never' })) })
    load()
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [setEvents])

  // Live AIS for whatever the map is showing; refetch on pan and every 15 s
  useEffect(() => {
    if (!bounds) return
    const load = () => apiService.getLive(bounds).then(setFeed).catch(() => setFeed(null))
    load()
    const interval = setInterval(load, 15000)
    return () => clearInterval(interval)
  }, [bounds])

  // Poll the running area search; the scanner animates until it settles
  useEffect(() => {
    if (!job?.job_id || job.status === 'done' || job.status === 'error') return
    const t = setTimeout(async () => {
      try {
        const next = await apiService.getSearch(job.job_id)
        if (next.stage) setStages((s) => (s[s.length - 1] === next.stage ? s : [...s, next.stage!]))
        setJob(next)
        if (next.status === 'done' && next.result?.ships.length) setFit(next.result.bbox ?? box)
      } catch (e) {
        setJob({ ...job, status: 'error', error: e instanceof Error ? e.message : 'Lost contact with the search.' })
      }
    }, 1500)
    return () => clearTimeout(t)
  }, [job, box])

  const onBox = useCallback((b: BBox) => { setBox(b); setDrawing(false); setJob(null) }, [])
  const clear = () => { setBox(null); setJob(null); setStages([]); setOpenShip(null); setDrawing(true) }
  const go = async () => {
    if (!box) return
    setStages(['Sending the box'])
    setJob({ job_id: '', status: 'queued', progress: 0, stage: 'Sending the box' })
    try {
      const { job_id, queue_position } = await apiService.startSearch(box)
      setJob({ job_id, status: 'queued', progress: 0, queue_position, stage: 'Starting' })
    } catch (e) {
      setJob({ job_id: '', status: 'error', progress: 0, error: e instanceof Error ? e.message : 'The search could not start.' })
    }
  }
  // ~20 km box around a ship, ready for Go (the search's minimum is 11 km)
  const searchHere = (lat: number, lon: number) => {
    const dLat = 10 / 110.57, dLon = 10 / (111.32 * Math.cos(lat * Math.PI / 180))
    const b: BBox = [lon - dLon, lat - dLat, lon + dLon, lat + dLat]
    setStages([]); setOpenShip(null); setJob(null); setDrawing(false); setBox(b); setFit(b)
  }
  const scanning = job?.status === 'queued' || job?.status === 'running'
  const result = job?.status === 'done' ? job.result ?? null : null

  const counts = events.reduce<Record<string, number>>((m, e) => ({ ...m, [e.status]: (m[e.status] || 0) + 1 }), {})
  const meanConf = events.length ? events.reduce((s, e) => s + (e.confidence || 0), 0) / events.length : 0
  const allLive = feed?.vessels ?? []
  const hiddenMembers = new Set<string>(SHIP_GROUPS.filter((g) => hiddenGroups.has(g.id)).flatMap((g) => [...g.members]))
  const live = hiddenMembers.size ? allLive.filter((v) => !hiddenMembers.has(v.group ?? 'unknown')) : allLive
  const stats: [string, string | number][] = [
    ['Live AIS ships in view', feed?.configured ? (feed.in_view ?? allLive.length).toLocaleString() : 'off'],
    ['Candidates', events.length],
    ['AIS unmatched', counts.AIS_UNMATCHED || 0],
    ['Mean confidence', `${Math.round(meanConf * 100)}%`],
  ]

  const aisPill = !feed ? null
    : !feed.configured ? <span className="pill text-ink-3" title="Set AISSTREAM_API_KEY on the server to show live ships">AIS feed off</span>
    : feed.connected ? <span className="pill-live" title={feed.in_view > allLive.length ? `Showing ${allLive.length.toLocaleString()} spread evenly across the view; zoom in to see every ship` : ''}>AIS {(feed.in_view ?? allLive.length).toLocaleString()} in view{feed.in_view > allLive.length ? `, ${allLive.length.toLocaleString()} drawn` : ''}</span>
    : <span className="pill border-partial/40 text-partial" title={feed.error ?? ''}>AIS reconnecting</span>

  return (
    <div className="flex min-h-screen flex-col">
      <header className="relative z-[1050] flex h-10 shrink-0 items-center justify-between gap-3 border-b border-rule bg-surface px-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-3">
          <Menu items={[
            { label: 'Overview', onSelect: () => { window.location.hash = '#/' } },
            { label: 'Draw a search area', onSelect: () => { clear(); window.scrollTo({ top: 0, behavior: 'smooth' }) } },
            { label: 'Run detection on a tile', onSelect: () => scrollTo('detect') },
            { label: 'Candidates table', onSelect: () => scrollTo('candidates') },
            { label: 'Sanctions news', onSelect: () => scrollTo('news') },
            'divider',
            { label: 'Export candidates as CSV', disabled: !filtered.length, onSelect: () => download(toCSV(filtered), 'text/csv', 'csv') },
            { label: 'Export candidates as JSON', disabled: !filtered.length, onSelect: () => download(JSON.stringify(filtered, null, 2), 'application/json', 'json') },
            'divider',
            { label: 'How candidates are made', onSelect: () => { window.location.hash = '#method' } },
            { label: 'Sign out', onSelect: () => { logout(); window.location.hash = '#/' } },
          ]} />
          <Wordmark />
          <span className={link?.ok === false ? 'pill border-unmatched/40 bg-unmatched/10 text-unmatched' : 'pill-live'}>
            <span className={`live-dot mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${link?.ok === false ? 'bg-unmatched' : 'bg-signal'}`} />
            {link?.ok === false ? 'Offline' : 'Live'}
          </span>
          <span className="hidden sm:block">{aisPill}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden text-[11px] text-ink-3 lg:block">
            {link?.ok === false ? `last sync ${link.at}` : link ? `sync ${link.at}` : 'connecting'}
          </span>
          <span className="pill hidden md:block">{clock}</span>
          <span className="hidden max-w-[10rem] truncate pl-1 text-[11px] text-ink-2 md:block">{user?.name}</span>
        </div>
      </header>

      <section className="relative shrink-0 border-b border-rule md:h-[calc(100vh-40px)] md:max-h-[860px] md:min-h-[520px]">
        <div className="h-[60vh] md:h-full">
          <MapComponent live={live} drawing={drawing} box={box} onBox={onBox} scanning={scanning} result={result}
            onBounds={setBounds} focus={focus} fit={fit} onShip={setOpenShip}
            onPickVessel={(m) => { setPickedMmsi(m); setShowTrack(false) }}
            picked={picked?.lat != null ? { lat: picked.lat, lon: picked.lon! } : null}
            track={showTrack ? picked?.track ?? null : null} hidden={hiddenGroups} onToggleGroup={toggleGroup} />
        </div>

        <dl className="pointer-events-none absolute left-3 top-3 z-[400] grid grid-cols-2 border border-rule bg-paper/90 sm:grid-cols-4">
          {stats.map(([label, value]) => (
            <div key={label} className="border-rule px-3 py-2 [&:not(:last-child)]:border-r">
              <dd className="text-xl font-bold text-ink">{value}</dd>
              <dt className="mt-0.5 text-[10px] uppercase tracking-wider text-ink-3">{label}</dt>
            </div>
          ))}
        </dl>

        {pickedMmsi && (
          <div className="z-[600] p-1 md:absolute md:bottom-3 md:left-3 md:top-[92px] md:w-[320px] md:overflow-y-auto md:p-0">
            <VesselCard mmsi={pickedMmsi} onClose={closeVessel} onLoaded={onVesselLoaded} onSearchHere={searchHere}
              showTrack={showTrack} onToggleTrack={() => setShowTrack((t) => !t)} />
          </div>
        )}

        <aside className="z-[500] space-y-1 p-1 md:pointer-events-none md:absolute md:bottom-3 md:right-3 md:top-3 md:w-[330px] md:overflow-y-auto md:p-0 [&>*]:pointer-events-auto">
          <SearchBox live={live} onFocus={(p) => setFocus({ ...p, zoom: 11 })} />
          <AreaSearch drawing={drawing} onDraw={() => setDrawing(!drawing)} box={box} onClear={clear} onGo={go}
            job={job} stages={stages} openShip={openShip} onShip={setOpenShip} />
          <FilterPanel />
        </aside>
      </section>

      <main className="grid flex-1 content-start gap-1 bg-paper p-1 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
        <div id="news" className="col-span-full lg:col-span-2 lg:row-span-2">
          <News className="h-full" />
        </div>
        <Panel title="AIS evidence" count={events.length}>
          {events.length ? <CategoryBar counts={counts} /> : <p className="text-xs text-ink-2">No candidates loaded.</p>}
        </Panel>
        <ConfidenceChart />
        <TimeSeriesChart />
        <div id="detect"><DetectionUpload /></div>
        <div id="candidates" className="col-span-full">
          <EventTable />
        </div>
      </main>

      <EventDetail />
    </div>
  )
}
