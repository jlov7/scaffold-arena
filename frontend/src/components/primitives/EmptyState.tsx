import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  description: string
  action?: ReactNode
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="lab-panel p-5">
      <div className="lab-label">Empty</div>
      <h3 className="mt-2 text-lg font-semibold text-text-primary">{title}</h3>
      <p className="lab-copy mt-2 text-sm">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
