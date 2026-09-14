import type { ReactNode } from 'react'

interface ErrorStateProps {
  title: string
  description: string
  action?: ReactNode
}

export function ErrorState({ title, description, action }: ErrorStateProps) {
  return (
    <div className="rounded-md border border-accent-loser/45 bg-accent-loser/10 p-4">
      <div className="lab-label text-accent-loser">Error</div>
      <h3 className="mt-2 text-base font-semibold text-text-primary">{title}</h3>
      <p className="lab-copy mt-2 text-sm">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
