import React from 'react'
import { TrendingUp } from 'lucide-react'
import clsx from 'clsx'

interface StatsCardProps {
  title: string
  value: string | number
  change?: number
  icon?: React.ReactNode
  trend?: 'up' | 'down' | 'neutral'
  className?: string
}

export const StatsCard: React.FC<StatsCardProps> = ({
  title,
  value,
  change,
  icon,
  trend = 'neutral',
  className
}) => {
  return (
    <div className={clsx(
      "glass-effect card-shadow rounded-lg p-4 transition-all hover:border-ocean-400/40",
      className
    )}>
      <div className="flex items-start justify-between mb-2">
        <p className="text-slate-400 text-sm font-medium">{title}</p>
        {icon && (
          <div className="p-2 bg-ocean-600/20 rounded-lg">
            {icon}
          </div>
        )}
      </div>

      <div className="flex items-baseline gap-2">
        <h3 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-ocean-400 to-ocean-300">
          {value}
        </h3>
        {change !== undefined && (
          <span className={clsx(
            'text-xs font-semibold flex items-center gap-0.5',
            trend === 'up' ? 'text-green-400' : trend === 'down' ? 'text-red-400' : 'text-slate-400'
          )}>
            {change > 0 ? '+' : ''}{change}%
            {trend === 'up' && <TrendingUp className="w-3 h-3" />}
          </span>
        )}
      </div>
    </div>
  )
}
