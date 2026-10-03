import { describe, it, expect } from 'vitest'
import { transformFeatureToEvent, inferRegion } from './api'

describe('inferRegion', () => {
  it('correctly identifies Skagerrak', () => {
    expect(inferRegion(57.68, 10.61)).toBe('Skagerrak')
  })

  it('correctly identifies Gulf of Oman', () => {
    expect(inferRegion(25.0, 56.5)).toBe('Gulf of Oman')
  })

  it('correctly identifies Laconia Bay', () => {
    expect(inferRegion(36.5, 22.5)).toBe('Laconia Bay')
  })

  it('falls back to Coastal Europe for other coordinates', () => {
    expect(inferRegion(0, 0)).toBe('Coastal Europe')
  })
})

describe('transformFeatureToEvent', () => {
  it('transforms GeoJSON feature to STSEvent cleanly', () => {
    const feature = {
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [10.6096, 57.6837]
      },
      properties: {
        category: 'AIS_VISIBLE',
        conf: 0.95,
        length_m: 190.5,
        time: '2025-06-08 05:31:31',
        mmsis: ['211453610', '219017733'],
        gfw_encounter: true,
        duration_min: 120
      }
    }

    const event = transformFeatureToEvent(feature, 1)

    expect(event.id).toBe('1')
    expect(event.lat).toBeCloseTo(57.6837)
    expect(event.lon).toBeCloseTo(10.6096)
    expect(event.status).toBe('AIS_VISIBLE')
    expect(event.confidence).toBe(0.95)
    expect(event.distance).toBe(191)
    expect(event.duration).toBe(2.0)
    expect(event.vessel1_mmsi).toBe('211453610')
    expect(event.vessel2_mmsi).toBe('219017733')
    expect(event.gfw_match).toBe(true)
    expect(event.region).toBe('Skagerrak')
  })

  it('handles dark candidates with empty MMSIs', () => {
    const feature = {
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [56.5, 25.0]
      },
      properties: {
        category: 'AIS_UNMATCHED',
        conf: 0.88,
        length_m: 250,
        time: '2025-07-01T12:00:00Z',
        mmsis: [],
        gfw_encounter: false
      }
    }

    const event = transformFeatureToEvent(feature, 2)

    expect(event.status).toBe('AIS_UNMATCHED')
    expect(event.vessel2_mmsi).toBe('Dark Target')
    expect(event.region).toBe('Gulf of Oman')
    expect(event.gfw_match).toBe(false)
  })

  it('passes through an already constructed STSEvent', () => {
    const raw = {
      id: 'test-1',
      lat: 57.0,
      lon: 10.0,
      timestamp: '2025-01-01T00:00:00Z',
      vessel1: 'Ship A',
      vessel2: 'Ship B',
      distance: 100,
      duration: 1,
      status: 'AIS_VISIBLE' as const,
      confidence: 0.9,
      gfw_match: true,
      vessel1_mmsi: '111',
      vessel2_mmsi: '222',
      length_estimate: 150,
      region: 'Skagerrak'
    }

    const res = transformFeatureToEvent(raw)
    expect(res).toEqual(raw)
  })
})
