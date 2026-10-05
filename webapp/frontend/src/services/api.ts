import axios from 'axios'
import { STSEvent, UserProfile, getToken, useDashboardStore } from '../store/dashboardStore'

// Same origin by default; on Vercel, VITE_API_URL points at the Render backend
// (e.g. https://smugglers.onrender.com/api).
const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, '') || '/api'

const api = axios.create({
  baseURL: API_URL,
  timeout: 30000,                      // Render's free tier can take ~30 s to wake up
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

export type BBox = [number, number, number, number] // west, south, east, north

export interface LiveVessel {
  mmsi: string
  name: string | null
  lat: number
  lon: number
  sog: number | null
  cog: number | null
  heading: number | null
  age_s: number
  group?: string
  len?: number | null
  source?: string
}

export interface VesselDetail extends Partial<LiveVessel> {
  mmsi: string
  type: string | null
  type_code?: number | null
  imo?: number | null
  callsign?: string | null
  length_m?: number | null
  beam_m?: number | null
  draught_m?: number | null
  destination?: string | null
  nav_status?: string | null
  eta?: string | null
  flag?: { iso2: string; country: string } | null
  track?: [number, number][]
  track_since_s?: number
  dwt?: number | null
  source?: string
}

export interface VesselIdentity {
  type: string | null
  imo: number | null
  callsign: string | null
  length_m: number | null
  tonnage_gt: number | null
  source: string
}

export interface StraitCrossing {
  name: string | null
  category: string | null
  flag: string | null
  dwt: number | null
  length_m: number | null
  direction: 'inbound' | 'outbound' | string
  at: string
  unobserved_h: number | null
  destination: string | null
}

export interface Particulars {
  fields: Partial<Record<'ship_type' | 'builder' | 'year_built' | 'gross_tonnage' | 'deadweight' | 'registry' | 'home_port', string | number>>
  first_seen?: string | null
  source: string
}

export interface ShipPhoto {
  url: string
  page: string | null
  author: string | null
  license: string | null
  source: string
}

export interface LiveFeed {
  configured: boolean
  connected: boolean
  error: string | null
  in_view: number
  vessels: LiveVessel[]
}

export interface NewsItem {
  title: string
  link: string
  source: string | null
  published: string | null
}

export interface AisCandidate {
  id: string
  name: string | null
  source: string | null
  distance_m: number
  minutes_from_pass: number
  speed_needed_kn: number
  ais_length_m: number | null
  size: 'consistent' | 'mismatch' | null
  plausible: boolean
}

export interface Coverage { score: number; label: 'good' | 'fair' | 'poor' | 'none'; factors: string[] }

export interface GfwLayers {
  day: string | null
  delay_days: number | null
  source: string
  vessels: { id: string; lat: number; lon: number; time: string }[]
  radar: { lat: number; lon: number; ais_matched: boolean; detections: number }[]
}

export interface SearchShip {
  id: number
  lat: number
  lon: number
  length_m: number
  beam_m: number | null
  conf: number
  category: string
  n_ais: number
  reasons: string[]
  chip_png: string | null
  ais_candidates?: AisCandidate[]
  coverage?: string
  weak?: boolean            // detector score below the ship threshold (0.25); hidden by default
  recurring_passes?: number // period search: AIS-unmatched at this spot on this many passes
}

export interface SearchResult {
  scene: { id: string; time: string; platform?: string }
  bbox: BBox
  scene_note?: string | null
  cached: boolean
  ships: SearchShip[]
  sts: { lat: number; lon: number; tier: string; spacing_m: number; radar_hulls: number; ais_identities: number | null; without_ais: number | null }[]
  counts: { ships: number; ais_unmatched: number; sts_pairs: number; sts_pairs_with_silent_hull: number;
            weak_candidates?: number; weak_ais_unmatched?: number }
  thresholds?: { ship: number; weak: number }
  coverage?: Coverage
  ais_source?: string
  ais_available?: boolean | null
  note: string
}

/** A pass of a period search that failed: shown in the timeline with its reason. */
export interface FailedPass { scene: { id: string; time: string }; error: string }
export type PassResult = SearchResult | FailedPass
export const isFailedPass = (p: PassResult): p is FailedPass => 'error' in p

/** Result of a time-period search (Render + Modal worker): one entry per Sentinel-1 pass. */
export interface PeriodResult {
  passes: PassResult[]
  passes_found: number
  passes_searched: number
  passes_failed: number
  recurring: { lat: number; lon: number; passes: number; times: string[] }[]
  counts: { ships: number; ais_unmatched: number; ais_unmatched_spots: number; weak_candidates: number; sts_pairs: number }
  note: string | null
  bbox?: BBox
  period?: [string, string]
}

/** Passes of any result, newest first: a single-pass search is a one-pass list. */
export const passesOf = (r: SearchResult | PeriodResult | null | undefined): PassResult[] =>
  !r ? [] : 'passes' in r ? r.passes : [r]

export interface SearchJob {
  job_id: string
  status: 'queued' | 'running' | 'done' | 'error'
  stage?: string
  progress: number
  queue_position?: number
  error?: string
  result?: SearchResult | PeriodResult
  stages?: string[]                 // period search: one line per pass
  passes?: number
  passes_found?: number | null
  period?: [string, string]
}

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

  async getLive(bbox?: BBox): Promise<LiveFeed> {
    // A zoomed-out map reports longitudes past ±180; the server wants real coordinates.
    const box = bbox && [Math.max(bbox[0], -180), Math.max(bbox[1], -90), Math.min(bbox[2], 180), Math.min(bbox[3], 90)]
    return (await api.get('/live', { params: box ? { bbox: box.map((v) => v.toFixed(4)).join(',') } : {} })).data
  },

  async searchShips(q: string): Promise<{ mmsi: string; name: string | null; lat: number; lon: number; source: string }[]> {
    return (await api.get('/live/search', { params: { q } })).data.ships
  },

  async getVessel(mmsi: string): Promise<VesselDetail> {
    return (await api.get(`/live/${mmsi}`)).data
  },

  async getVesselExtra(mmsi: string): Promise<{ identity: VesselIdentity | null; photo: ShipPhoto | null; track?: [number, number][]; particulars?: Particulars | null }> {
    return (await api.get(`/live/${mmsi}/extra`, { timeout: 45000 })).data
  },

  async getGfwLayers(bbox: BBox): Promise<GfwLayers> {
    return (await api.get('/gfw/layers', { params: { bbox: bbox.map((v) => v.toFixed(2)).join(',') }, timeout: 120000 })).data
  },

  async getStraitCrossings(hours = 48): Promise<{ hours: number; crossings: StraitCrossing[]; source: string }> {
    return (await api.get('/strait/crossings', { params: { hours }, timeout: 30000 })).data
  },

  async getNews(region = 'all'): Promise<{ items: NewsItem[]; error: string | null }> {
    return (await api.get('/news', { params: { region }, timeout: 15000 })).data
  },

  async startSearch(bbox: BBox, start?: string, end?: string): Promise<{ job_id: string; queue_position: number; period?: [string, string] }> {
    // generous timeout: both the backend and the worker may be waking from sleep
    return (await api.post('/search', { bbox, ...(start && end ? { start, end } : {}) }, { timeout: 120000 })).data
  },

  async getSearch(jobId: string): Promise<SearchJob> {
    return (await api.get(`/search/${jobId}`)).data
  },

  async register(details: { name: string; email: string; password: string }): Promise<Session> {
    return (await api.post('/auth/register', details)).data
  },
}
