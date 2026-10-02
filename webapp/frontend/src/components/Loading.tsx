import React from 'react'

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg'
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ size = 'md' }) => {
  const sizeClass = {
    sm: 'w-4 h-4',
    md: 'w-8 h-8',
    lg: 'w-12 h-12'
  }[size]

  return (
    <div className={`${sizeClass} animate-spin`}>
      <div className="h-full w-full border-4 border-slate-700 border-t-ocean-500 rounded-full"></div>
    </div>
  )
}

export const EmptyState: React.FC<{ message: string }> = ({ message }) => (
  <div className="flex flex-col items-center justify-center h-64 text-slate-400">
    <p>{message}</p>
  </div>
)
