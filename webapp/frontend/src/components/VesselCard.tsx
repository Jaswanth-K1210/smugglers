import React, { useEffect, useRef, useState } from 'react'
import { apiService, LiveVessel, Particulars, ShipPhoto, VesselDetail, VesselIdentity } from '../services/api'

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
  initial?: LiveVessel             // the map's own row: name, position and speed show at once
}> = ({ mmsi, onClose, onLoaded, onSearchHere, showTrack, onToggleTrack, initial }) => {
  const [v, setV] = useState<VesselDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [photo, setPhoto] = useState<ShipPhoto | null | undefined>(undefined)
  const [ident, setIdent] = useState<VesselIdentity | null>(null)
  const [part, setPart] = useState<Particulars | null>(null)
  // 48 h track from Open Waters, kept across the 15 s refreshes (which carry only our own shorter track)
  const longTrack = useRef<[number, number][]>([])
  const first = useRef(initial)
  first.current = initial

  useEffect(() => {
    let live = true
    let retry: ReturnType<typeof setTimeout>
    const load = () => apiService.getVessel(mmsi)
      .then((d) => {
        if (!live) return
        if (longTrack.current.length > (d.track?.length ?? 0)) d = { ...d, track: longTrack.current }
        setV(d); setError(null); onLoaded(d)
      })
      .catch((e) => {
        if (!live) return
        setError(`${e instanceof Error ? e.message : 'Could not load this ship.'} Retrying…`)
        retry = setTimeout(load, 5000)       // the server may be waking up or restarting
      })
    setV(first.current ? { ...first.current, type: null } : null)   // full details replace it in ~0.5 s
    setPhoto(undefined)
    setIdent(null)
    setPart(null)
    longTrack.current = []
    load()
    const t = setInterval(load, 15000)   // type, ETA and IMO can arrive a few minutes after the first position
    return () => { live = false; clearInterval(t); clearTimeout(retry) }
  }, [mmsi, onLoaded])

  // Slow lookups, once per ship: GFW identity when AIS static data is missing, and a photo by IMO.
  // Asked again if the ship's own IMO arrives later and no photo was found.
  useEffect(() => {
    if (!v || photo) return
    let live = true
    apiService.getVesselExtra(mmsi)
      .then((x) => {
        if (!live) return
        setIdent(x.identity); setPhoto(x.photo); setPart(x.particulars ?? null)
        if (x.track && x.track.length > (v.track?.length ?? 0)) {
          longTrack.current = x.track
          const withTrack = { ...v, track: x.track, track_since_s: 48 * 3600 }
          setV(withTrack); onLoaded(withTrack)
        }
      })
      .catch(() => live && setPhoto(null))
    return () => { live = false }
  }, [mmsi, !!v, v?.imo]) // eslint-disable-line react-hooks/exhaustive-deps

  // AIS first; Global Fishing Watch where AIS has not said yet
  const type = v?.type ?? ident?.type ?? null
  const imo = v?.imo ?? ident?.imo ?? null
  const callsign = v?.callsign ?? ident?.callsign ?? null
  const length = v?.length_m ?? ident?.length_m ?? null
  // External pages: by MMSI where we have one; regional Gulf ships carry none, so search by name / IMO
  const regionalShip = mmsi.startsWith('hn:')
  const q = encodeURIComponent(v?.name ?? '')
  const marineTraffic = !regionalShip
    ? `https://www.marinetraffic.com/en/ais/details/ships/mmsi:${mmsi}`
    : `https://www.marinetraffic.com/en/ais/index/search/all/keyword:${q}`
  const vesselFinder = imo ? `https://www.vesselfinder.com/vessels/details/${imo}`
    : regionalShip ? `https://www.vesselfinder.com/vessels?name=${q}` : `https://www.vesselfinder.com/vessels/details/${mmsi}`
  const fromGfw = !!ident && ((!v?.type && !!ident.type) || (!v?.imo && !!ident.imo))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const details: [string, React.ReactNode][] = v ? [
    ['Flag', v.flag?.country ?? 'Unknown'],
    [regionalShip ? 'Feed ID' : 'MMSI', regionalShip ? v.mmsi.slice(3) : v.mmsi],
    ['IMO', imo ?? '—'],
    ['Call sign', callsign ?? '—'],
    ['Size', length ? `${length} × ${v.beam_m ?? '?'} m` : '—'],
    ...(v.dwt ? [['Deadweight', `${Math.round(v.dwt).toLocaleString()} t`] as [string, React.ReactNode]] : []),
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
                {photo === null && (
                  <p className="text-[11px] text-ink-3">
                    Photos on{' '}
                    <a className="text-ink-2 underline hover:text-ink" href={marineTraffic} target="_blank" rel="noreferrer">MarineTraffic</a>
                    {' or '}
                    <a className="text-ink-2 underline hover:text-ink" href={vesselFinder} target="_blank" rel="noreferrer">VesselFinder</a>
                  </p>
                )}
              </div>
            )}
          </figure>

          <div className="grid grid-cols-3 gap-1.5 border-b border-rule p-2">
            <button onClick={onToggleTrack} disabled={trackPoints < 2} aria-pressed={showTrack}
              className={showTrack ? 'btn-quiet border-signal px-1 text-signal' : 'btn-quiet px-1'}
              title={trackPoints < 2 ? 'Not enough positions recorded yet' : undefined}>Past track</button>
            <button className="btn-quiet px-1" disabled={v.lat == null} onClick={() => onSearchHere(v.lat!, v.lon!)}>Search area</button>
            <a className="btn-primary px-1" target="_blank" rel="noreferrer" href={marineTraffic}>Details ↗</a>
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

          {part && (
            <div className="border-t border-rule px-3 py-2">
              <p className="text-[10px] uppercase tracking-wider text-ink-3">Registered particulars</p>
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                {([['Builder', part.fields.builder], ['Built', part.fields.year_built],
                   ['Gross tonnage', part.fields.gross_tonnage != null ? Number(part.fields.gross_tonnage).toLocaleString() : null],
                   ['Deadweight', part.fields.deadweight != null ? `${Number(part.fields.deadweight).toLocaleString()} t` : null],
                   ['Registry', part.fields.registry], ['Home port', part.fields.home_port]] as const)
                  .filter(([, val]) => val != null && val !== '')
                  .map(([k, val]) => (
                    <div key={k} className="min-w-0">
                      <dt className="text-[10px] text-ink-3">{k}</dt>
                      <dd className="truncate text-ink">{String(val)}</dd>
                    </div>
                  ))}
              </dl>
              <p className="mt-1 text-[10px] text-ink-3">{part.source}</p>
            </div>
          )}

          <p className="border-t border-rule px-3 py-2 text-[11px] text-ink-3">
            Received <span className="text-ink-2">{ago(v.age_s) ?? '—'}</span> (AIS source: {v.source ?? 'aisstream.io, terrestrial'})
            {fromGfw && <>. Type, IMO or call sign via {ident!.source}</>}
            {trackPoints > 1 && <>. Track covers the last {ago(v.track_since_s)?.replace(' ago', '')}.</>}
          </p>
        </>
      )}
    </section>
  )
}
