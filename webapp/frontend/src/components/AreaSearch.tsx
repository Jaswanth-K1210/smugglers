import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { apiService, isFailedPass, passesOf } from '../services/api'
import type { AisSilentShip, BBox, SearchEstimate, SearchJob, SearchResult, SearchShip } from '../services/api'
import { STATUS } from '../status'
import { Panel } from './Panel'

// Mirrors src/limits.py: one 1024 px tile at minimum; the maximum is for one-pass (local) searches only,
// period searches cut any box into 50 km cells (src/plan.py).
const MIN_KM = 11
const MAX_KM = 60
/** A `km` × `km` box around the centre of `b`: the fix offered for a box drawn too large. */
export const shrinkBox = (b: BBox, km = 50): BBox => {
  const lat = (b[1] + b[3]) / 2, lon = (b[0] + b[2]) / 2
  const dLat = km / 2 / 110.57, dLon = km / 2 / (111.32 * Math.cos(lat * Math.PI / 180))
  return [lon - dLon, lat - dLat, lon + dLon, lat + dLat]
}

export const boxKm = (b: BBox) => [
  (b[2] - b[0]) * 111.32 * Math.cos(((b[1] + b[3]) / 2) * Math.PI / 180),
  (b[3] - b[1]) * 110.57,
]

// Mirrors src/limits.py: time-period search (any length; the estimate shows what it will take).
export const DEFAULT_DAYS = 12
const ARCHIVE_START = '2014-10-03'
const isoDay = (d: Date) => d.toISOString().slice(0, 10)
export const defaultPeriod = (): [string, string] => {
  const end = new Date()
  return [isoDay(new Date(end.getTime() - (DEFAULT_DAYS - 1) * 86400000)), isoDay(end)]
}
export const periodError = ([start, end]: [string, string]): string | null => {
  if (!start || !end) return 'Pick a start and an end date.'
  if (end < start) return 'The end date is before the start date.'
  if (end > isoDay(new Date())) return 'The end date is in the future.'
  return start < ARCHIVE_START ? 'Sentinel-1 images start on 3 Oct 2014.' : null
}

const EstimateLine: React.FC<{ est: { data?: SearchEstimate; error?: string; loading?: boolean } }> = ({ est }) => {
  if (est.loading) return <p className="text-[11px] text-ink-3">Counting satellite passes…</p>
  if (est.error) return <p className="text-xs text-partial">{est.error}</p>
  const e = est.data
  if (!e) return null
  if (e.over_limit) return (     // counting stops at the ceiling, so the numbers would be partial
    <div className="space-y-1 border border-rule px-2 py-1.5 text-[11px] leading-snug">
      <p className="text-ink">More than {e.max_units} pieces of work{e.cells > 1 ? ` (${e.cells} areas of up to 50 km)` : ''}.</p>
      <p className="text-partial">That is over the limit for one search: pick a shorter period or a smaller area.</p>
    </div>
  )
  return (
    <div className="space-y-1 border border-rule px-2 py-1.5 text-[11px] leading-snug">
      <p className="text-ink">
        {e.passes} pass{e.passes === 1 ? '' : 'es'} ({day(e.first).slice(0, 11)} to {day(e.last).slice(0, 11)})
        {e.cells > 1 ? ` over ${e.cells} areas of up to 50 km` : ''}: {e.units} piece{e.units === 1 ? '' : 's'} of work.
      </p>
      <p className="text-ink-2">About {e.minutes < 2 ? '2 minutes' : e.minutes < 90 ? `${e.minutes} minutes` : `${(e.minutes / 60).toFixed(1)} hours`},
        ≈ ${e.usd.toFixed(2)} of free cloud credit.</p>
      {e.over_daily && <p className="text-partial">You have {e.daily_units_left} pieces left today: pick a shorter period or a smaller area.</p>}
    </div>
  )
}

const day = (t: string) => new Date(t).toUTCString().slice(5, 22)

const CATEGORY: Record<string, { label: string; color: string }> = {
  ...STATUS,
  AIS_NOT_AVAILABLE: { label: 'AIS not available', color: '#838383' },
}

/** Loading over the map while a search runs: see-through, so the map stays visible and usable. */
export const ScanOverlay: React.FC<{ job: SearchJob | null }> = ({ job }) => (
  <div className="pointer-events-none absolute inset-0 z-[450] flex items-center justify-center bg-paper/25" role="status" aria-live="polite">
    <div className="flex flex-col items-center gap-3 px-6 py-4 text-center">
      <div className="radar h-20 w-20 rounded-full border border-signal/50" aria-hidden="true" />
      <p className="text-[11px] uppercase tracking-wider text-signal drop-shadow">
        {job?.status === 'queued' && job.queue_position ? `Queued, ${job.queue_position} ahead` : 'Scanning'} · {Math.round((job?.progress ?? 0) * 100)}%
      </p>
      <p className="max-w-xs text-xs text-ink drop-shadow">{job?.stage || 'Sending the box'}</p>
      <div className="h-1 w-56 bg-rule/60">
        <div className="h-full bg-signal transition-[width] duration-500" style={{ width: `${Math.max(4, (job?.progress ?? 0) * 100)}%` }} />
      </div>
    </div>
  </div>
)

/** The search log, shown below the map: one line per pass (period search) or per step. */
export const SearchLog: React.FC<{ job: SearchJob | null; stages: string[] }> = ({ job, stages }) => (
  <Panel title="Search log" right={job && <span className="text-[10px] uppercase text-ink-3">{job.status}</span>} bodyClassName="p-3">
    {job?.stages?.length ? (
      // period search: one line per pass with its own state (index keys: many lines read "waiting")
      <ol className="max-h-64 space-y-0.5 overflow-y-auto font-mono text-[11px] text-ink-3" aria-label="Passes">
        {job.stages.map((s, i) => {
          const state = / failed/.test(s) ? 'failed' : /: (done|Done)$/.test(s) || /(\d+) of \1 areas done$/.test(s) ? 'done'
            : s === 'waiting' || /: waiting$/.test(s) ? 'waiting' : 'running'
          const mark = { failed: '✗', done: '✓', waiting: '·', running: '>' }[state]
          const tone = { failed: 'text-unmatched', done: 'text-ink-3', waiting: 'text-ink-3', running: 'text-signal' }[state]
          return (
            <li key={i} className={state === 'running' ? 'text-ink-2' : ''}>
              <span className={tone}>{mark}</span> {s === 'waiting' ? `Pass ${i + 1}: waiting for a free worker` : s}
            </li>
          )
        })}
      </ol>
    ) : (
      <ol className="max-h-64 space-y-0.5 overflow-y-auto font-mono text-[11px] text-ink-3">
        {stages.map((s, i) => (
          <li key={i} className={i === stages.length - 1 ? 'text-ink-2' : ''}>
            <span className={i === stages.length - 1 ? 'text-signal' : 'text-ink-3'}>{i === stages.length - 1 ? '>' : '✓'}</span> {s}
          </li>
        ))}
      </ol>
    )}
    {job?.status === 'error' && <p role="alert" className="mt-2 text-xs text-unmatched">{job.error}</p>}
  </Panel>
)

/** Ships whose AIS was silent across this pass and that could have been in the area. */
const SilentAis: React.FC<{ ships: AisSilentShip[]; passTime: string; onShip: (id: number) => void }> = ({ ships, passTime, onShip }) => {
  const linked = ships.filter((r) => r.could_be.length).length
  const recent = Date.now() - Date.parse(passTime) < 5 * 86400000
  return (
    <details className="border border-rule px-2 py-1.5 text-[11px]" open={linked > 0}>
      <summary className="cursor-pointer text-ink-2">
        AIS silent at this pass: <span className="text-[#B98CFF]">{ships.length} ship{ships.length === 1 ? '' : 's'}</span>
        {linked ? `, ${linked} could be a ship found here` : ''}
      </summary>
      <p className="mt-1 text-ink-3">
        Reported AIS before the pass, went silent across it and reported again after, and could have been in this
        area at the pass time (at up to 15 kn). On the map: hollow circle where AIS stopped, filled circle where it
        came back. AIS also drops out through poor reception, so each one is a lead, not proof.
        {recent && ' This pass is recent: AIS after it may not be published yet (Global Fishing Watch runs 3–5 days behind).'}
      </p>
      {ships.length ? (
        <ul className="mt-1 max-h-56 space-y-1.5 overflow-y-auto">
          {[...ships].sort((a, b) => b.could_be.length - a.could_be.length || a.silent_h - b.silent_h).map((r) => (
            <li key={r.key} className="border-t border-rule pt-1.5 first:border-t-0 first:pt-0">
              <p className="text-ink">
                {r.mmsi ? (
                  <a className="hover:underline" target="_blank" rel="noreferrer"
                    href={`https://www.marinetraffic.com/en/ais/details/ships/mmsi:${r.mmsi}`}>{r.name ?? `MMSI ${r.mmsi}`} ↗</a>
                ) : (r.name ?? 'Unnamed ship')}
                <span className="text-ink-3"> {[r.flag, r.type, r.imo && `IMO ${r.imo}`, r.mmsi && `MMSI ${r.mmsi}`].filter(Boolean).join(' · ')}</span>
              </p>
              <p className="text-ink-2">
                Off {r.off.hours_before} h before ({r.off.lat.toFixed(3)}, {r.off.lon.toFixed(3)}) · on {r.on.hours_after} h after
                ({r.on.lat.toFixed(3)}, {r.on.lon.toFixed(3)}) · silent {r.silent_h} h
              </p>
              {r.could_be.length > 0 && (
                <p className="text-ink-2">Could be{' '}
                  {r.could_be.map((id) => (
                    <button key={id} onClick={() => onShip(id)} className="mr-1 text-[#B98CFF] underline">ship {id + 1}</button>
                  ))}
                </p>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-ink-3">No ship went silent across this pass near this area.</p>
      )}
    </details>
  )
}

const ShipRow: React.FC<{ ship: SearchShip; open: boolean; onToggle: () => void }> = ({ ship, open, onToggle }) => {
  const cat = CATEGORY[ship.category] ?? { label: ship.category, color: '#E8E8E8' }
  return (
    <li className="border-t border-rule first:border-t-0">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-2 py-2 text-left hover:bg-white/[0.03]">
        <span className="h-2 w-2 shrink-0" style={{ background: cat.color }} />
        <span className="flex-1 text-xs text-ink">Ship {ship.id + 1}</span>
        {!!ship.recurring_passes && (
          <span className="text-[10px] text-partial" title="AIS-unmatched at this spot on several passes: likely a fixed structure or a ship at anchor">
            seen on {ship.recurring_passes} passes
          </span>
        )}
        <span className="text-[11px] text-ink-2">≈{ship.length_m} m</span>
        <span className="w-28 truncate text-right text-[11px] text-ink-3">{cat.label}</span>
      </button>
      {open && (
        <div className="flex gap-3 pb-3">
          {ship.chip_png && (
            <img src={`data:image/png;base64,${ship.chip_png}`} alt={`Radar chip around ship ${ship.id + 1}`}
              className="h-20 w-20 shrink-0 border border-rule [image-rendering:pixelated]" />
          )}
          <ul className="space-y-1 text-[11px] leading-snug text-ink-2">
            {ship.reasons.map((r) => <li key={r}>{r}</li>)}
            {!!ship.ais_candidates?.length && (
              <li className="pt-1 text-ink-3">
                Nearest AIS:{' '}
                {ship.ais_candidates.map((c) => (
                  <span key={c.id} className={`mr-2 inline-block ${c.plausible ? 'text-ink-2' : 'line-through'}`}
                    title={`${c.source}: ${c.minutes_from_pass} min from pass, would need ${c.speed_needed_kn} kn`}>
                    {c.name ?? 'unnamed'} {(c.distance_m / 1000).toFixed(1)} km{c.size === 'mismatch' ? ' (size differs)' : ''}
                  </span>
                ))}
              </li>
            )}
          </ul>
        </div>
      )}
    </li>
  )
}

export const AreaSearch: React.FC<{
  drawing: boolean
  onDraw: () => void
  box: BBox | null
  onClear: () => void
  onGo: () => void
  job: SearchJob | null
  openShip: number | null
  onShip: (id: number | null) => void
  period: [string, string]
  onPeriod: (p: [string, string]) => void
  periodSearch: boolean             // backend runs time-period searches (Render + Modal worker)
  pass: number
  onPass: (i: number) => void
  onBox: (b: BBox) => void
  onPassUpdated?: (i: number, p: SearchResult) => void   // a saved pass gained its silent-AIS list
}> = ({ drawing, onDraw, box, onClear, onGo, job, openShip, onShip, period, onPeriod, periodSearch, pass, onPass, onBox, onPassUpdated }) => {
  const [w, h] = box ? boxKm(box) : [0, 0]
  const tooBig = !!box && !periodSearch && Math.max(w, h) > MAX_KM
  const sizeError = box && Math.min(w, h) < MIN_KM
    ? `Draw a box at least ${MIN_KM} km on each side (one satellite image tile). This one is ${w.toFixed(0)} × ${h.toFixed(0)} km.`
    : tooBig ? `Boxes must be ${MIN_KM}–${MAX_KM} km on each side here. This one is ${w.toFixed(0)} × ${h.toFixed(0)} km.` : null
  const busy = job?.status === 'queued' || job?.status === 'running'
  const full = job?.status === 'done' ? job.result : undefined
  const passes = passesOf(full)
  const isPeriod = !!full && 'passes' in full
  const selected = passes[pass]
  const result = selected && !isFailedPass(selected) ? selected : undefined
  // A search saved before the silent-AIS check existed gets it when one of its passes is opened.
  const [silentCheck, setSilentCheck] = React.useState<{ key: string; error?: string } | null>(null)
  const needsSilent = !!(result && job?.job_id && result.ais_available && result.ais_silent === undefined && !result.ais_silent_note)
  const checkKey = `${job?.job_id}:${pass}`
  React.useEffect(() => {
    if (!needsSilent || !job?.job_id || silentCheck?.key === checkKey) return
    setSilentCheck({ key: checkKey })
    apiService.checkSilent(job.job_id, pass)
      .then((p) => onPassUpdated?.(pass, p))
      .catch((e) => setSilentCheck({ key: checkKey, error: e instanceof Error ? e.message : 'The check failed.' }))
  }, [needsSilent, checkKey])   // once per pass
  const dateError = periodSearch ? periodError(period) : null
  const showWeak = useDashboardStore((s) => s.showWeak)
  const setShowWeak = useDashboardStore((s) => s.setShowWeak)
  const ships = result ? result.ships.filter((s) => showWeak || !s.weak) : []
  const nWeak = result?.counts.weak_candidates ?? 0
  const [est, setEst] = React.useState<{ data?: SearchEstimate; error?: string; loading?: boolean }>({})
  const boxKey = box?.join() ?? ''
  React.useEffect(() => {               // the estimate follows the box and dates, debounced
    if (!periodSearch || !box || sizeError || dateError || busy || full) { setEst({}); return }
    let live = true
    setEst({ loading: true })
    const t = setTimeout(() => apiService.estimateSearch(box, period[0], period[1])
      .then((data) => live && setEst({ data }))
      .catch((e) => live && setEst({ error: e instanceof Error ? e.message : 'Could not count the passes. Try again in a minute.' })), 600)
    return () => { live = false; clearTimeout(t) }
  }, [periodSearch, boxKey, period[0], period[1], !!sizeError, !!dateError, busy, !!full])
  const estBlocks = periodSearch && (!est.data || est.data.over_limit || est.data.over_daily)

  return (
    <Panel title="Area search" right={box && <span className="text-[10px] text-ink-3">{w.toFixed(0)} × {h.toFixed(0)} km</span>} bodyClassName="space-y-3 p-3">
      {!box && (
        <>
          <p className="text-xs leading-relaxed text-ink-2">
            {drawing
              ? 'Drag on the map to draw a box over open water.'
              : periodSearch
                ? 'Draw a box of any size and pick a time period: every Sentinel-1 pass in it is searched and each ship checked against AIS. You see how long it will take before you press Go.'
                : 'Draw a box to run the detector on the newest Sentinel-1 pass over it and check every ship against AIS.'}
          </p>
          <button onClick={onDraw} className={drawing ? 'btn-quiet w-full border-signal text-signal' : 'btn-quiet w-full'}>
            {drawing ? 'Drawing… drag on the map' : 'Draw area'}
          </button>
        </>
      )}

      {box && !busy && !full && (
        <>
          <p className="text-[11px] text-ink-3">
            {box[1].toFixed(2)}°, {box[0].toFixed(2)}° to {box[3].toFixed(2)}°, {box[2].toFixed(2)}°
          </p>
          {sizeError && <p className="text-xs text-partial">{sizeError}</p>}
          {tooBig && box && (
            <button onClick={() => onBox(shrinkBox(box))} className="btn-quiet w-full">
              Use a 50 × 50 km box at its centre
            </button>
          )}
          {periodSearch && (
            <fieldset className="space-y-1">
              <legend className="text-[10px] uppercase tracking-wider text-ink-3">Time period (UTC)</legend>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] text-ink-3">From
                  <input type="date" value={period[0]} min={ARCHIVE_START} max={period[1]}
                    onChange={(e) => onPeriod([e.target.value, period[1]])} className="mt-0.5 w-full border border-rule bg-transparent px-1.5 py-1 text-xs text-ink" />
                </label>
                <label className="text-[11px] text-ink-3">To
                  <input type="date" value={period[1]} min={period[0]} max={isoDay(new Date())}
                    onChange={(e) => onPeriod([period[0], e.target.value])} className="mt-0.5 w-full border border-rule bg-transparent px-1.5 py-1 text-xs text-ink" />
                </label>
              </div>
              {dateError && <p className="text-xs text-partial">{dateError}</p>}
            </fieldset>
          )}
          {periodSearch && <EstimateLine est={est} />}
          {job?.status === 'error' && <p role="alert" className="text-xs text-unmatched">{job.error}</p>}
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <button onClick={onGo} disabled={!!sizeError || !!dateError || estBlocks} className="btn-primary py-2.5 text-sm">Go</button>
            <button onClick={onClear} className="btn-quiet">Redraw</button>
          </div>
        </>
      )}

      {job?.status === 'done' && !full && (
        <p role="alert" className="text-xs text-partial">{job.result_missing ?? 'This search has no saved results.'}</p>
      )}
      {busy && (
        <div className="space-y-2" role="status">
          <p className="text-xs text-ink">{job?.stage || 'Sending the box'}</p>
          <div className="h-1 bg-rule">
            <div className="h-full bg-signal transition-[width] duration-500" style={{ width: `${Math.max(4, (job?.progress ?? 0) * 100)}%` }} />
          </div>
          <p className="text-[11px] text-ink-3">Step by step in the search log below the map.</p>
        </div>
      )}

      {isPeriod && full && 'passes' in full && (
        <div className="space-y-2">
          <p className="text-[11px] leading-relaxed text-ink-2">
            {full.period ? <>{full.period[0]} to {full.period[1]}: </> : null}
            {full.passes_searched} of {full.passes_found} pass{full.passes_found === 1 ? '' : 'es'} searched
            {full.passes_failed ? `, ${full.passes_failed} failed` : ''}. {full.counts.ais_unmatched} ships without AIS
            at {full.counts.ais_unmatched_spots} place{full.counts.ais_unmatched_spots === 1 ? '' : 's'}
            {full.recurring.length ? `; ${full.recurring.length} seen on several passes` : ''}.
          </p>
          <ol className="grid gap-1" aria-label="Satellite passes">
            {passes.map((p, i) => (
              <li key={p.scene.id}>
                <button onClick={() => { onPass(i); onShip(null) }} aria-pressed={i === pass}
                  className={`flex w-full items-center gap-2 border px-2 py-1.5 text-left text-[11px] ${i === pass ? 'border-signal text-ink' : 'border-rule text-ink-2 hover:bg-white/[0.03]'}`}>
                  <span className="flex-1">{day(p.scene.time)} UTC</span>
                  {isFailedPass(p) ? <span className="text-unmatched">failed</span> : (
                    <>
                      <span>{p.counts.ships} ships</span>
                      <span className={p.counts.ais_unmatched ? 'text-unmatched' : 'text-ink-3'}>{p.counts.ais_unmatched} no AIS</span>
                      {p.ais_available === false && <span className="text-ink-3" title={p.scene_note ?? ''}>AIS unchecked</span>}
                    </>
                  )}
                </button>
              </li>
            ))}
          </ol>
          {selected && isFailedPass(selected) && (
            <p role="alert" className="text-xs text-unmatched">This pass failed: {selected.error}</p>
          )}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <dl className="grid grid-cols-3 border border-rule text-center">
            {([['Ships', result.counts.ships], ['No AIS', result.counts.ais_unmatched], ['Pairs', result.counts.sts_pairs]] as const).map(([k, v]) => (
              <div key={k} className="border-rule py-2 [&:not(:last-child)]:border-r">
                <dd className="text-lg font-bold text-ink">{v}</dd>
                <dt className="text-[10px] uppercase tracking-wider text-ink-3">{k}</dt>
              </div>
            ))}
          </dl>
          {result.coverage && result.coverage.label !== 'none' && (
            <details className="border border-rule px-2 py-1.5 text-[11px]">
              <summary className="cursor-pointer text-ink-2">
                AIS coverage:{' '}
                <span className={result.coverage.label === 'good' ? 'text-signal' : result.coverage.label === 'fair' ? 'text-partial' : 'text-unmatched'}>
                  {result.coverage.label} ({result.coverage.score.toFixed(2)})
                </span>
              </summary>
              <ul className="mt-1 space-y-0.5 text-ink-3">
                {result.coverage.factors.map((f) => <li key={f}>{f}</li>)}
                <li>Low coverage makes "no AIS" weak evidence; it never makes it proof.</li>
              </ul>
            </details>
          )}
          <p className="text-[11px] leading-relaxed text-ink-3">
            {result.ais_source && <>AIS: {result.ais_source}. </>}
            {result.scene.platform ?? 'Sentinel-1'} pass of {new Date(result.scene.time).toUTCString().slice(5, 22)} UTC
            {result.cached ? ', from an earlier search.' : '.'} {result.scene_note}
          </p>
          {result.ais_silent && <SilentAis ships={result.ais_silent} passTime={result.scene.time} onShip={onShip} />}
          {needsSilent && silentCheck?.key === checkKey && (
            <p role="status" className="text-[11px] text-ink-3">
              {silentCheck.error ? `Ships with silent AIS could not be checked: ${silentCheck.error}`
                : 'Checking which ships had their AIS silent at this pass (about 30 s, once per pass)…'}
            </p>
          )}
          {result.ais_silent_note && <p className="text-[11px] text-partial">{result.ais_silent_note}</p>}
          {nWeak > 0 && (
            <label className="flex items-start gap-2 text-[11px] text-ink-2">
              <input type="checkbox" checked={showWeak} onChange={(e) => setShowWeak(e.target.checked)} className="mt-0.5" />
              <span>
                Show {nWeak} weak candidate{nWeak === 1 ? '' : 's'} (detector score {result.thresholds?.weak ?? 0.15}–{result.thresholds?.ship ?? 0.25})
                <span className="block text-ink-3">Not in the counts above. How often scores this low are real ships has not been measured yet.</span>
              </span>
            </label>
          )}
          {ships.length ? (
            <ul className="max-h-72 overflow-y-auto">
              {ships.map((s) => (
                <ShipRow key={s.id} ship={s} open={openShip === s.id} onToggle={() => onShip(openShip === s.id ? null : s.id)} />
              ))}
            </ul>
          ) : (
            <p className="text-xs text-ink-2">No ships detected in this pass. Try a box over busier water.</p>
          )}
          <p className="text-[11px] leading-relaxed text-ink-3">{result.note}</p>
        </div>
      )}
      {full && <button onClick={onClear} className="btn-quiet w-full">New search</button>}
    </Panel>
  )
}
