import React from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import type { BBox, SearchJob, SearchShip } from '../services/api'
import { STATUS } from '../status'
import { Panel } from './Panel'

// Mirrors src/search.py: one 1024 px tile at minimum, the free-CPU budget at maximum.
const MIN_KM = 11
const MAX_KM = 60
export const boxKm = (b: BBox) => [
  (b[2] - b[0]) * 111.32 * Math.cos(((b[1] + b[3]) / 2) * Math.PI / 180),
  (b[3] - b[1]) * 110.57,
]

const CATEGORY: Record<string, { label: string; color: string }> = {
  ...STATUS,
  AIS_NOT_AVAILABLE: { label: 'AIS not available', color: '#838383' },
}

const Scanner: React.FC<{ job: SearchJob | null; stages: string[] }> = ({ job, stages }) => (
  <div className="space-y-3" role="status" aria-live="polite">
    <div className="flex items-center gap-3">
      <div className="radar h-14 w-14 shrink-0 rounded-full border border-signal/40" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-wider text-signal">
          {job?.status === 'queued' && job.queue_position ? `Queued, ${job.queue_position} ahead` : 'Scanning'}
        </p>
        <p className="mt-1 text-xs leading-snug text-ink">{job?.stage || 'Sending the box'}</p>
      </div>
    </div>
    <div className="h-1 bg-rule">
      <div className="h-full bg-signal transition-[width] duration-500" style={{ width: `${Math.max(4, (job?.progress ?? 0) * 100)}%` }} />
    </div>
    <ol className="space-y-0.5 text-[11px] text-ink-3">
      {stages.map((s, i) => (
        <li key={s} className={i === stages.length - 1 ? 'text-ink-2' : ''}>
          <span className={i === stages.length - 1 ? 'text-signal' : 'text-ink-3'}>{i === stages.length - 1 ? '>' : '✓'}</span> {s}
        </li>
      ))}
    </ol>
  </div>
)

const ShipRow: React.FC<{ ship: SearchShip; open: boolean; onToggle: () => void }> = ({ ship, open, onToggle }) => {
  const cat = CATEGORY[ship.category] ?? { label: ship.category, color: '#E8E8E8' }
  return (
    <li className="border-t border-rule first:border-t-0">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-2 py-2 text-left hover:bg-white/[0.03]">
        <span className="h-2 w-2 shrink-0" style={{ background: cat.color }} />
        <span className="flex-1 text-xs text-ink">Ship {ship.id + 1}</span>
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
  stages: string[]
  openShip: number | null
  onShip: (id: number | null) => void
}> = ({ drawing, onDraw, box, onClear, onGo, job, stages, openShip, onShip }) => {
  const [w, h] = box ? boxKm(box) : [0, 0]
  const sizeError = box && (Math.min(w, h) < MIN_KM || Math.max(w, h) > MAX_KM)
    ? `Boxes must be ${MIN_KM}–${MAX_KM} km on each side. This one is ${w.toFixed(0)} × ${h.toFixed(0)} km.`
    : null
  const busy = job?.status === 'queued' || job?.status === 'running'
  const result = job?.status === 'done' ? job.result : undefined
  const showWeak = useDashboardStore((s) => s.showWeak)
  const setShowWeak = useDashboardStore((s) => s.setShowWeak)
  const ships = result ? result.ships.filter((s) => showWeak || !s.weak) : []
  const nWeak = result?.counts.weak_candidates ?? 0

  return (
    <Panel title="Area search" right={box && <span className="text-[10px] text-ink-3">{w.toFixed(0)} × {h.toFixed(0)} km</span>} bodyClassName="space-y-3 p-3">
      {!box && (
        <>
          <p className="text-xs leading-relaxed text-ink-2">
            {drawing
              ? 'Drag on the map to draw a box over open water.'
              : 'Draw a box to run the detector on the newest Sentinel-1 pass over it and check every ship against AIS.'}
          </p>
          <button onClick={onDraw} className={drawing ? 'btn-quiet w-full border-signal text-signal' : 'btn-quiet w-full'}>
            {drawing ? 'Drawing… drag on the map' : 'Draw area'}
          </button>
        </>
      )}

      {box && !busy && !result && (
        <>
          <p className="text-[11px] text-ink-3">
            {box[1].toFixed(2)}°, {box[0].toFixed(2)}° to {box[3].toFixed(2)}°, {box[2].toFixed(2)}°
          </p>
          {sizeError && <p className="text-xs text-partial">{sizeError}</p>}
          {job?.status === 'error' && <p role="alert" className="text-xs text-unmatched">{job.error}</p>}
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <button onClick={onGo} disabled={!!sizeError} className="btn-primary py-2.5 text-sm">Go</button>
            <button onClick={onClear} className="btn-quiet">Redraw</button>
          </div>
        </>
      )}

      {busy && <Scanner job={job} stages={stages} />}

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
          <button onClick={onClear} className="btn-quiet w-full">New search</button>
        </div>
      )}
    </Panel>
  )
}
