import create from 'zustand'

export interface STSEvent {
  id: string
  lat: number
  lon: number
  timestamp: string
  vessel1: string
  vessel2: string
  distance: number
  duration: number
  status: 'AIS_VISIBLE' | 'AIS_PARTIAL' | 'AIS_UNMATCHED'
  confidence: number
  gfw_match: boolean
  vessel1_mmsi: string
  vessel2_mmsi: string
  length_estimate: number
  region: string
}

interface DashboardStore {
  events: STSEvent[]
  selectedEvent: STSEvent | null
  filter: {
    status: string
    minConfidence: number
    dateRange: [string, string]
    region: string
  }
  loading: boolean
  error: string | null

  setEvents: (events: STSEvent[]) => void
  setSelectedEvent: (event: STSEvent | null) => void
  setFilter: (filter: Partial<DashboardStore['filter']>) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  getFilteredEvents: () => STSEvent[]
}

export const useDashboardStore = create<DashboardStore>((set, get) => ({
  events: [],
  selectedEvent: null,
  filter: {
    status: 'all',
    minConfidence: 0.5,
    dateRange: ['', ''],
    region: 'all'
  },
  loading: false,
  error: null,

  setEvents: (events) => set({ events }),
  setSelectedEvent: (event) => set({ selectedEvent: event }),

  setFilter: (filter) => set((state) => ({
    filter: { ...state.filter, ...filter }
  })),

  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  getFilteredEvents: () => {
    const state = get()
    return state.events.filter(event => {
      const statusMatch = state.filter.status === 'all' || event.status === state.filter.status
      const confidenceMatch = event.confidence >= state.filter.minConfidence
      const regionMatch = state.filter.region === 'all' || event.region === state.filter.region

      return statusMatch && confidenceMatch && regionMatch
    })
  }
}))
