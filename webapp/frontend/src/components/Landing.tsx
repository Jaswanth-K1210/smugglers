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
  <a href="#/" className="flex items-center gap-2 text-ink">
    <svg width="18" height="18" viewBox="0 0 22 22" aria-hidden="true">
      <circle cx="11" cy="11" r="10" fill="none" stroke="#2A2A2A" strokeWidth="1.5" />
      <rect x="6.5" y="5" width="3.5" height="12" rx="1" fill="#44FF88" />
      <rect x="12" y="6.5" width="3.5" height="10.5" rx="1" fill="#E8E8E8" />
    </svg>
    <span className="text-[13px] font-bold">Open STS</span>
  </a>
)

export const SiteHeader: React.FC = () => {
  const user = useDashboardStore((s) => s.user)
  return (
    <header className="sticky top-0 z-50 border-b border-rule bg-paper/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Wordmark />
        <nav className="flex items-center gap-1 text-[13px] sm:gap-5">
          <a href="#method" className="hidden text-ink-2 hover:text-ink sm:block">Method</a>
          <a href="#categories" className="hidden text-ink-2 hover:text-ink sm:block">Categories</a>
          {!user && <a href="#/login" className="px-2 text-ink-2 hover:text-ink">Sign in</a>}
          <a href="#/console" className="btn-primary px-3 py-1.5">Launch console</a>
        </nav>
      </div>
    </header>
  )
}

const Reticle: React.FC<{ x: number; y: number; id: string }> = ({ x, y, id }) => (
  <g stroke="#44FF88" strokeWidth="2" fill="none">
    <circle cx={x} cy={y} r="46" />
    <path d={`M${x - 70} ${y}h18M${x + 52} ${y}h18M${x} ${y - 70}v18M${x} ${y + 52}v18`} />
    <text x={x - 168} y={y + 8} fill="#44FF88" stroke="none" fontFamily="'JetBrains Mono', monospace" fontSize="22">{id}</text>
  </g>
)

const READOUT: [string, string][] = [
  ['Sensor', 'Sentinel-1C IW GRD'],
  ['Polarisation', 'VV'],
  ['Acquired', 'June 2025'],
  ['Detector', 'YOLO, CPU inference'],
  ['Returns', 'TGT-A, TGT-B'],
  ['One-ship check', 'Two separate hulls'],
  ['AIS match', 'Not run on this tile'],
]

const DetectorWindow: React.FC = () => (
  <figure className="panel">
    <div className="panel-head">
      <span className="flex gap-1.5" aria-hidden="true">
        <span className="h-2.5 w-2.5 rounded-full bg-[#FF5F57]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#FEBC2E]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28C840]" />
      </span>
      <span className="hidden text-[11px] uppercase tracking-wider text-ink-2 sm:block">Open STS / detector view</span>
      <span className="text-[11px] uppercase tracking-wider text-signal">Validation tile</span>
    </div>
    <div className="grid md:grid-cols-[minmax(0,440px)_1fr]">
      <div className="relative overflow-hidden bg-black">
        <img
          src="/sar-pair.jpg"
          width={720}
          height={720}
          alt="Grainy grey Sentinel-1 radar image of open sea with two bright, elongated hull returns, each marked with a targeting reticle."
          className="block h-auto w-full"
        />
        <svg viewBox="0 0 720 720" className="absolute inset-0 h-full w-full" aria-hidden="true">
          <Reticle x={502} y={84} id="TGT-A" />
          <Reticle x={268} y={380} id="TGT-B" />
          <path d="M268 380 L502 84" stroke="#44FF88" strokeWidth="1.5" strokeDasharray="6 6" fill="none" />
        </svg>
        <div className="sweep" />
      </div>
      <dl className="border-t border-rule text-xs md:border-l md:border-t-0">
        {READOUT.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 border-b border-rule px-3 py-2.5 last:border-b-0">
            <dt className="text-ink-3">{k}</dt>
            <dd className="text-right text-ink">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
    <figcaption className="border-t border-rule px-3 py-2 text-[11px] text-ink-3">
      A crop from the detector's validation tiles, enlarged so single radar returns are visible.
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
      <dl className="mt-3 space-y-1.5 text-xs">
        {STATUS_ORDER.map((k) => (
          <div key={k} className="flex items-center gap-2">
            <span className="h-2 w-2" style={{ background: STATUS[k].color }} />
            <dt className="flex-1 text-ink-2">{STATUS[k].label}</dt>
            <dd className="text-ink">{counts[k] || 0}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

const STEPS = [
  ['Acquire radar scenes', 'Sentinel-1 IW scenes over each area of interest, free from Copernicus. Radar sees through cloud and at night.'],
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

  const stats: [string, number, string?][] = summary
    ? [['Candidates', summary.total], ...STATUS_ORDER.map((k): [string, number, string] => [STATUS[k].label, summary.by_category[k] || 0, STATUS[k].color])]
    : []

  return (
    <div className="min-h-screen">
      <SiteHeader />

      <main>
        <section className="hero-glow px-4 pb-16 pt-16 sm:px-6 sm:pt-24">
          <div className="mx-auto max-w-4xl text-center">
            <span className="pill-live inline-flex items-center gap-2 px-3 py-1 text-[11px] uppercase tracking-[0.2em]">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-signal" />
              Open-data ship-to-ship monitoring
            </span>
            <h1 className="mt-7 font-sans text-4xl font-bold leading-[1.1] tracking-tight text-ink sm:text-5xl">
              Two ships, side by side, far from port.
              <span className="block text-signal">Seen from orbit. Checked against AIS.</span>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl font-sans text-lg leading-relaxed text-ink-2">
              Open STS finds vessels lying together in free Sentinel-1 radar scenes, then checks
              how many of them were broadcasting their identity. Every input is public, so every
              result can be checked.
            </p>
          </div>

          <div className="mx-auto mt-10 grid max-w-4xl gap-3 sm:grid-cols-2">
            <a href="#/console" className="btn-primary py-3.5 text-sm">Launch the console</a>
            <a href="#method" className="btn-quiet py-3.5 text-sm">See how it works</a>
          </div>
          <p className="mt-4 text-center text-[11px] uppercase tracking-[0.15em] text-ink-3">
            Free imagery / open AIS / checkable results
          </p>

          {stats.length > 0 && (
            <dl className="mx-auto mt-12 grid max-w-4xl grid-cols-2 border border-rule bg-surface sm:grid-cols-4">
              {stats.map(([label, value, color]) => (
                <div key={label} className="border-rule p-4 [&:nth-child(-n+2)]:border-b sm:[&:nth-child(-n+2)]:border-b-0 [&:not(:last-child)]:border-r">
                  <dd className="text-2xl font-bold text-ink">{value}</dd>
                  <dt className="mt-1 flex items-center gap-2 text-[11px] uppercase tracking-wider text-ink-3">
                    {color && <span className="h-2 w-2" style={{ background: color }} />}
                    {label}
                  </dt>
                </div>
              ))}
            </dl>
          )}

          <div className="mx-auto mt-16 max-w-4xl">
            <DetectorWindow />
          </div>
        </section>

        <section id="method" className="border-t border-rule px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-5xl">
            <h2 className="text-center font-sans text-2xl font-bold">How a candidate is made</h2>
            <p className="mx-auto mt-3 max-w-xl text-center font-sans leading-relaxed text-ink-2">
              The pipeline runs offline on each new batch of scenes. The console shows what it published.
            </p>
            <ol className="mt-10 grid gap-1 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
              {STEPS.map(([title, body], i) => (
                <li key={title} className="panel">
                  <div className="panel-head">
                    <span className="font-mono text-[11px] font-semibold uppercase tracking-[1px] text-ink">{title}</span>
                    <span className="badge">{String(i + 1).padStart(2, '0')}</span>
                  </div>
                  <p className="p-3 font-sans text-sm leading-relaxed text-ink-2">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="categories" className="border-t border-rule bg-shoal px-4 py-20 sm:px-6">
          <div className="mx-auto max-w-5xl">
            <h2 className="text-center font-sans text-2xl font-bold">What the categories mean</h2>
            <p className="mx-auto mt-3 max-w-xl text-center font-sans leading-relaxed text-ink-2">
              Missing AIS is missing evidence about AIS. Reception gaps, coverage, faulty transponders
              and processing all produce it. Categories describe evidence, never intent.
            </p>
            <dl className="mt-10 grid gap-1 md:grid-cols-3">
              {STATUS_ORDER.map((k) => (
                <div key={k} className="panel">
                  <dt className="panel-head">
                    <span className="panel-title flex items-center gap-2">
                      <span className="h-2 w-2" style={{ background: STATUS[k].color }} />
                      {STATUS[k].label}
                    </span>
                  </dt>
                  <dd className="p-3 font-sans text-sm leading-relaxed text-ink-2">{STATUS[k].meaning}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>
      </main>

      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-[11px] leading-relaxed text-ink-3 sm:px-6 md:flex-row md:justify-between">
          <p>B.Tech minor project, Anurag University. Imagery: Copernicus Sentinel-1. Identity: AIS. Cross-checks: Global Fishing Watch.</p>
          <p>
            Based on{' '}
            <a className="text-ink-2 underline underline-offset-2 hover:text-ink" href="https://arxiv.org/abs/2404.07607">Ballinger (2024), IGARSS</a>
          </p>
        </div>
      </footer>
    </div>
  )
}
