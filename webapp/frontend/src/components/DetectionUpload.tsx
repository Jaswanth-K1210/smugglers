import React, { useState } from 'react'
import { apiService } from '../services/api'
import { Upload, CheckCircle, AlertCircle } from 'lucide-react'
import { LoadingSpinner } from './Loading'

export const DetectionUpload: React.FC = () => {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      setError(null)
      setResult(null)
    }
  }

  const handleUpload = async () => {
    if (!file) return

    try {
      setLoading(true)
      const result = await apiService.detectShip(file)
      setResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="glass-effect card-shadow rounded-lg p-6 space-y-4">
      <h3 className="text-lg font-semibold">Live Detection</h3>
      <p className="text-sm text-slate-400">
        Upload a Sentinel-1 SAR tile to run the detector on CPU
      </p>

      <div className="border-2 border-dashed border-slate-700 rounded-lg p-6 text-center hover:border-ocean-500 transition-colors cursor-pointer"
        onClick={() => document.getElementById('file-input')?.click()}
      >
        <Upload className="w-8 h-8 mx-auto mb-2 text-slate-500" />
        <p className="text-sm text-slate-400">
          {file ? file.name : 'Click or drag to upload SAR image'}
        </p>
        <input
          id="file-input"
          type="file"
          accept=".tif,.tiff,.jp2"
          onChange={handleFileChange}
          className="hidden"
        />
      </div>

      <button
        onClick={handleUpload}
        disabled={!file || loading}
        className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <LoadingSpinner size="sm" />
            Processing...
          </>
        ) : (
          'Run Detection'
        )}
      </button>

      {error && (
        <div className="p-3 bg-red-500/20 border border-red-500/30 rounded-lg flex items-center gap-2 text-red-300 text-sm">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {result && (
        <div className="p-3 bg-green-500/20 border border-green-500/30 rounded-lg space-y-2">
          <div className="flex items-center gap-2 text-green-300 text-sm font-medium">
            <CheckCircle className="w-4 h-4" />
            Detection Complete
          </div>
          <div className="text-xs text-green-200 space-y-1">
            <p>Vessels Detected: <span className="font-semibold">{result.vessels_count || 0}</span></p>
            <p>STS Events: <span className="font-semibold">{result.sts_count || 0}</span></p>
            {result.processing_time && (
              <p>Processing Time: <span className="font-semibold">{result.processing_time.toFixed(2)}s</span></p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
