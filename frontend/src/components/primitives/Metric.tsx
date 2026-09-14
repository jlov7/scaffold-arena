interface MetricProps {
  label: string
  value: string
  detail?: string
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}

const TONE_CLASS: Record<NonNullable<MetricProps['tone']>, string> = {
  neutral: 'text-text-primary',
  success: 'text-accent-winner',
  warning: 'text-accent-warning',
  danger: 'text-accent-loser',
  info: 'text-accent-info',
}

export function Metric({ label, value, detail, tone = 'neutral' }: MetricProps) {
  return (
    <div className="lab-row px-3 py-2">
      <div className="lab-label">{label}</div>
      <div className={['mt-1 font-mono text-xl tabular-nums', TONE_CLASS[tone]].join(' ')}>
        {value}
      </div>
      {detail && <div className="mt-1 text-xs text-text-muted">{detail}</div>}
    </div>
  )
}
