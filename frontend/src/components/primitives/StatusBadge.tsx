interface StatusBadgeProps {
  children: string
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}

const TONE_CLASS: Record<NonNullable<StatusBadgeProps['tone']>, string> = {
  neutral: 'border-border bg-bg-primary text-text-secondary',
  success: 'border-accent-winner/45 bg-accent-winner/10 text-accent-winner',
  warning: 'border-accent-warning/45 bg-accent-warning/10 text-accent-warning',
  danger: 'border-accent-loser/45 bg-accent-loser/10 text-accent-loser',
  info: 'border-accent-info/45 bg-accent-info/10 text-accent-info',
}

export function StatusBadge({ children, tone = 'neutral' }: StatusBadgeProps) {
  return (
    <span className={['inline-flex items-center rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em]', TONE_CLASS[tone]].join(' ')}>
      {children}
    </span>
  )
}
