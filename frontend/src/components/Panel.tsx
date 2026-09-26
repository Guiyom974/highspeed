import { useId, useState, type ReactNode } from 'react'

interface PanelProps {
  title: ReactNode
  subtitle?: ReactNode
  badge?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
  className?: string
}

/** Frosted-glass collapsible panel with animated chevron and height transition. */
export default function Panel({ title, subtitle, badge, defaultOpen = true, children, className = '' }: PanelProps) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()

  return (
    <section className={`panel${open ? ' open' : ''} ${className}`.trim()}>
      <button
        type="button"
        className="panel-head"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
      >
        <svg className="panel-chevron" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="panel-title">{title}</span>
        {subtitle && <span className="panel-sub">{subtitle}</span>}
        {badge && <span className="panel-badge" onClick={(e) => e.stopPropagation()}>{badge}</span>}
      </button>
      <div className="panel-collapse" id={id} role="region">
        <div className="panel-body">{children}</div>
      </div>
    </section>
  )
}
