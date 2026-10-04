import React from 'react'

export const Panel: React.FC<{
  title: string
  count?: number | string
  right?: React.ReactNode
  className?: string
  bodyClassName?: string
  children: React.ReactNode
}> = ({ title, count, right, className = '', bodyClassName = 'p-3', children }) => (
  <section className={`panel ${className}`}>
    <header className="panel-head">
      <h2 className="panel-title">{title}</h2>
      <div className="flex items-center gap-2">
        {right}
        {count !== undefined && <span className="badge">{count}</span>}
      </div>
    </header>
    <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
  </section>
)
