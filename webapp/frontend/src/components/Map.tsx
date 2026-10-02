import React, { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import L from 'leaflet'
import { useDashboardStore, STSEvent } from '../store/dashboardStore'

const MapComponent: React.FC = () => {
  const events = useDashboardStore((s) => s.getFilteredEvents())
  const selectedEvent = useDashboardStore((s) => s.selectedEvent)

  const getColor = (status: string) => {
    switch (status) {
      case 'AIS_VISIBLE':
        return '#22c55e'
      case 'AIS_PARTIAL':
        return '#eab308'
      case 'AIS_UNMATCHED':
        return '#ef4444'
      default:
        return '#0ea5e9'
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'AIS_VISIBLE':
        return 'AIS Visible'
      case 'AIS_PARTIAL':
        return 'Partially Visible'
      case 'AIS_UNMATCHED':
        return 'Dark Candidate'
      default:
        return status
    }
  }

  const defaultCenter: [number, number] = [57.75, 10.9]

  return (
    <div className="glass-effect card-shadow rounded-lg overflow-hidden h-full min-h-[600px]">
      <MapContainer
        center={defaultCenter}
        zoom={6}
        style={{ height: '100%', width: '100%' }}
        className="z-0"
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png"
          attribution='&copy; OpenStreetMap contributors'
        />

        {events.map((event) => (
          <CircleMarker
            key={event.id}
            center={[event.lat, event.lon]}
            radius={selectedEvent?.id === event.id ? 12 : 8}
            fillColor={getColor(event.status)}
            color={getColor(event.status)}
            weight={selectedEvent?.id === event.id ? 3 : 2}
            opacity={1}
            fillOpacity={0.8}
            className="transition-all"
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold mb-1">{getStatusLabel(event.status)}</p>
                <p className="text-xs text-gray-600">
                  {new Date(event.timestamp).toLocaleDateString()}
                </p>
                <p className="text-xs text-gray-600">
                  Distance: {event.distance}m
                </p>
                <p className="text-xs text-gray-600">
                  Confidence: {(event.confidence * 100).toFixed(1)}%
                </p>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}

export default MapComponent
