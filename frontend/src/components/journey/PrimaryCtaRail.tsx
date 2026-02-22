import type { JourneyStage } from '../../features/journey/useJourneyProgress'

interface PrimaryCtaRailProps {
  stage: JourneyStage
  canRun: boolean
  hasResults: boolean
  runDisabledReason?: string
  orderVariant?: 'compare_first' | 'export_first'
  showSecondary?: boolean
  onOpenResults?: () => void
  onRun: () => void
  onCompare: () => void
  onExport: () => void
  onShare: () => void
}

export function PrimaryCtaRail({
  stage,
  canRun,
  hasResults,
  runDisabledReason,
  orderVariant = 'compare_first',
  showSecondary = true,
  onOpenResults,
  onRun,
  onCompare,
  onExport,
  onShare,
}: PrimaryCtaRailProps) {
  const secondaryActions =
    orderVariant === 'export_first'
      ? [
          { key: 'export', label: 'Export report', onClick: onExport },
          { key: 'compare', label: 'Run proof comparison', onClick: onCompare },
        ]
      : [
          { key: 'compare', label: 'Run proof comparison', onClick: onCompare },
          { key: 'export', label: 'Export report', onClick: onExport },
        ]

  return (
    <section
      className="rounded-lg border border-border bg-bg-secondary p-3"
      aria-label="Primary actions"
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onRun}
          disabled={!canRun}
          title={canRun ? undefined : runDisabledReason}
          className="rounded border border-accent-info bg-accent-info/10 min-h-11 px-3.5 py-2 text-xs font-mono text-accent-info transition-colors hover:bg-accent-info hover:text-white disabled:cursor-not-allowed disabled:opacity-40 sm:min-h-0 sm:px-3 sm:py-1.5"
        >
          {stage === 'running'
            ? 'Run in progress'
            : hasResults
              ? 'Run again'
              : 'Run arena'}
        </button>
        {showSecondary ? (
          <>
            {secondaryActions.map((action) => (
              <button
                key={action.key}
                type="button"
                onClick={action.onClick}
                disabled={!hasResults}
                className="rounded border border-border min-h-11 px-3.5 py-2 text-xs font-mono text-text-secondary transition-colors hover:border-accent-info hover:text-accent-info disabled:cursor-not-allowed disabled:opacity-40 sm:min-h-0 sm:px-3 sm:py-1.5"
              >
                {action.label}
              </button>
            ))}
            <button
              type="button"
              onClick={onShare}
              disabled={!hasResults}
              className="rounded border border-border min-h-11 px-3.5 py-2 text-xs font-mono text-text-secondary transition-colors hover:border-accent-info hover:text-accent-info disabled:cursor-not-allowed disabled:opacity-40 sm:min-h-0 sm:px-3 sm:py-1.5"
            >
              Share run
            </button>
          </>
        ) : (
          hasResults &&
          onOpenResults && (
            <button
              type="button"
              onClick={onOpenResults}
              className="rounded border border-border min-h-11 px-3.5 py-2 text-xs font-mono text-text-secondary transition-colors hover:border-accent-info hover:text-accent-info sm:min-h-0 sm:px-3 sm:py-1.5"
            >
              Review results
            </button>
          )
        )}
      </div>
    </section>
  )
}
