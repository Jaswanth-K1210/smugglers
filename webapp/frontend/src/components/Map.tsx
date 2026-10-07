import React, { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, ZoomControl, Rectangle, Polyline, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS } from '../status'
import type { BBox, GfwLayers, LiveVessel, SearchResult } from '../services/api'

const SILENT = '#B98CFF'      // ships whose AIS was silent across the pass

const SEARCH_COLORS: Record<string, string> = {
  AIS_VISIBLE: STATUS.AIS_VISIBLE.color,
  AIS_PARTIAL: STATUS.AIS_PARTIAL.color,
  AIS_UNMATCHED: STATUS.AIS_UNMATCHED.color,
  AIS_NOT_AVAILABLE: '#838383',
}

const toBox = (b: L.LatLngBounds): BBox => [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
const toBounds = (b: BBox): L.LatLngBoundsExpression => [[b[1], b[0]], [b[3], b[2]]]

// Drag on the map to draw a box. Panning is off while drawing so the drag draws instead.
// ponytail: mouse only; touch drawing needs pointer events if the console goes mobile.
const DrawBox: React.FC<{ active: boolean; onBox: (b: BBox) => void }> = ({ active, onBox }) => {
  const map = useMap()
  const start = useRef<L.LatLng | null>(null)
  const [draft, setDraft] = useState<L.LatLngBounds | null>(null)

  useEffect(() => {
    if (active) { map.dragging.disable(); map.boxZoom.disable(); map.getContainer().style.cursor = 'crosshair' }
    else { map.dragging.enable(); map.boxZoom.enable(); map.getContainer().style.cursor = '' }
  }, [active, map])

  useMapEvents({
    mousedown(e) { if (active) { start.current = e.latlng; setDraft(null) } },
    mousemove(e) { if (active && start.current) setDraft(L.latLngBounds(start.current, e.latlng)) },
    mouseup(e) {
      if (!active || !start.current) return
      const b = L.latLngBounds(start.current, e.latlng)
      start.current = null
      setDraft(null)
      if (!b.getSouthWest().equals(b.getNorthEast())) onBox(toBox(b))
    },
  })

  return draft ? <Rectangle bounds={draft} pathOptions={{ color: '#44FF88', weight: 1.5, dashArray: '4 4', fillOpacity: 0.06 }} /> : null
}

// Ship type groups in MarineTraffic's colour conventions, which analysts already read at a
// glance: pale fill, darker outline of the same hue. Tankers, the class that matters for
// sanctions work, also get a heavier outline so they do not rely on red alone.
export const SHIP_GROUPS = [
  { id: 'cargo', label: 'Cargo', fill: '#9BE38F', stroke: '#2F7A26', members: ['cargo'] },
  { id: 'tanker', label: 'Tanker', fill: '#F0473E', stroke: '#7A120D', members: ['tanker'] },
  { id: 'passenger', label: 'Passenger', fill: '#2B5BFF', stroke: '#10288A', members: ['passenger'] },
  { id: 'highspeed', label: 'High-speed craft', fill: '#F5DD45', stroke: '#8C7A10', members: ['highspeed'] },
  { id: 'special', label: 'Tug & special', fill: '#5FE0E6', stroke: '#16777C', members: ['special'] },
  { id: 'fishing', label: 'Fishing', fill: '#F7A68A', stroke: '#A64A2C', members: ['fishing'] },
  { id: 'pleasure', label: 'Pleasure craft', fill: '#D86BEB', stroke: '#7A1E8F', members: ['pleasure'] },
  { id: 'other', label: 'Other / unknown', fill: '#C9CCD1', stroke: '#5E636B', members: ['other', 'unknown'] },
] as const
const GROUP_STYLE: Record<string, { fill: string; stroke: string }> =
  Object.fromEntries(SHIP_GROUPS.flatMap((g) => g.members.map((m) => [m, { fill: g.fill, stroke: g.stroke }])))

export const BASEMAPS = {
  light: {
    base: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    labels: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    background: '#F2F3F4',
  },
  dark: {
    base: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    labels: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    background: '#020A08',
  },
} as const
export type MapStyle = keyof typeof BASEMAPS

// Live ships drawn on one canvas over the tiles: an arrow along the heading when
// under way, a dot when stopped. 20k ships redraw in a few ms; hover and click are
// found by nearest screen point, so no per-ship DOM or Leaflet objects exist.
const ShipCanvas: React.FC<{ vessels: LiveVessel[]; onPick: (mmsi: string) => void; enabled: boolean }> = ({ vessels, onPick, enabled }) => {
  const map = useMap()
  const canvas = useRef<HTMLCanvasElement | null>(null)
  const points = useRef<{ x: number; y: number; v: LiveVessel }[]>([])
  const data = useRef(vessels)
  const tip = useRef(L.tooltip({ direction: 'top', offset: [0, -6] }))
  const pick = useRef(onPick)
  const on = useRef(enabled)
  data.current = vessels
  pick.current = onPick
  on.current = enabled

  const draw = useRef(() => {})
  draw.current = () => {
    const c = canvas.current
    if (!c) return
    const { x: w, y: h } = map.getSize()
    const dpr = window.devicePixelRatio || 1
    if (c.width !== w * dpr || c.height !== h * dpr) { c.width = w * dpr; c.height = h * dpr; c.style.width = `${w}px`; c.style.height = `${h}px` }
    // the pane moves with the map; pin the canvas to the viewport's top-left corner
    L.DomUtil.setPosition(c, map.containerPointToLayerPoint([0, 0]))
    const ctx = c.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    const pts: typeof points.current = []
    const zoom = map.getZoom()
    const zk = zoom >= 11 ? 1.35 : zoom >= 9 ? 1.15 : zoom >= 6 ? 0.95 : 0.75
    // Zoomed far out (or across the 180° line) the map shows several copies of the world:
    // draw each ship on every copy in view, not only on the one between -180° and 180°.
    const west = map.getBounds().getWest(), east = map.getBounds().getEast()
    for (const v of data.current) {
      for (let copy = Math.ceil((west - v.lon) / 360); copy <= Math.floor((east - v.lon) / 360); copy++) {
        const p = map.latLngToContainerPoint([v.lat, v.lon + 360 * copy])
        if (p.x < -10 || p.y < -10 || p.x > w + 10 || p.y > h + 10) continue
        pts.push({ x: p.x, y: p.y, v })
        const dir = v.heading ?? v.cog
        const style = GROUP_STYLE[v.group ?? 'unknown'] ?? GROUP_STYLE.unknown
        // bigger ships draw bigger, as on MarineTraffic
        const k = zk * (v.len == null ? 1 : v.len < 40 ? 0.8 : v.len < 120 ? 1 : v.len < 220 ? 1.15 : 1.3)
        ctx.fillStyle = style.fill
        ctx.strokeStyle = style.stroke
        ctx.lineWidth = v.group === 'tanker' ? 1.6 : 1
        ctx.beginPath()
        if ((v.sog ?? 0) >= 0.5 && dir != null) {
          const a = (dir * Math.PI) / 180
          const cos = Math.cos(a), sin = Math.sin(a)
          const shape: [number, number][] = [[0, -8], [4.6, 6], [0, 3.4], [-4.6, 6]]
          shape.forEach(([sx, sy], i) => {
            const x = p.x + (sx * cos - sy * sin) * k, y = p.y + (sx * sin + sy * cos) * k
            i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
          })
          ctx.closePath()
        } else {
          ctx.arc(p.x, p.y, 3.2 * k, 0, Math.PI * 2)
        }
        ctx.fill()
        ctx.stroke()
      }
    }
    points.current = pts
  }

  const nearest = (cp: L.Point) => {
    let best: (typeof points.current)[number] | null = null, bd = 64  // within 8 px
    for (const q of points.current) {
      const d = (q.x - cp.x) ** 2 + (q.y - cp.y) ** 2
      if (d < bd) { bd = d; best = q }
    }
    return best
  }

  useEffect(() => {
    // Own pane inside the map pane: above tiles (200), below candidate and search markers (400)
    const pane = map.getPane('ships') ?? map.createPane('ships')
    pane.style.zIndex = '350'
    pane.style.pointerEvents = 'none'
    const c = L.DomUtil.create('canvas', 'leaflet-zoom-hide', pane)
    c.style.position = 'absolute'
    canvas.current = c
    const redraw = () => draw.current()
    const move = (e: L.LeafletMouseEvent) => {
      const hit = on.current ? nearest(e.containerPoint) : null
      map.getContainer().style.cursor = hit ? 'pointer' : on.current ? '' : map.getContainer().style.cursor
      if (hit) {
        const v = hit.v
        tip.current.setLatLng([v.lat, v.lon]).setContent(`${v.name || 'Unnamed'} / ${v.sog ?? '?'} kn`)
        map.openTooltip(tip.current)
      } else map.closeTooltip(tip.current)
    }
    const click = (e: L.LeafletMouseEvent) => { const hit = on.current && nearest(e.containerPoint); if (hit) pick.current(hit.v.mmsi) }
    map.on('move zoom resize viewreset', redraw)
    map.on('mousemove', move)
    map.on('click', click)
    redraw()
    return () => {
      map.off('move zoom resize viewreset', redraw)
      map.off('mousemove', move)
      map.off('click', click)
      map.closeTooltip(tip.current)
      c.remove()
    }
  }, [map])

  useEffect(() => { draw.current() }, [vessels])
  return null
}

// A sweep line crossing the box, south to north, for as long as the search runs.
const Sweep: React.FC<{ box: BBox }> = ({ box }) => {
  const [t, setT] = useState(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    const t0 = performance.now()
    const tick = (now: number) => { setT(((now - t0) / 2200) % 1); raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
  const lat = box[1] + (box[3] - box[1]) * t
  return <Polyline positions={[[lat, box[0]], [lat, box[2]]]} pathOptions={{ color: '#44FF88', weight: 2, opacity: 0.9 }} />
}

const Viewport: React.FC<{ onBounds: (b: BBox) => void; focus: { lat: number; lon: number; zoom?: number } | null; fit: BBox | null }> = ({ onBounds, focus, fit }) => {
  const map = useMap()
  useMapEvents({ moveend: () => onBounds(toBox(map.getBounds())) })
  useEffect(() => { onBounds(toBox(map.getBounds())) }, [map, onBounds])
  useEffect(() => { if (focus) map.flyTo([focus.lat, focus.lon], focus.zoom ?? 11, { duration: 0.8 }) }, [focus, map])
  useEffect(() => { if (fit) map.flyToBounds(toBounds(fit), { padding: [40, 40], duration: 0.8 }) }, [fit, map])
  return null
}

export const MapComponent: React.FC<{
  live: LiveVessel[]
  drawing: boolean
  box: BBox | null
  onBox: (b: BBox) => void
  scanning: boolean
  result: SearchResult | null
  onBounds: (b: BBox) => void
  focus: { lat: number; lon: number; zoom?: number } | null
  fit: BBox | null
  onShip: (id: number) => void
  onPickVessel: (mmsi: string) => void
  picked: { lat: number; lon: number } | null
  track: [number, number][] | null
  mapStyle: MapStyle
  gfw: GfwLayers | null
}> = ({ live, drawing, box, onBox, scanning, result, onBounds, focus, fit, onShip, onPickVessel, picked, track, mapStyle, gfw }) => {
  const events = useDashboardStore((s) => s.getFilteredEvents())
  const selected = useDashboardStore((s) => s.selectedEvent)
  const showWeak = useDashboardStore((s) => s.showWeak)
  const setSelectedEvent = useDashboardStore((s) => s.setSelectedEvent)
  const valid = events.filter((e) => Number.isFinite(e.lat) && Number.isFinite(e.lon))

  return (
    <section className="relative h-full">
      <MapContainer center={[57.75, 10.9]} zoom={7} preferCanvas style={{ height: '100%', width: '100%', background: BASEMAPS[mapStyle].background }} className="z-0" zoomControl={false}>
        <ZoomControl position="bottomleft" />
        <TileLayer key={`${mapStyle}-base`} url={BASEMAPS[mapStyle].base}
          attribution="Tiles &copy; Esri, HERE, Garmin, OpenStreetMap contributors | AIS: aisstream.io, AISHub via Open Waters, hormuz.now, Global Fishing Watch" maxZoom={16} />
        <TileLayer key={`${mapStyle}-labels`} url={BASEMAPS[mapStyle].labels} maxZoom={16} />
        <Viewport onBounds={onBounds} focus={focus} fit={fit} />
        <DrawBox active={drawing} onBox={onBox} />

        <ShipCanvas vessels={live} onPick={onPickVessel} enabled={!drawing} />
        {track && track.length > 1 && (
          <>
            <Polyline positions={track} pathOptions={{ color: '#44FF88', weight: 2, opacity: 0.85, dashArray: '5 5' }} interactive={false} />
            <CircleMarker center={track[0]} radius={3} interactive={false} pathOptions={{ color: '#44FF88', weight: 1.5, fillColor: '#0A0A0A', fillOpacity: 1 }} />
          </>
        )}
        {picked && (
          <CircleMarker center={[picked.lat, picked.lon]} radius={9} interactive={false}
            pathOptions={{ color: '#44FF88', weight: 2, fill: false }} />
        )}

        {valid.map((e) => (
          <CircleMarker key={e.id} center={[e.lat, e.lon]} radius={selected?.id === e.id ? 9 : 6}
            pathOptions={{ color: '#0A0A0A', weight: 2, fillColor: STATUS[e.status]?.color ?? '#E8E8E8', fillOpacity: 1 }}
            eventHandlers={{ click: () => setSelectedEvent(e) }}>
            <Tooltip>Published candidate / {STATUS[e.status]?.label} / {Math.round(e.confidence * 100)}%</Tooltip>
          </CircleMarker>
        ))}

        {box && (
          <Rectangle bounds={toBounds(box)} pathOptions={{
            color: '#44FF88', weight: 1.5, dashArray: scanning ? undefined : '4 4',
            fillColor: '#44FF88', fillOpacity: scanning ? 0.08 : 0.04,
          }} />
        )}
        {box && scanning && <Sweep box={box} />}

        {gfw?.vessels.map((g) => (
          <CircleMarker key={`gv-${g.id}`} center={[g.lat, g.lon]} radius={4}
            pathOptions={{ color: '#0E9AA7', weight: 1.5, fill: false }}>
            <Tooltip>GFW AIS vessel, last seen {g.time.slice(5, 16).replace('T', ' ')} UTC ({gfw.delay_days} days ago)</Tooltip>
          </CircleMarker>
        ))}
        {gfw?.radar.map((r, i) => (
          <CircleMarker key={`gr-${i}`} center={[r.lat, r.lon]} radius={r.ais_matched ? 5 : 7}
            pathOptions={{ color: r.ais_matched ? '#8A8A8A' : '#D9782F', weight: r.ais_matched ? 1 : 2.5, fill: false, dashArray: r.ais_matched ? '2 3' : undefined }}>
            <Tooltip>GFW radar detection {gfw.day}: {r.ais_matched ? 'matched to AIS' : 'no AIS match'}</Tooltip>
          </CircleMarker>
        ))}

        {result?.ais_silent?.map((r) => (   // AIS went quiet here before the pass and came back there after
          <React.Fragment key={`silent-${r.key}`}>
            <Polyline positions={[[r.off.lat, r.off.lon], [r.on.lat, r.on.lon]]}
              pathOptions={{ color: SILENT, weight: 1.5, dashArray: '4 5', opacity: 0.8 }} />
            <CircleMarker center={[r.off.lat, r.off.lon]} radius={5} pathOptions={{ color: SILENT, weight: 2, fill: false }}>
              <Tooltip>{r.name ?? `MMSI ${r.mmsi ?? '?'}`}: AIS went silent here {r.off.hours_before} h before the pass</Tooltip>
            </CircleMarker>
            <CircleMarker center={[r.on.lat, r.on.lon]} radius={5} pathOptions={{ color: SILENT, weight: 2, fillColor: SILENT, fillOpacity: 0.9 }}>
              <Tooltip>{r.name ?? `MMSI ${r.mmsi ?? '?'}`}: AIS back on here {r.on.hours_after} h after the pass{r.could_be.length ? ` / could be radar ship ${r.could_be.map((i) => i + 1).join(', ')}` : ''}</Tooltip>
            </CircleMarker>
          </React.Fragment>
        ))}
        {result?.sts.map((s, i) => (
          <CircleMarker key={`sts-${i}`} center={[s.lat, s.lon]} radius={14}
            pathOptions={{ color: '#44FF88', weight: 1.5, dashArray: '3 3', fill: false }}>
            <Tooltip>Side-by-side pair / {s.spacing_m} m apart / {s.radar_hulls} hulls</Tooltip>
          </CircleMarker>
        ))}
        {result && [...result.ships].filter((s) => showWeak || !s.weak).reverse().map((s) => (  // unmatched first in the list; draw them last, on top
          <CircleMarker key={`ship-${s.id}`} center={[s.lat, s.lon]} radius={s.weak ? 4 : 6}
            pathOptions={{ color: '#0A0A0A', weight: 1.5, fillColor: SEARCH_COLORS[s.category] ?? '#E8E8E8', fillOpacity: s.weak ? 0.45 : 1, dashArray: s.weak ? '2 2' : undefined }}
            eventHandlers={{ click: () => onShip(s.id) }}>
            <Tooltip>Radar ship {s.id + 1} / ≈{s.length_m} m / {s.category.replace(/_/g, ' ').toLowerCase()}</Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </section>
  )
}

export default MapComponent
