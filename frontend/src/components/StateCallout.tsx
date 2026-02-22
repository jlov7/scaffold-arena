import type { UiStateKind } from '../features/states/taxonomy'

interface StateCalloutProps {
  kind: UiStateKind
  title: string
  description: string
  actionLabel?: string
  onAction?: () => void
}

const STYLE_MAP: Record<
  UiStateKind,
  { surface: string; text: string }
> = {
  loading: {
    surface: 'state-guidance',
    text: 'text-accent-info',
  },
  empty: {
    surface: 'surface-optional',
    text: 'text-text-secondary',
  },
  partial: {
    surface: 'state-blocker',
    text: 'text-accent-warning',
  },
  error: {
    surface: 'state-alert',
    text: 'text-accent-loser',
  },
  blocked: {
    surface: 'state-blocker',
    text: 'text-accent-warning',
  },
  success: {
    surface: 'state-success',
    text: 'text-accent-winner',
  },
}

export default function StateCallout({
  kind,
  title,
  description,
  actionLabel,
  onAction,
}: StateCalloutProps) {
  const style = STYLE_MAP[kind]
  return (
    <section
      className={[
        'rounded-lg border p-4 font-mono',
        style.surface,
      ].join(' ')}
      aria-label={`${title} callout`}
    >
      <div className={['text-[10px] uppercase tracking-widest', style.text].join(' ')}>
        {kind}
      </div>
      <h3 className="mt-1 text-sm text-text-primary">{title}</h3>
      <p className="mt-1 text-xs text-text-secondary">{description}</p>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="mt-3 rounded border border-current px-3 py-1.5 text-xs hover:bg-black/10"
        >
          {actionLabel}
        </button>
      )}
    </section>
  )
}
