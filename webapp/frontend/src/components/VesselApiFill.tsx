import React, { useState } from 'react'
import { apiService, BBox, LiveFeed } from '../services/api'
import { Panel } from './Panel'

/** "Fill this view": one VesselAPI request batch for the current map view, where the free live
 *  feeds have few receivers (e.g. India). Shared monthly quota, so it is a button, not a feed. */
export const VesselApiFill: React.FC<{ bounds: BBox | null; feed: LiveFeed | null; onFilled: () => void }> = ({ bounds, feed, onFilled }) => {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const va = feed?.vesselapi
  if (!va?.configured) return null
  const tooBig = !!bounds && (bounds[2] - bounds[0] > va.max_deg || bounds[3] - bounds[1] > va.max_deg)
  const fill = async () => {
    if (!bounds) return
    setBusy(true); setMsg(null)
    try {
      const r = await apiService.fillFromVesselApi(bounds)
      setMsg(`${r.added} ships added for 30 minutes${r.remaining != null ? ` · ${r.remaining} requests left this month` : ''}.`)
      onFilled()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'VesselAPI did not answer.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel title="Fill this view" bodyClassName="space-y-2 p-3">
      <p className="text-[11px] leading-relaxed text-ink-2">
        Few free AIS receivers cover some coasts (India, for example). Load the ships in this view from VesselAPI (about 30-100, positions minutes old).
        {va.remaining != null && <> {va.remaining} requests left this month.</>}
      </p>
      <button onClick={fill} disabled={busy || !bounds || tooBig} className="btn-quiet w-full">
        {busy ? 'Loading ships…' : tooBig ? `Zoom in to ${va.max_deg}° × ${va.max_deg}° or less` : 'Fill this view (VesselAPI)'}
      </button>
      {msg && <p role="status" className="text-[11px] text-ink-3">{msg}</p>}
    </Panel>
  )
}
