import React, { useCallback, useEffect, useState } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { apiService, BBox, GfwLayers, isFailedPass, LiveFeed, PastSearch, passesOf, SearchJob, VesselDetail } from '../services/api'
import MapComponent, { MapStyle, SHIP_GROUPS } from './Map'
import { AreaSearch, ScanOverlay, SearchLog, defaultPeriod } from './AreaSearch'
import { SearchBox } from './SearchBox'
import { News } from './News'
import { VesselCard } from './VesselCard'
import { SilentAtSea } from './SilentAtSea'
import { MySearches } from './MySearches'
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
  const [history, setHistory] = useState(false)                         // left drawer: My searches
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
    // a failed refresh keeps the ships already on the map instead of wiping them
    const load = () => apiService.getLive(bounds).then(setFeed).catch(() => {})
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
  // Reopen one of the user's searches: a finished one shows its saved results, a running one resumes polling
  const openPast = async (p: PastSearch) => {
    setHistory(false); setStages([]); setOpenShip(null); setPass(0); setDrawing(false)
    setBox(p.bbox); setFit(p.bbox)
    if (p.period) setPeriod(p.period)
    try {
      setJob(await apiService.getSearch(p.job_id))
    } catch (e) {
      setJob({ job_id: p.job_id, status: 'error', progress: 0, error: e instanceof Error ? e.message : 'Could not reopen this search.' })
    }
  }
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
      <header className="relative z-[1050] flex h-12 shrink-0 items-center gap-4 border-b border-rule bg-surface px-3 sm:px-4">
        <div className="flex shrink-0 items-center gap-3">
          <Wordmark />
          <span className={link?.ok === false ? 'pill border-unmatched/40 bg-unmatched/10 text-unmatched' : 'pill-live'}
            title={link?.ok === false ? `Last sync ${link.at}` : link ? `Synced ${link.at}` : 'Connecting'}>
            <span className={`live-dot mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${link?.ok === false ? 'bg-unmatched' : 'bg-signal'}`} />
            {link?.ok === false ? 'Offline' : 'Live'}
          </span>
        </div>
        <nav aria-label="Sections" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto text-[11px] uppercase tracking-wider">
          {([
            ['Map', () => window.scrollTo({ top: 0, behavior: 'smooth' }), false],
            ['My searches', () => setHistory((h) => !h), history],
            ['AIS stopped at sea', () => scrollTo('silent'), false],
            ['News', () => scrollTo('news'), false],
            ['Run detection', () => scrollTo('detect'), false],
            ['Method', () => { window.location.hash = '#method' }, false],
          ] as const).map(([label, go, on]) => (
            <button key={label} onClick={go} aria-pressed={on}
              className={`shrink-0 px-2 py-1.5 ${on ? 'text-signal' : 'text-ink-2 hover:text-ink'}`}>{label}</button>
          ))}
        </nav>
        <div className="flex shrink-0 items-center gap-2 text-[11px]">
          <span className="hidden lg:block">{aisPill}</span>
          <span className="pill hidden md:block">{clock}</span>
          <button onClick={() => setShowGfw((g) => !g)} aria-pressed={showGfw} title="Global Fishing Watch satellite AIS and radar detections (days delayed)"
            className={showGfw ? 'pill border-signal text-signal' : 'pill text-ink-2 hover:text-ink'}>GFW layers</button>
          <button onClick={switchMap} title="Switch the map theme" className="pill text-ink-2 hover:text-ink">
            {mapStyle === 'light' ? 'Dark map' : 'Light map'}
          </button>
          <span className="hidden max-w-[9rem] truncate pl-1 text-ink-2 md:block">{user?.name}</span>
          <button onClick={() => { logout(); window.location.hash = '#/' }} className="text-ink-3 hover:text-ink">Sign out</button>
        </div>
      </header>

      <section className="relative flex shrink-0 flex-col border-b border-rule md:h-[calc(100vh-48px)] md:max-h-[880px] md:min-h-[540px] md:flex-row">
        {/* left sidebar: live counts, then the area search */}
        <aside className="flex shrink-0 flex-col border-rule bg-surface md:w-[360px] md:border-r" aria-label="Area search">
          <dl className="grid grid-cols-2 border-b border-rule">
            {stats.map(([label, value]) => (
              <div key={label} className="border-rule px-4 py-3 [&:not(:last-child)]:border-r">
                <dd className="text-xl font-bold text-ink">{value}</dd>
                <dt className="mt-0.5 text-[10px] uppercase tracking-wider text-ink-3">{label}</dt>
              </div>
            ))}
          </dl>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <AreaSearch drawing={drawing} onDraw={() => setDrawing(!drawing)} box={box} onClear={clear} onGo={go}
              job={job} openShip={openShip} onShip={setOpenShip} onBox={(b) => { onBox(b); setFit(b) }}
              period={period} onPeriod={setPeriod} periodSearch={periodSearch} pass={pass} onPass={setPass} />
          </div>
        </aside>

        <div className="relative min-w-0 flex-1">
          <div className="h-[60vh] md:h-full">
            <MapComponent live={live} drawing={drawing} box={box} onBox={onBox} scanning={scanning} result={result}
              onBounds={setBounds} focus={focus} fit={fit} onShip={setOpenShip}
              onPickVessel={(m) => { setPickedMmsi(m); setShowTrack(false) }}
              picked={picked?.lat != null ? { lat: picked.lat, lon: picked.lon! } : null}
              track={showTrack ? picked?.track ?? null : null} mapStyle={mapStyle} gfw={showGfw ? gfw : null} />
          </div>

          {showGfw && gfwMsg && (
            <p role="status" className="absolute bottom-3 left-1/2 z-[400] max-w-[60%] -translate-x-1/2 border border-rule bg-paper/90 px-3 py-1.5 text-center text-[11px] text-ink-2">
              {gfwMsg}
            </p>
          )}
          {scanning && <ScanOverlay job={job} />}

          {/* right: Ship search and Filters, each opened by its button; the picked ship's card below */}
          <div className="z-[500] space-y-1 p-1 md:pointer-events-none md:absolute md:bottom-3 md:right-3 md:top-3 md:w-[330px] md:overflow-y-auto md:p-0 [&>*]:pointer-events-auto">
            <div className="flex justify-end gap-1">
              {([['ships', 'Search ship'], ['filters', 'Filters']] as const).map(([id, label]) => (
                <button key={id} onClick={() => setSide(side === id ? null : id)} aria-expanded={side === id}
                  className={side === id ? 'btn-quiet border-signal bg-paper/90 text-signal' : 'btn-quiet bg-paper/90'}>
                  {label}
                </button>
              ))}
            </div>
            {side === 'ships' && <SearchBox live={live} onFocus={(p) => setFocus({ ...p, zoom: 11 })} onPick={(m) => { setPickedMmsi(m); setShowTrack(false) }} />}
            {side === 'filters' && <FilterPanel hidden={hiddenGroups} onToggleGroup={toggleGroup} />}
            {pickedMmsi && (
              <VesselCard mmsi={pickedMmsi} initial={allLive.find((x) => x.mmsi === pickedMmsi)}
                onClose={closeVessel} onLoaded={onVesselLoaded} onSearchHere={searchHere}
                showTrack={showTrack} onToggleTrack={() => setShowTrack((t) => !t)} />
            )}
          </div>
        </div>
      </section>

      <main className="grid flex-1 content-start gap-1 bg-paper p-1 lg:grid-cols-3">
        {(job || stages.length > 0) && (
          <div id="log" className="lg:col-span-3"><SearchLog job={job} stages={stages} /></div>
        )}
        <div id="news"><News className="h-full" /></div>
        <div id="silent">
          <SilentAtSea className="h-full" onShip={(s) => {
            const at = s.on ?? s.off
            setFocus({ lat: at.lat, lon: at.lon, zoom: 9 }); setPickedMmsi(s.mmsi); setShowTrack(false)
            window.scrollTo({ top: 0, behavior: 'smooth' })
          }} />
        </div>
        <div id="detect"><DetectionUpload /></div>
      </main>

      <MySearches open={history} onClose={() => setHistory(false)} onOpen={openPast} />
      <EventDetail />
    </div>
  )
}
