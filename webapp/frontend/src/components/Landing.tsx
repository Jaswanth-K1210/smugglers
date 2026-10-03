import React, { useEffect, useState } from 'react'
import { apiService } from '../services/api'
import { useDashboardStore } from '../store/dashboardStore'
import { STATUS, STATUS_ORDER } from '../status'

export const useUtcClock = () => {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return now.toISOString().slice(11, 19) + 'Z'
}

// Two short parallel hulls: the configuration the whole project looks for.
export const Wordmark: React.FC = () => (
  <a href="#/" className="flex items-center gap-2.5 text-ink">
    <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
      <rect x="4" y="3" width="5" height="16" rx="1" fill="#3BF08A" />
      <rect x="12" y="5" width="5" height="14" rx="1" fill="#D3E2DA" />
    </svg>
    <span className="font-mono text-sm font-bold uppercase tracking-[0.25em]">Open STS</span>
  </a>
)

export const SiteHeader: React.FC = () => {
  const user = useDashboardStore((s) => s.user)
  const clock = useUtcClock()
  return (
    <header className="border-b border-rule bg-paper/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Wordmark />
          <span className="hidden font-mono text-xs text-ink-2 md:block">{clock}</span>
        </div>
        <nav className="flex items-center gap-1 font-mono text-xs uppercase tracking-wider sm:gap-3">
          <a href="#method" className="hidden px-2 py-1 text-ink-2 hover:text-signal sm:block">Method</a>
          <a href="#categories" className="hidden px-2 py-1 text-ink-2 hover:text-signal sm:block">Categories</a>
          {user ? (
            <a href="#/console" className="btn-primary">Enter console</a>
          ) : (
            <>
              <a href="#/login" className="px-2 py-1 text-ink hover:text-signal">Sign in</a>
              <a href="#/register" className="btn-primary">Create account</a>
            </>
          )}
        </nav>
      </div>
    </header>
  )
}

const Reticle: React.FC<{ x: number; y: number; id: string }> = ({ x, y, id }) => (
  <g stroke="#3BF08A" strokeWidth="2" fill="none">
    <circle cx={x} cy={y} r="46" />
    <path d={`M${x - 70} ${y}h18M${x + 52} ${y}h18M${x} ${y - 70}v18M${x} ${y + 52}v18`} />
    <text x={x - 168} y={y + 8} fill="#3BF08A" stroke="none" fontFamily="'JetBrains Mono', monospace" fontSize="22">{id}</text>
  </g>
)

const SarFigure: React.FC = () => (
  <figure className="panel p-3">
    <div className="mb-3 flex justify-between font-mono text-[11px] uppercase tracking-wider text-ink-2">
      <span>Sensor <span className="text-ink">S1C IW GRD</span></span>
      <span>Pol <span className="text-ink">VV</span></span>
      <span>Acq <span className="text-ink">2025-06</span></span>
    </div>
    <div className="scanlines relative overflow-hidden bg-black">
      <img
        src="/sar-pair.jpg"
        width={720}
        height={720}
        alt="Grainy grey Sentinel-1 radar image of open sea with two bright, elongated hull returns, each marked with a targeting reticle."
        className="block h-auto w-full opacity-90"
      />
      <svg viewBox="0 0 720 720" className="absolute inset-0 h-full w-full" aria-hidden="true">
        <Reticle x={502} y={84} id="TGT-A" />
        <Reticle x={268} y={380} id="TGT-B" />
        <path d="M268 380 L502 84" stroke="#3BF08A" strokeWidth="1.5" strokeDasharray="6 6" fill="none" />
        <rect x="24" y="636" width="400" height="60" fill="#070B0A" fillOpacity="0.85" />
        <text x="40" y="674" fill="#3BF08A" fontFamily="'JetBrains Mono', monospace" fontSize="22">PAIR? AIS IDS: PENDING</text>
      </svg>
      <div className="sweep" />
    </div>
    <figcaption className="mt-3 font-mono text-[11px] leading-relaxed text-ink-3">
      Crop from the detector's validation tiles, enlarged so single radar returns are visible.
    </figcaption>
  </figure>
)

type Summary = { total: number; by_category: Record<string, number> }

export const CategoryBar: React.FC<{ counts: Record<string, number> }> = ({ counts }) => {
  const total = STATUS_ORDER.reduce((n, k) => n + (counts[k] || 0), 0)
  if (!total) return null
  return (
    <div>
      <div className="flex h-2 gap-0.5" role="img"
        aria-label={STATUS_ORDER.map((k) => `${STATUS[k].label}: ${counts[k] || 0}`).join(', ')}>
        {STATUS_ORDER.filter((k) => counts[k]).map((k) => (
          <div key={k} title={`${STATUS[k].label}: ${counts[k]}`}
            style={{ flexGrow: counts[k], background: STATUS[k].color }} />
        ))}
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs">
        {STATUS_ORDER.map((k) => (
          <div key={k} className="flex items-center gap-2">
            <span className="h-2 w-2" style={{ background: STATUS[k].color }} />
            <dt className="text-ink-2">{STATUS[k].label}</dt>
            <dd className="text-ink">{counts[k] || 0}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

const STEPS = [
  ['Acquire radar scenes', 'Sentinel-1 IW scenes over each area of interest, downloaded free from Copernicus. Radar sees through cloud and at night.'],
  ['Detect vessels and pairs', 'A YOLO detector marks single vessels and side-by-side pairs. Land, fixed infrastructure and undersized returns are masked out.'],
  ['Reject one-ship doubles', 'A long hull split into two returns, or a radar sidelobe, looks like a pair. These are merged back into one ship before anything is counted.'],
  ['Match against AIS', 'Each hull is matched to AIS positions broadcast around the image time. The count of matched identities sets the category.'],
  ['Rank for review', 'Candidates are ordered by a triage score and cross-checked against Global Fishing Watch encounter and gap events.'],
]

export const Landing: React.FC = () => {
  const [summary, setSummary] = useState<Summary | null>(null)

  useEffect(() => {
    apiService.getSummary().then(setSummary).catch(() => setSummary(null))
  }, [])

  return (
    <div className="min-h-screen">
      <SiteHeader />

      <main>
        <section className="mx-auto grid max-w-6xl gap-12 px-4 py-14 sm:px-6 lg:grid-cols-12 lg:gap-14 lg:py-20">
          <div className="lg:col-span-6 lg:pt-4">
            <p className="font-mono text-xs text-ink-2">
              <span className="text-signal">&gt;</span> sentinel-1 sar / ais cross-match / skagerrak
            </p>
            <h1 className="cursor mt-5 font-mono text-4xl font-bold uppercase leading-[1.08] tracking-tight text-ink sm:text-5xl">
              Ship-to-ship transfers, tracked from orbit
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
              Open STS finds vessels lying side by side in free Sentinel-1 radar scenes, then
              checks how many of them were broadcasting their identity. Every input is public
              data, so every result can be verified.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <a href="#/console" className="btn-primary px-5 py-3">Enter console</a>
              <a href="#method" className="btn-quiet px-5 py-3">How it works</a>
            </div>

            {summary && summary.total > 0 && (
              <div className="panel mt-12 max-w-xl p-5">
                <div className="mb-4 flex items-baseline justify-between font-mono">
                  <span className="text-xs uppercase tracking-wider text-ink-2">
                    <span className="live-dot mr-2 inline-block h-1.5 w-1.5 rounded-full bg-signal align-middle" />
                    Published run
                  </span>
                  <span className="text-2xl font-bold text-ink">{summary.total} <span className="text-xs font-normal text-ink-2">candidates</span></span>
                </div>
                <CategoryBar counts={summary.by_category} />
              </div>
            )}
          </div>
          <div className="lg:col-span-6">
            <SarFigure />
          </div>
        </section>

        <section id="method" className="border-t border-rule bg-paper/80">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-12">
            <div className="lg:col-span-4">
              <h2 className="font-mono text-2xl font-bold uppercase tracking-tight">How a candidate is made</h2>
              <p className="mt-4 leading-relaxed text-ink-2">
                The pipeline runs offline on each new batch of scenes. The console shows
                what it published.
              </p>
            </div>
            <ol className="lg:col-span-8">
              {STEPS.map(([title, body], i) => (
                <li key={title} className="grid grid-cols-[3.5rem_1fr] gap-x-4 border-t border-rule py-5 first:border-t-0 first:pt-0">
                  <span className="font-mono text-sm text-signal">[{String(i + 1).padStart(2, '0')}]</span>
                  <div>
                    <h3 className="font-mono text-sm font-medium uppercase tracking-wider text-ink">{title}</h3>
                    <p className="mt-1.5 max-w-prose leading-relaxed text-ink-2">{body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="categories" className="border-t border-rule bg-shoal/80">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-12">
            <div className="lg:col-span-4">
              <h2 className="font-mono text-2xl font-bold uppercase tracking-tight">What the categories mean</h2>
              <p className="mt-4 leading-relaxed text-ink-2">
                Missing AIS is missing evidence about AIS. Reception gaps, coverage, faulty
                transponders and processing all produce it. Categories describe evidence,
                never intent.
              </p>
            </div>
            <dl className="space-y-6 lg:col-span-8">
              {STATUS_ORDER.map((k) => (
                <div key={k} className="grid grid-cols-[3.5rem_1fr] gap-x-4">
                  <span className="mt-1.5 h-2 w-8" style={{ background: STATUS[k].color }} />
                  <div>
                    <dt className="font-mono text-sm font-medium uppercase tracking-wider text-ink">{STATUS[k].label}</dt>
                    <dd className="mt-1.5 max-w-prose leading-relaxed text-ink-2">{STATUS[k].meaning}</dd>
                  </div>
                </div>
              ))}
            </dl>
          </div>
        </section>
      </main>

      <footer className="border-t border-rule bg-paper">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-10 font-mono text-xs leading-relaxed text-ink-3 sm:px-6 md:flex-row md:justify-between">
          <p className="max-w-md">
            B.Tech minor project, Anurag University. Imagery: Copernicus Sentinel-1.
            Identity: AIS. Cross-checks: Global Fishing Watch.
          </p>
          <p>
            Based on{' '}
            <a className="text-ink-2 underline underline-offset-2 hover:text-signal" href="https://arxiv.org/abs/2404.07607">
              Ballinger (2024), IGARSS
            </a>
          </p>
        </div>
      </footer>
    </div>
  )
}
