import { describe, it, expect, beforeEach } from 'vitest'
import { useDashboardStore, STSEvent } from './dashboardStore'

const mockEvents: STSEvent[] = [
  {
    id: '1',
    lat: 57.6,
    lon: 10.6,
    timestamp: '2025-06-08T05:31:31Z',
    vessel1: '211453610',
    vessel2: '219017733',
    distance: 190,
    duration: 2.0,
    status: 'AIS_VISIBLE',
    confidence: 0.95,
    gfw_match: true,
    vessel1_mmsi: '211453610',
    vessel2_mmsi: '219017733',
    length_estimate: 190,
    region: 'Skagerrak'
  },
  {
    id: '2',
    lat: 25.1,
    lon: 56.4,
    timestamp: '2025-07-01T10:00:00Z',
    vessel1: 'Unknown',
    vessel2: 'Dark Target',
    distance: 300,
    duration: 1.5,
    status: 'AIS_UNMATCHED',
    confidence: 0.70,
    gfw_match: false,
    vessel1_mmsi: 'Unknown',
    vessel2_mmsi: 'Dark Target',
    length_estimate: 250,
    region: 'Gulf of Oman'
  }
]

describe('useDashboardStore', () => {
  beforeEach(() => {
    useDashboardStore.setState({
      events: [],
      selectedEvent: null,
      filter: {
        status: 'all',
        minConfidence: 0.0,
        dateRange: ['', ''],
        region: 'all'
      },
      loading: false,
      error: null
    })
  })

  it('stores events and handles selected event', () => {
    useDashboardStore.getState().setEvents(mockEvents)
    expect(useDashboardStore.getState().events).toHaveLength(2)

    useDashboardStore.getState().setSelectedEvent(mockEvents[0])
    expect(useDashboardStore.getState().selectedEvent?.id).toBe('1')
  })

  it('filters by status correctly', () => {
    useDashboardStore.getState().setEvents(mockEvents)
    useDashboardStore.getState().setFilter({ status: 'AIS_UNMATCHED' })

    const filtered = useDashboardStore.getState().getFilteredEvents()
    expect(filtered).toHaveLength(1)
    expect(filtered[0].id).toBe('2')
  })

  it('filters by region correctly', () => {
    useDashboardStore.getState().setEvents(mockEvents)
    useDashboardStore.getState().setFilter({ region: 'Skagerrak' })

    const filtered = useDashboardStore.getState().getFilteredEvents()
    expect(filtered).toHaveLength(1)
    expect(filtered[0].id).toBe('1')
  })

  it('filters by minConfidence correctly', () => {
    useDashboardStore.getState().setEvents(mockEvents)
    useDashboardStore.getState().setFilter({ minConfidence: 0.8 })

    const filtered = useDashboardStore.getState().getFilteredEvents()
    expect(filtered).toHaveLength(1)
    expect(filtered[0].id).toBe('1')
  })

  it('safely handles non-array input to setEvents', () => {
    // @ts-expect-error test invalid input
    useDashboardStore.getState().setEvents({ type: 'FeatureCollection' })
    expect(useDashboardStore.getState().events).toEqual([])
    expect(useDashboardStore.getState().getFilteredEvents()).toEqual([])
  })
})
