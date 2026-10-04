import React, { useEffect, useState } from 'react'
import { apiService, ShipPhoto, VesselDetail, VesselIdentity } from '../services/api'

const ago = (s?: number) => s === undefined ? null : s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`
// 'NO' -> 🇳🇴 (regional indicator letters)
const flagEmoji = (iso2: string) => String.fromCodePoint(...[...iso2.toUpperCase()].map((c) => 127397 + c.charCodeAt(0)))

export const VesselCard: React.FC<{
  mmsi: string
  onClose: () => void
  onLoaded: (v: VesselDetail) => void
  onSearchHere: (lat: number, lon: number) => void
  showTrack: boolean
  onToggleTrack: () => void
}> = ({ mmsi, onClose, onLoaded, onSearchHere, showTrack, onToggleTrack }) => {
  const [v, setV] = useState<VesselDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [photo, setPhoto] = useState<ShipPhoto | null | undefined>(undefined)
  const [ident, setIdent] = useState<VesselIdentity | null>(null)

  useEffect(() => {
    let live = true
    const load = () => apiService.getVessel(mmsi)
      .then((d) => { if (live) { setV(d); setError(null); onLoaded(d) } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : 'Could not load this ship.') })
    setV(null)
    setPhoto(undefined)
    setIdent(null)
    load()
    const t = setInterval(load, 15000)   // type, ETA and IMO can arrive a few minutes after the first position
    return () => { live = false; clearInterval(t) }
  }, [mmsi, onLoaded])

  // Slow lookups, once per ship: GFW identity when AIS static data is missing, and a photo by IMO.
  // Asked again if the ship's own IMO arrives later and no photo was found.
  useEffect(() => {
    if (!v || photo) return
    let live = true
    apiService.getVesselExtra(mmsi)
      .then((x) => { if (live) { setIdent(x.identity); setPhoto(x.photo) } })
      .catch(() => live && setPhoto(null))
    return () => { live = false }
  }, [mmsi, !!v, v?.imo]) // eslint-disable-line react-hooks/exhaustive-deps

  // AIS first; Global Fishing Watch where AIS has not said yet
  const type = v?.type ?? ident?.type ?? null
  const imo = v?.imo ?? ident?.imo ?? null
  const callsign = v?.callsign ?? ident?.callsign ?? null
  const length = v?.length_m ?? ident?.length_m ?? null
  const fromGfw = !!ident && ((!v?.type && !!ident.type) || (!v?.imo && !!ident.imo))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const details: [string, React.ReactNode][] = v ? [
    ['Flag', v.flag?.country ?? 'Unknown'],
    ['MMSI', v.mmsi],
    ['IMO', imo ?? '—'],
    ['Call sign', callsign ?? '—'],
    ['Size', length ? `${length} × ${v.beam_m ?? '?'} m` : '—'],
    ...(ident?.tonnage_gt ? [['Gross tonnage', ident.tonnage_gt.toLocaleString()] as [string, React.ReactNode]] : []),
    ['Position', v.lat != null ? `${v.lat.toFixed(4)}, ${v.lon!.toFixed(4)}` : '—'],
  ] : []
  const trackPoints = v?.track?.length ?? 0

  return (
    <section className="panel w-full shadow-2xl" role="dialog" aria-label="Ship details">
      <header className="flex items-start gap-2.5 border-b border-rule px-3 py-2.5">
        {v?.flag && (
          <span className="mt-0.5 text-2xl leading-none" role="img" aria-label={`Flag: ${v.flag.country}`} title={v.flag.country}>
            {flagEmoji(v.flag.iso2)}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-sans text-lg font-bold leading-tight text-ink">{v?.name || (v ? 'Unnamed ship' : 'Loading…')}</h2>
          <p className="truncate text-xs text-ink-2">{v ? type ?? (photo === undefined ? 'Looking up type…' : 'Type unknown') : ' '}</p>
        </div>
        <button onClick={onClose} aria-label="Close ship details" className="px-1 text-xl leading-none text-ink-2 hover:text-ink">×</button>
      </header>

      {error && <p role="alert" className="p-3 text-xs text-unmatched">{error}</p>}

      {v && (
        <>
          <figure className="relative aspect-[16/10] bg-paper">
            {photo ? (
              <>
                <img src={photo.url} alt={`Photo of ${v.name || 'the ship'}`} className="h-full w-full object-cover" />
                <figcaption className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-2 py-1 text-[10px] text-ink-2">
                  <a href={photo.page ?? undefined} target="_blank" rel="noreferrer" className="hover:text-ink">
                    © {photo.author ?? 'Unknown'}{photo.license ? `, ${photo.license}` : ''}, {photo.source}
                  </a>
                </figcaption>
              </>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
                <svg width="56" height="20" viewBox="0 0 56 20" aria-hidden="true" className="text-ink-3">
                  <path d="M2 12h44l8-6v6l-6 6H8z" fill="none" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M14 12V6h10v6M28 12V3h6v9" fill="none" stroke="currentColor" strokeWidth="1.5" />
                </svg>
                <p className="text-[11px] text-ink-3">
                  {photo === undefined ? 'Looking for a photo…' : imo ? 'No public photo of this ship on Wikimedia Commons' : 'No IMO number known, so no photo lookup'}
                </p>
              </div>
            )}
          </figure>

          <div className="grid grid-cols-3 gap-1.5 border-b border-rule p-2">
            <button onClick={onToggleTrack} disabled={trackPoints < 2} aria-pressed={showTrack}
              className={showTrack ? 'btn-quiet border-signal px-1 text-signal' : 'btn-quiet px-1'}
              title={trackPoints < 2 ? 'Not enough positions recorded yet' : undefined}>Past track</button>
            <button className="btn-quiet px-1" disabled={v.lat == null} onClick={() => onSearchHere(v.lat!, v.lon!)}>Search area</button>
            <a className="btn-primary px-1" target="_blank" rel="noreferrer"
              href={`https://www.marinetraffic.com/en/ais/details/ships/mmsi:${v.mmsi}`}>Details ↗</a>
          </div>

          <div className="flex items-end justify-between gap-3 border-b border-rule px-3 py-3">
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-ink-3">Destination</p>
              <p className="truncate font-sans text-xl font-bold text-ink">{v.destination ?? 'Not broadcast'}</p>
            </div>
            <div className="shrink-0 text-right">
              <p className="text-[10px] uppercase tracking-wider text-ink-3">Reported ETA</p>
              <p className="text-sm text-ink">{v.eta ?? '—'}</p>
            </div>
          </div>

          <dl className="grid grid-cols-3 border-b border-rule text-xs">
            {([['Status', v.nav_status ?? '—'], ['Speed / course', v.sog != null ? `${v.sog} kn / ${v.cog != null ? Math.round(v.cog) : '?'}°` : '—'],
              ['Draught', v.draught_m ? `${v.draught_m} m` : '—']] as const).map(([k, val]) => (
              <div key={k} className="border-rule px-3 py-2 [&:not(:last-child)]:border-r">
                <dt className="text-[10px] uppercase tracking-wider text-ink-3">{k}</dt>
                <dd className="mt-1 font-bold leading-snug text-ink">{val}</dd>
              </div>
            ))}
          </dl>

          <dl className="px-3 py-1 text-xs">
            {details.map(([k, val]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-rule py-1.5 last:border-b-0">
                <dt className="text-ink-3">{k}</dt>
                <dd className="truncate text-right text-ink">{val}</dd>
              </div>
            ))}
          </dl>

          <p className="border-t border-rule px-3 py-2 text-[11px] text-ink-3">
            Received <span className="text-ink-2">{ago(v.age_s) ?? '—'}</span> (AIS source: aisstream.io, terrestrial)
            {fromGfw && <>. Type, IMO or call sign via {ident!.source}</>}
            {trackPoints > 1 && <>. Track covers the last {ago(v.track_since_s)?.replace(' ago', '')}.</>}
          </p>
        </>
      )}
    </section>
  )
}
