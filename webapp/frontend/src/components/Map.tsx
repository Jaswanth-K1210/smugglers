import React from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS, STATUS_ORDER } from '../status'

const MapComponent: React.FC = () => {
  const events = useDashboardStore((s) => s.getFilteredEvents())
  const selected = useDashboardStore((s) => s.selectedEvent)
  const setSelectedEvent = useDashboardStore((s) => s.setSelectedEvent)
  const valid = events.filter((e) => Number.isFinite(e.lat) && Number.isFinite(e.lon))
  const center: [number, number] = valid.length ? [valid[0].lat, valid[0].lon] : [57.75, 10.9]

  return (
    <section className="panel relative overflow-hidden">
      <MapContainer center={center} zoom={7} style={{ height: 480, width: '100%' }} className="z-0">
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          attribution="Tiles &copy; Esri, HERE, Garmin, OpenStreetMap contributors"
          maxZoom={13}
        />
        {valid.map((e) => (
          <CircleMarker
            key={e.id}
            center={[e.lat, e.lon]}
            radius={selected?.id === e.id ? 10 : 7}
            pathOptions={{ color: '#070B0A', weight: 2, fillColor: STATUS[e.status]?.color ?? '#D3E2DA', fillOpacity: 1 }}
            eventHandlers={{ click: () => setSelectedEvent(e) }}
          >
            <Tooltip>{STATUS[e.status]?.label}, {Math.round(e.confidence * 100)}% confidence</Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
      <ul className="absolute bottom-3 left-3 z-[400] space-y-1 rounded-md border border-rule bg-surface/95 px-3 py-2 font-mono text-xs">
        {STATUS_ORDER.map((k) => (
          <li key={k} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS[k].color }} />{STATUS[k].label}
          </li>
        ))}
      </ul>
    </section>
  )
}

export default MapComponent
