import React from 'react'
import { Satellite, Activity } from 'lucide-react'

export const Header: React.FC = () => {
  return (
    <header className="glass-effect card-shadow sticky top-0 z-40 border-b border-ocean-500/20">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="absolute inset-0 bg-gradient-to-r from-ocean-600 to-ocean-400 rounded-lg blur opacity-75 animate-pulse"></div>
            <div className="relative bg-slate-900 rounded-lg p-2">
              <Satellite className="w-6 h-6 text-ocean-400" />
            </div>
          </div>
          <div>
            <h1 className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-ocean-400 to-ocean-300">
              Dark STS Detector
            </h1>
            <p className="text-xs text-slate-400">Ship-to-Ship Transfer Detection</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-green-500/10 rounded-lg border border-green-500/30">
            <Activity className="w-4 h-4 text-green-400 animate-pulse" />
            <span className="text-sm text-green-300 font-medium">Live</span>
          </div>
        </div>
      </div>
    </header>
  )
}
