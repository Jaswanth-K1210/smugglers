import React, { useState } from 'react'
import { apiService } from '../services/api'

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
    <section className="panel space-y-4 p-5">
      <div>
        <h2 className="panel-title">Run detection</h2>
        <p className="mt-1 text-sm text-ink-2">Upload one Sentinel-1 tile. The detector runs on CPU in a few seconds.</p>
      </div>

      <label className="block cursor-pointer rounded-md border border-dashed border-rule bg-paper px-4 py-5 text-center text-sm hover:border-ink-3">
        <span className="font-medium text-signal">{file ? file.name : 'Choose a tile'}</span>
        <span className="mt-1 block text-ink-3">GeoTIFF, JP2, PNG or JPEG</span>
        <input type="file" accept=".tif,.tiff,.jp2,.png,.jpg,.jpeg" className="sr-only"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null) }} />
      </label>

      <button onClick={run} disabled={!file || loading} className="btn-primary w-full">
        {loading ? 'Running detection…' : 'Run detection'}
      </button>

      {error && <p role="alert" className="text-sm text-unmatched">{error}</p>}

      {result && (
        <dl className="grid grid-cols-3 gap-2 border-t border-rule pt-4 text-sm">
          <div><dt className="text-ink-2">Vessels</dt><dd className="font-mono text-xl font-semibold">{result.vessels_count ?? 0}</dd></div>
          <div><dt className="text-ink-2">Pairs</dt><dd className="font-mono text-xl font-semibold">{result.sts_count ?? 0}</dd></div>
          <div><dt className="text-ink-2">Time</dt><dd className="font-mono text-xl font-semibold">{Number(result.processing_time ?? 0).toFixed(1)}s</dd></div>
        </dl>
      )}
    </section>
  )
}
