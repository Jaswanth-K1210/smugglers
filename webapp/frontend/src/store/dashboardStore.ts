import { create } from 'zustand'

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

export interface UserProfile {
  name: string
  email: string
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
  searchQuery: string
  user: UserProfile | null
  loading: boolean
  error: string | null

  setEvents: (events: STSEvent[]) => void
  setSelectedEvent: (event: STSEvent | null) => void
  setFilter: (filter: Partial<DashboardStore['filter']>) => void
  setSearchQuery: (query: string) => void
  login: (user: UserProfile, token: string) => void
  logout: () => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  getFilteredEvents: () => STSEvent[]
}

export const getToken = (): string | null => {
  try {
    return localStorage.getItem('sts_token')
  } catch {
    return null
  }
}

const getStoredUser = (): UserProfile | null => {
  try {
    const raw = localStorage.getItem('sts_user')
    return raw && getToken() ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useDashboardStore = create<DashboardStore>((set, get) => ({
  events: [],
  selectedEvent: null,
  filter: {
    status: 'all',
    minConfidence: 0.0,
    dateRange: ['', ''],
    region: 'all'
  },
  searchQuery: '',
  user: getStoredUser(),
  loading: false,
  error: null,

  setEvents: (events) => set({ events: Array.isArray(events) ? events : [] }),
  setSelectedEvent: (event) => set({ selectedEvent: event }),

  setFilter: (filter) => set((state) => ({
    filter: { ...state.filter, ...filter }
  })),

  setSearchQuery: (searchQuery) => set({ searchQuery }),
  login: (user, token) => {
    try {
      localStorage.setItem('sts_user', JSON.stringify(user))
      localStorage.setItem('sts_token', token)
    } catch {
      // private mode: session lasts until reload
    }
    set({ user })
  },

  logout: () => {
    try {
      localStorage.removeItem('sts_user')
      localStorage.removeItem('sts_token')
    } catch {
      // ignore
    }
    set({ user: null, events: [] })
  },

  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  getFilteredEvents: () => {
    const state = get()
    if (!Array.isArray(state.events)) return []
    const q = (state.searchQuery || '').trim().toLowerCase()

    return state.events.filter(event => {
      const statusMatch = !state.filter.status || state.filter.status === 'all' || event.status === state.filter.status
      const confidenceMatch = (event.confidence ?? 0) >= (state.filter.minConfidence ?? 0)
      const regionMatch = !state.filter.region || state.filter.region === 'all' || event.region === state.filter.region

      if (!statusMatch || !confidenceMatch || !regionMatch) return false

      if (!q) return true

      const idMatch = event.id.toLowerCase().includes(q)
      const v1Match = (event.vessel1 || '').toLowerCase().includes(q)
      const v2Match = (event.vessel2 || '').toLowerCase().includes(q)
      const mmsi1Match = (event.vessel1_mmsi || '').toLowerCase().includes(q)
      const mmsi2Match = (event.vessel2_mmsi || '').toLowerCase().includes(q)
      const regMatch = (event.region || '').toLowerCase().includes(q)
      const coordsMatch = `${event.lat.toFixed(2)},${event.lon.toFixed(2)}`.includes(q)

      return idMatch || v1Match || v2Match || mmsi1Match || mmsi2Match || regMatch || coordsMatch
    })
  }
}))
