import React from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { useDashboardStore } from '../store/dashboardStore'
import { Panel } from './Panel'

const Tip = ({ active, payload, label }: any) =>
  active && payload?.length ? (
    <div className="border border-rule bg-paper px-2.5 py-1.5 text-xs">
      <p className="text-ink-2">{label}</p>
      <p className="font-medium text-ink">{payload[0].value} candidates</p>
    </div>
  ) : null

const Histogram: React.FC<{ title: string; data: { x: string; n: number }[] }> = ({ title, data }) => (
  <Panel title={title} count={data.reduce((n, d) => n + d.n, 0)}>
    <ResponsiveContainer width="100%" height={170}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="#1F1F1F" />
        <XAxis dataKey="x" tickLine={false} axisLine={{ stroke: '#2A2A2A' }} tick={{ fill: '#A3A3A3', fontSize: 10, fontFamily: 'JetBrains Mono' }} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: '#A3A3A3', fontSize: 10, fontFamily: 'JetBrains Mono' }} />
        <Tooltip content={<Tip />} cursor={{ fill: '#1E1E1E' }} />
        <Bar dataKey="n" fill="#1C93CF" radius={[4, 4, 0, 0]} maxBarSize={36} />
      </BarChart>
    </ResponsiveContainer>
  </Panel>
)

export const ConfidenceChart: React.FC = () => {
  const events = useDashboardStore((s) => s.events)
  const data = ['0–20', '20–40', '40–60', '60–80', '80–100'].map((x, i) => ({
    x: `${x}%`,
    n: events.filter((e) => Math.min(Math.floor((e.confidence ?? 0) * 5), 4) === i).length,
  }))
  return <Histogram title="Confidence" data={data} />
}

export const TimeSeriesChart: React.FC = () => {
  const events = useDashboardStore((s) => s.events)
  const data = React.useMemo(() => {
    const byDay = new Map<string, number>()
    for (const e of [...events].sort((a, b) => a.timestamp.localeCompare(b.timestamp))) {
      const d = new Date(e.timestamp)
      if (isNaN(d.getTime())) continue
      const key = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
      byDay.set(key, (byDay.get(key) || 0) + 1)
    }
    return Array.from(byDay, ([x, n]) => ({ x, n })).slice(-14)
  }, [events])
  return <Histogram title="Candidates by image date" data={data} />
}
