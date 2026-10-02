import React from 'react'
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useDashboardStore } from '../store/dashboardStore'

const ChartTooltip = (props: any) => {
  const { active, payload } = props
  if (active && payload && payload.length) {
    return (
      <div className="glass-effect rounded-lg p-2 border border-ocean-500/30">
        <p className="text-xs text-slate-200">{payload[0].name}</p>
        <p className="text-sm font-semibold text-ocean-300">{payload[0].value}</p>
      </div>
    )
  }
  return null
}

export const StatusChart: React.FC = () => {
  const events = useDashboardStore((s) => s.events)

  const data = [
    {
      name: 'AIS Visible',
      value: events.filter((e) => e.status === 'AIS_VISIBLE').length,
      fill: '#22c55e',
    },
    {
      name: 'Partial',
      value: events.filter((e) => e.status === 'AIS_PARTIAL').length,
      fill: '#eab308',
    },
    {
      name: 'Dark Candidates',
      value: events.filter((e) => e.status === 'AIS_UNMATCHED').length,
      fill: '#ef4444',
    },
  ]

  return (
    <div className="glass-effect card-shadow rounded-lg p-4">
      <h3 className="text-lg font-semibold mb-4">Status Distribution</h3>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
            outerRadius={80}
            fill="#0ea5e9"
            dataKey="value"
          >
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.fill} />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip />} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

export const ConfidenceChart: React.FC = () => {
  const events = useDashboardStore((s) => s.events)

  const data = [
    { range: '0-20%', count: events.filter((e) => e.confidence < 0.2).length },
    { range: '20-40%', count: events.filter((e) => e.confidence >= 0.2 && e.confidence < 0.4).length },
    { range: '40-60%', count: events.filter((e) => e.confidence >= 0.4 && e.confidence < 0.6).length },
    { range: '60-80%', count: events.filter((e) => e.confidence >= 0.6 && e.confidence < 0.8).length },
    { range: '80-100%', count: events.filter((e) => e.confidence >= 0.8).length },
  ]

  return (
    <div className="glass-effect card-shadow rounded-lg p-4">
      <h3 className="text-lg font-semibold mb-4">Confidence Distribution</h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="range" stroke="#64748b" />
          <YAxis stroke="#64748b" />
          <Tooltip content={<ChartTooltip />} />
          <Bar dataKey="count" fill="#0ea5e9" radius={[8, 8, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export const TimeSeriesChart: React.FC = () => {
  const events = useDashboardStore((s) => s.events)

  const data = Array.from({ length: 7 }, (_, i) => {
    const date = new Date()
    date.setDate(date.getDate() - (6 - i))
    const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    const count = events.filter((e) => {
      const eventDate = new Date(e.timestamp).toLocaleDateString()
      const checkDate = date.toLocaleDateString()
      return eventDate === checkDate
    }).length
    return { date: dateStr, count }
  })

  return (
    <div className="glass-effect card-shadow rounded-lg p-4">
      <h3 className="text-lg font-semibold mb-4">Detection Trend (7 Days)</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" stroke="#64748b" />
          <YAxis stroke="#64748b" />
          <Tooltip content={<ChartTooltip />} />
          <Line
            type="monotone"
            dataKey="count"
            stroke="#0ea5e9"
            dot={{ fill: '#0ea5e9', r: 4 }}
            activeDot={{ r: 6 }}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
