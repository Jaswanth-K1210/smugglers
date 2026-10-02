import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

export interface ApiResponse<T> {
  data: T
  status: number
  message?: string
}

export const apiService = {
  async getHealth() {
    const response = await api.get('/health')
    return response.data
  },

  async getEvents(filters?: Record<string, any>) {
    const response = await api.get('/events', { params: filters })
    return response.data
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
    return response.data
  }
}
