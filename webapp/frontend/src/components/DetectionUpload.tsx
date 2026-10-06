import React, { useState } from 'react'
import { apiService } from '../services/api'
import { Panel } from './Panel'

export const DetectionUpload: React.FC = () => {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    try {
      setResult(await apiService.detectShip(file))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Detection failed. Check the file and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Panel title="Run detection" right={<span className="text-[10px] uppercase text-ink-3">CPU</span>} bodyClassName="space-y-3 p-3">
      <p className="text-sm leading-relaxed text-ink-2">Upload one Sentinel-1 tile. The detector runs in a few seconds.</p>

      <label className="flex min-h-[180px] cursor-pointer flex-col items-center justify-center rounded-sm border-2 border-dashed border-rule bg-paper px-4 py-10 text-center hover:border-signal/60">
        <span className="text-base font-medium text-signal">{file ? file.name : 'Choose a radar image to upload'}</span>
        <span className="mt-2 block text-xs text-ink-3">GeoTIFF, JP2, PNG or JPEG, up to 10 MB</span>
        <input type="file" accept=".tif,.tiff,.jp2,.png,.jpg,.jpeg" className="sr-only"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null) }} />
      </label>

      <button onClick={run} disabled={!file || loading} className="btn-primary w-full py-3 text-sm">
        {loading ? 'Running detection…' : 'Run detection'}
      </button>

      {error && <p role="alert" className="text-sm text-unmatched">{error}</p>}

      {result && (
        <dl className="grid grid-cols-3 gap-2 border-t border-rule pt-3 text-[11px] uppercase">
          <div><dt className="text-ink-2">Vessels</dt><dd className="text-lg font-bold text-ink">{result.vessels_count ?? 0}</dd></div>
          <div><dt className="text-ink-2">Pairs</dt><dd className="text-lg font-bold text-ink">{result.sts_count ?? 0}</dd></div>
          <div><dt className="text-ink-2">Time</dt><dd className="text-lg font-bold text-ink">{Number(result.processing_time ?? 0).toFixed(1)}s</dd></div>
        </dl>
      )}
    </Panel>
  )
}
