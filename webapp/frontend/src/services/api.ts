import axios from 'axios'
import { STSEvent, UserProfile, getToken, useDashboardStore } from '../store/dashboardStore'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(undefined, (error) => {
  if (error.response?.status === 401 && getToken()) useDashboardStore.getState().logout()
  // Surface the server's own sentence ("Email or password is incorrect.") instead of axios's.
  const detail = error.response?.data?.detail
  return Promise.reject(typeof detail === 'string' ? new Error(detail) : error)
})

export interface Session {
  token: string
  user: UserProfile
}

export interface ApiResponse<T> {
  data: T
  status: number
  message?: string
}

export function inferRegion(lat: number, lon: number): string {
  if (lat >= 55 && lat <= 60 && lon >= 8 && lon <= 13) return 'Skagerrak'
  if (lat >= 22 && lat <= 27 && lon >= 55 && lon <= 61) return 'Gulf of Oman'
  if (lat >= 35 && lat <= 38 && lon >= 21 && lon <= 24) return 'Laconia Bay'
  return 'Coastal Europe'
}

export function transformFeatureToEvent(feat: any, index: number = 0): STSEvent {
  if (!feat) {
    return {
      id: String(index),
      lat: 0,
      lon: 0,
      timestamp: new Date().toISOString(),
      vessel1: 'Unknown',
      vessel2: 'Unknown',
      distance: 0,
      duration: 0,
      status: 'AIS_UNMATCHED',
      confidence: 0,
      gfw_match: false,
      vessel1_mmsi: 'Unknown',
      vessel2_mmsi: 'Unknown',
      length_estimate: 0,
      region: 'Unknown',
    }
  }

  if (typeof feat.lat === 'number' && typeof feat.lon === 'number' && feat.status) {
    return feat as STSEvent
  }

  const p = feat.properties || {}
  const coords = feat.geometry?.coordinates || [0, 0]
  const lon = Number(coords[0] ?? p.lon ?? 0)
  const lat = Number(coords[1] ?? p.lat ?? 0)
  let mmsis: any[] = []
  if (Array.isArray(p.mmsis)) {
    mmsis = p.mmsis
  } else if (typeof p.mmsis === 'string') {
    try {
      mmsis = JSON.parse(p.mmsis)
    } catch {
      mmsis = []
    }
  }

  let timestamp = p.time || p.timestamp || new Date().toISOString()
  if (typeof timestamp === 'string' && timestamp.includes(' ') && !timestamp.includes('T')) {
    timestamp = timestamp.replace(' ', 'T') + 'Z'
  }

  const v1 = mmsis[0] ? String(mmsis[0]) : (p.registry_name || 'Vessel 1')
  const v2 = mmsis[1] ? String(mmsis[1]) : (p.category === 'AIS_UNMATCHED' ? 'Dark Target' : 'Unidentified')

  return {
    id: String(p.id ?? feat.id ?? index),
    lat,
    lon,
    timestamp,
    vessel1: v1,
    vessel2: v2,
    distance: Math.round(Number(p.distance ?? p.length_m ?? 0)),
    duration: p.duration_min != null ? Math.round((Number(p.duration_min) / 60) * 10) / 10 : Number(p.duration ?? 0),
    status: (p.category ?? p.status ?? 'AIS_UNMATCHED') as STSEvent['status'],
    confidence: Number(p.conf ?? p.confidence ?? 0),
    gfw_match: Boolean(p.gfw_encounter || p.gfw_match),
    vessel1_mmsi: mmsis[0] ? String(mmsis[0]) : (p.vessel1_mmsi || 'Unknown'),
    vessel2_mmsi: mmsis[1] ? String(mmsis[1]) : (p.vessel2_mmsi || (p.category === 'AIS_UNMATCHED' ? 'Dark Target' : 'Unknown')),
    length_estimate: Math.round(Number(p.length_m ?? p.length_estimate ?? 0)),
    region: p.region || inferRegion(lat, lon),
  }
}

export const apiService = {
  async getHealth() {
    const response = await api.get('/health')
    const raw = response.data
    return {
      ...raw,
      status: (raw?.status === 'ok' || raw?.status === 'healthy') ? 'healthy' : (raw?.status === 'degraded' ? 'degraded' : 'unhealthy'),
      eventCount: raw?.eventCount ?? raw?.events ?? 0,
      liveDetectionAvailable: Boolean(raw?.liveDetectionAvailable ?? raw?.live_detection),
    }
  },

  async getEvents(filters?: Record<string, any>): Promise<STSEvent[]> {
    const response = await api.get('/events', { params: filters })
    const data = response.data
    if (data && data.type === 'FeatureCollection' && Array.isArray(data.features)) {
      return data.features.map((feat: any, idx: number) => transformFeatureToEvent(feat, idx))
    }
    if (Array.isArray(data)) {
      return data.map((item: any, idx: number) => transformFeatureToEvent(item, idx))
    }
    return []
  },

  async getSummary() {
    const response = await api.get('/summary')
    return response.data
  },

  async detectShip(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/detect', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return response.data
  },

  async getEventDetails(eventId: string) {
    const response = await api.get(`/events/${eventId}`)
    const data = response.data
    if (data?.event) return data.event
    if (data?.feature) return transformFeatureToEvent(data.feature, Number(eventId) || 0)
    if (data?.properties) return transformFeatureToEvent(data, Number(eventId) || 0)
    return data
  },

  async login(credentials: { email: string; password: string }): Promise<Session> {
    return (await api.post('/auth/login', credentials)).data
  },

  async register(details: { name: string; email: string; password: string }): Promise<Session> {
    return (await api.post('/auth/register', details)).data
  },
}
