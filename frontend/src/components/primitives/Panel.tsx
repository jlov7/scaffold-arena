import type { HTMLAttributes, ReactNode } from 'react'

interface PanelProps extends HTMLAttributes<HTMLElement> {
  label?: string
  title?: string
  actions?: ReactNode
  children: ReactNode
}

export function Panel({
  label,
  title,
  actions,
  children,
  className = '',
  ...props
}: PanelProps) {
  return (
    <section {...props} className={['lab-panel p-4', className].join(' ')}>
      {(label || title || actions) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            {label && <div className="lab-label">{label}</div>}
            {title && (
              <h2 className="mt-1 text-lg font-semibold leading-tight text-text-primary">
                {title}
              </h2>
            )}
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
