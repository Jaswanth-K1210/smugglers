import React, { useEffect, useRef, useState } from 'react'

export type MenuItem = { label: string; onSelect: () => void; disabled?: boolean } | 'divider'

export const Menu: React.FC<{ items: MenuItem[] }> = ({ items }) => {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close) }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu" aria-label="Open menu"
        className="flex h-7 w-7 flex-col items-center justify-center gap-[3px] border border-rule hover:border-[#444]">
        {[0, 1, 2].map((i) => <span key={i} className="block h-px w-3.5 bg-ink" />)}
      </button>
      {open && (
        <ul role="menu" className="absolute left-0 top-9 z-[1100] w-60 border border-rule bg-surface py-1 shadow-2xl">
          {items.map((it, i) => it === 'divider' ? (
            <li key={i} role="separator" className="my-1 border-t border-rule" />
          ) : (
            <li key={it.label} role="none">
              <button role="menuitem" disabled={it.disabled} onClick={() => { setOpen(false); it.onSelect() }}
                className="w-full px-3 py-2 text-left text-xs text-ink hover:bg-white/[0.05] disabled:text-ink-3">
                {it.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
