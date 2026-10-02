import React, { useEffect, useState } from 'react'
import { apiService } from '../services/api'
import { LoadingSpinner } from './Loading'
import { AlertCircle } from 'lucide-react'

interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy'
  eventCount: number
  liveDetectionAvailable: boolean
}

export const HealthCheck: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const data = await apiService.getHealth()
        setHealth(data)
      } catch (error) {
        console.error('Health check failed:', error)
        setHealth({
          status: 'unhealthy',
          eventCount: 0,
          liveDetectionAvailable: false
        })
      } finally {
        setLoading(false)
      }
    }

    checkHealth()
    const interval = setInterval(checkHealth, 60000)
    return () => clearInterval(interval)
  }, [])

  if (loading) return <LoadingSpinner size="sm" />

  const statusColors = {
    healthy: 'bg-green-500/20 text-green-300 border-green-500/30',
    degraded: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
    unhealthy: 'bg-red-500/20 text-red-300 border-red-500/30'
  }

  return (
    <div className={`p-3 rounded-lg border ${statusColors[health?.status || 'unhealthy']} text-sm`}>
      <div className="flex items-center gap-2">
        {health?.status === 'unhealthy' && <AlertCircle className="w-4 h-4" />}
        <span className="font-medium">
          {health?.status === 'healthy' && '✓ System Operational'}
          {health?.status === 'degraded' && '⚠ Degraded Performance'}
          {health?.status === 'unhealthy' && '✗ Service Unavailable'}
        </span>
      </div>
      <p className="text-xs mt-1 opacity-75">
        {health?.eventCount} events • Live detection {health?.liveDetectionAvailable ? 'enabled' : 'disabled'}
      </p>
    </div>
  )
}
