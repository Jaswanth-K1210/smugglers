import React, { useEffect, useState } from 'react'
import { formatDistanceToNow } from 'date-fns'
import { apiService, NewsItem } from '../services/api'
import { Panel } from './Panel'

const REGIONS = [['all', 'All'], ['skagerrak', 'Skagerrak'], ['gulf-of-oman', 'Gulf of Oman'], ['laconia', 'Laconia']] as const

export const News: React.FC<{ className?: string }> = ({ className }) => {
  const [region, setRegion] = useState<string>('all')
  const [items, setItems] = useState<NewsItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setItems(null)
    apiService.getNews(region)
      .then((d) => { setItems(d.items); setError(d.error) })
      .catch(() => { setItems([]); setError('News is unavailable right now.') })
  }, [region])

  return (
    <Panel
      title="Sanctions and STS news"
      count={items?.length}
      className={className}
      bodyClassName="flex flex-col"
      right={<span className="text-[10px] text-ink-3">last 30 days</span>}
    >
      <div className="flex gap-1 border-b border-rule px-3 py-2" role="tablist" aria-label="News region">
        {REGIONS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={region === id} onClick={() => setRegion(id)}
            className={region === id ? 'pill-live' : 'pill text-ink-2 hover:border-[#444]'}>{label}</button>
        ))}
      </div>
      <ul className="max-h-80 flex-1 overflow-y-auto">
        {items === null && <li className="px-3 py-3 text-xs text-ink-3">Loading headlines…</li>}
        {items?.length === 0 && <li className="px-3 py-3 text-xs text-ink-2">{error || 'No stories in the last 30 days.'}</li>}
        {items?.map((n) => (
          <li key={n.link} className="border-b border-rule last:border-b-0">
            <a href={n.link} target="_blank" rel="noreferrer" className="block px-3 py-2.5 hover:bg-white/[0.03]">
              <p className="font-sans text-[13px] leading-snug text-ink">{n.title}</p>
              <p className="mt-1 text-[10px] uppercase tracking-wider text-ink-3">
                {n.source || 'Unknown source'}
                {n.published && ` / ${formatDistanceToNow(new Date(n.published), { addSuffix: true })}`}
              </p>
            </a>
          </li>
        ))}
      </ul>
    </Panel>
  )
}
