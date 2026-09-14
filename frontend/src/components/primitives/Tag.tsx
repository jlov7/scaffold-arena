import type { ReactNode } from 'react'

interface TagProps {
  tone?: 'neutral' | 'info' | 'success' | 'warning'
  children: ReactNode
}

export function Tag({ tone = 'neutral', children }: TagProps) {
  const toneClass =
    tone === 'info'
      ? 'border-accent-info/50 text-accent-info bg-accent-info/10'
      : tone === 'success'
        ? 'border-accent-winner/50 text-accent-winner bg-accent-winner/10'
        : tone === 'warning'
          ? 'border-accent-warning/50 text-accent-warning bg-accent-warning/10'
          : 'border-border text-text-secondary bg-bg-primary'

  return (
    <span className={['inline-flex items-center rounded-sm border px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.12em]', toneClass].join(' ')}>
      {children}
    </span>
  )
}
