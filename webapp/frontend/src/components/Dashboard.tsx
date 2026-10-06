import React, { useCallback, useEffect, useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { apiService, BBox, GfwLayers, isFailedPass, LiveFeed, passesOf, SearchJob, VesselDetail } from '../services/api'
import MapComponent, { MapStyle, SHIP_GROUPS } from './Map'
import { AreaSearch, ScanOverlay, SearchLog, defaultPeriod } from './AreaSearch'
import { SearchBox } from './SearchBox'
import { VesselApiFill } from './VesselApiFill'
import { News } from './News'
import { Menu } from './Menu'
import { VesselCard } from './VesselCard'
import { StraitPanel } from './StraitPanel'
import { FilterPanel } from './Filters'
import { DetectionUpload } from './DetectionUpload'
import { EventDetail } from './EventDetail'
import { Wordmark, useUtcClock } from './Landing'

const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

export const Dashboard: React.FC = () => {
  const events = useDashboardStore((s) => s.events)
  const user = useDashboardStore((s) => s.user)
  const logout = useDashboardStore((s) => s.logout)
  const setEvents = useDashboardStore((s) => s.setEvents)
  const clock = useUtcClock()

  const [link, setLink] = useState<{ ok: boolean; at: string } | null>(null)
  const [bounds, setBounds] = useState<BBox | null>(null)
  const [feed, setFeed] = useState<LiveFeed | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [box, setBox] = useState<BBox | null>(null)
  const [job, setJob] = useState<SearchJob | null>(null)
  const [stages, setStages] = useState<string[]>([])
  const [period, setPeriod] = useState<[string, string]>(defaultPeriod)
  const [pass, setPass] = useState(0)
  const [periodSearch, setPeriodSearch] = useState(false)
  // The Render backend runs time-period searches on the Modal worker; the all-in-one site does not.
  useEffect(() => {
    apiService.getHealth().then((h) => setPeriodSearch(h?.search_mode === 'worker')).catch(() => {})
  }, [])
  const [openShip, setOpenShip] = useState<number | null>(null)
  const [focus, setFocus] = useState<{ lat: number; lon: number; zoom?: number } | null>(null)
  const [fit, setFit] = useState<BBox | null>(null)
  const [pickedMmsi, setPickedMmsi] = useState<string | null>(null)
  const [picked, setPicked] = useState<VesselDetail | null>(null)
  const onVesselLoaded = useCallback((v: VesselDetail) => setPicked(v), [])
  const [showTrack, setShowTrack] = useState(false)
  const [side, setSide] = useState<'filters' | 'ships' | null>(null)   // right-hand panels open on click
  const [mapStyle, setMapStyle] = useState<MapStyle>(() => {
    // dark by default; a user who picked light keeps it
    try { return localStorage.getItem('sts_map_style') === 'light' ? 'light' : 'dark' } catch { return 'dark' }
  })
  const switchMap = () => setMapStyle((m) => {
    const next = m === 'light' ? 'dark' : 'light'
    try { localStorage.setItem('sts_map_style', next) } catch { /* private mode: per-session only */ }
    return next
  })
  const [showGfw, setShowGfw] = useState(false)
  const [gfw, setGfw] = useState<GfwLayers | null>(null)
  const [gfwMsg, setGfwMsg] = useState<string | null>(null)
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

  // GFW layers for the view, on request: days delayed, slow on first load, cached by the server
  useEffect(() => {
    if (!showGfw || !bounds) { setGfw(null); setGfwMsg(null); return }
    if (bounds[2] - bounds[0] > 5 || bounds[3] - bounds[1] > 5) {
      setGfw(null); setGfwMsg('Zoom in to load GFW layers (up to 5° × 5°).'); return
    }
    let live = true
    setGfwMsg('Loading GFW satellite AIS and radar detections… (first load can take ~30 s)')
    const t = setTimeout(() => {
      apiService.getGfwLayers(bounds)
        .then((d) => {
          if (!live) return
          setGfw(d)
          setGfwMsg(d.day ? `GFW ${d.day} (${d.delay_days} days delayed): ${d.vessels.length} AIS vessels, ${d.radar.length} radar detections, ${d.radar.filter((r) => !r.ais_matched).length} without AIS`
            : 'GFW has no AIS for this view in the last week.')
        })
        .catch((e) => live && setGfwMsg(e instanceof Error ? e.message : 'GFW did not answer.'))
    }, 800)
    return () => { live = false; clearTimeout(t) }
  }, [showGfw, bounds])

  // Poll the running area search; the scanner animates until it settles
  useEffect(() => {
    if (!job?.job_id || job.status === 'done' || job.status === 'error') return
    const t = setTimeout(async () => {
      try {
        const next = await apiService.getSearch(job.job_id)
        // period search: the per-pass lines live on the job itself; the running list is for single-pass searches
        if (!next.stages?.length && next.stage) setStages((s) => (s[s.length - 1] === next.stage ? s : [...s, next.stage!]))
        setJob(next)
        if (next.status === 'done') {
          setPass(0)
          const any = passesOf(next.result).some((p) => !isFailedPass(p) && p.ships.length)
          if (any) setFit(next.result?.bbox ?? box)
        }
      } catch (e) {
        setJob({ ...job, status: 'error', error: e instanceof Error ? e.message : 'Lost contact with the search.' })
      }
    }, 1500)
    return () => clearTimeout(t)
  }, [job, box])

  const onBox = useCallback((b: BBox) => { setBox(b); setDrawing(false); setJob(null) }, [])
  const clear = () => { setBox(null); setJob(null); setStages([]); setOpenShip(null); setPass(0); setDrawing(true) }
  const go = async () => {
    if (!box) return
    setStages(['Sending the box'])
    setJob({ job_id: '', status: 'queued', progress: 0, stage: 'Sending the box' })
    try {
      const { job_id, queue_position } = periodSearch
        ? await apiService.startSearch(box, period[0], period[1])
        : await apiService.startSearch(box)
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
  // The map shows one pass at a time: the one picked in the timeline (a single-pass search is pass 0).
  const picked0 = job?.status === 'done' ? passesOf(job.result)[pass] : undefined
  const result = picked0 && !isFailedPass(picked0) ? picked0 : null

  const counts = events.reduce<Record<string, number>>((m, e) => ({ ...m, [e.status]: (m[e.status] || 0) + 1 }), {})
  const allLive = feed?.vessels ?? []
  const hiddenMembers = new Set<string>(SHIP_GROUPS.filter((g) => hiddenGroups.has(g.id)).flatMap((g) => [...g.members]))
  const live = hiddenMembers.size ? allLive.filter((v) => !hiddenMembers.has(v.group ?? 'unknown')) : allLive
  const stats: [string, string | number][] = [
    ['Live AIS ships in view', feed?.configured ? (feed.in_view ?? allLive.length).toLocaleString() : 'off'],
    ['AIS unmatched', counts.AIS_UNMATCHED || 0],
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
            { label: 'Sanctions news', onSelect: () => scrollTo('news') },
            { label: 'Strait of Hormuz crossings', onSelect: () => scrollTo('strait') },
            { label: mapStyle === 'light' ? 'Switch to dark map' : 'Switch to light map', onSelect: switchMap },
            { label: showGfw ? 'Hide GFW layers' : 'Show GFW satellite AIS + radar (delayed)', onSelect: () => setShowGfw((g) => !g) },
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
            track={showTrack ? picked?.track ?? null : null} hidden={hiddenGroups} onToggleGroup={toggleGroup} mapStyle={mapStyle} gfw={showGfw ? gfw : null} />
        </div>

        {showGfw && gfwMsg && (
          <p role="status" className="absolute bottom-3 left-1/2 z-[400] max-w-[60%] -translate-x-1/2 border border-rule bg-paper/90 px-3 py-1.5 text-center text-[11px] text-ink-2">
            {gfwMsg}
          </p>
        )}
        {scanning && <ScanOverlay job={job} />}

        {/* left: stats, then the area search on top */}
        <div className="z-[500] space-y-1 p-1 md:pointer-events-none md:absolute md:bottom-3 md:left-3 md:top-3 md:w-[340px] md:overflow-y-auto md:p-0 [&>*]:pointer-events-auto">
          <dl className="grid grid-cols-2 border border-rule bg-paper/90">
            {stats.map(([label, value]) => (
              <div key={label} className="border-rule px-3 py-2 [&:not(:last-child)]:border-r">
                <dd className="text-xl font-bold text-ink">{value}</dd>
                <dt className="mt-0.5 text-[10px] uppercase tracking-wider text-ink-3">{label}</dt>
              </div>
            ))}
          </dl>
          <AreaSearch drawing={drawing} onDraw={() => setDrawing(!drawing)} box={box} onClear={clear} onGo={go}
            job={job} openShip={openShip} onShip={setOpenShip} onBox={(b) => { onBox(b); setFit(b) }}
            period={period} onPeriod={setPeriod} periodSearch={periodSearch} pass={pass} onPass={setPass} />
          <VesselApiFill bounds={bounds} feed={feed} onFilled={() => bounds && apiService.getLive(bounds).then(setFeed).catch(() => {})} />
        </div>

        {/* right: only Filters and Ship search, each opened by its button; the picked ship's card below */}
        <aside className="z-[500] space-y-1 p-1 md:pointer-events-none md:absolute md:bottom-3 md:right-3 md:top-3 md:w-[330px] md:overflow-y-auto md:p-0 [&>*]:pointer-events-auto">
          <div className="flex justify-end gap-1">
            {([['ships', 'Search ship'], ['filters', 'Filters']] as const).map(([id, label]) => (
              <button key={id} onClick={() => setSide(side === id ? null : id)} aria-expanded={side === id}
                className={side === id ? 'btn-quiet border-signal bg-paper/90 text-signal' : 'btn-quiet bg-paper/90'}>
                {label}
              </button>
            ))}
          </div>
          {side === 'ships' && <SearchBox live={live} onFocus={(p) => setFocus({ ...p, zoom: 11 })} onPick={(m) => { setPickedMmsi(m); setShowTrack(false) }} />}
          {side === 'filters' && <FilterPanel />}
          {pickedMmsi && (
            <VesselCard mmsi={pickedMmsi} onClose={closeVessel} onLoaded={onVesselLoaded} onSearchHere={searchHere}
              showTrack={showTrack} onToggleTrack={() => setShowTrack((t) => !t)} />
          )}
        </aside>
      </section>

      <main className="grid flex-1 content-start gap-1 bg-paper p-1 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
        {(job || stages.length > 0) && (
          <div id="log" className="col-span-full"><SearchLog job={job} stages={stages} /></div>
        )}
        <div id="news" className="col-span-full lg:col-span-2 lg:row-span-2">
          <News className="h-full" />
        </div>
        <div id="strait" className="col-span-full lg:col-span-2 lg:row-span-2">
          <StraitPanel className="h-full" onShip={async (name) => {
            try {
              const hits = await apiService.searchShips(name)
              const hit = hits.find((h) => (h.name ?? '').toUpperCase() === name.toUpperCase()) ?? hits[0]
              if (hit) { setFocus({ lat: hit.lat, lon: hit.lon, zoom: 10 }); setPickedMmsi(hit.mmsi); setShowTrack(false); window.scrollTo({ top: 0, behavior: 'smooth' }) }
            } catch { /* not on the live map right now */ }
          }} />
        </div>
        <div id="detect" className="col-span-full"><DetectionUpload /></div>
      </main>

      <EventDetail />
    </div>
  )
}
