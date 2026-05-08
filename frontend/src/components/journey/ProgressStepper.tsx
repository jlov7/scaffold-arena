import type { JourneyStep } from '../../features/journey/useJourneyProgress'

interface ProgressStepperProps {
  steps: JourneyStep[]
}

export function ProgressStepper({ steps }: ProgressStepperProps) {
  const completedCount = steps.filter((step) => step.status === 'complete').length
  const currentIndex = Math.max(
    0,
    steps.findIndex((step) => step.status === 'current'),
  )
  const progressPct =
    steps.length === 0 ? 0 : Math.round(((completedCount + (steps[currentIndex]?.status === 'current' ? 0.5 : 0)) / steps.length) * 100)

  return (
    <>
      <section
        className="lab-panel p-3 sm:hidden"
        aria-label="Mobile journey progress"
      >
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span>
            Step {currentIndex + 1} of {steps.length}
          </span>
          <span className="tabular-nums text-accent-info">{progressPct}%</span>
        </div>
        <div className="mt-2 h-1.5 rounded bg-bg-tertiary">
          <div
            className="h-1.5 rounded bg-accent-info transition-[width] duration-200"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <ol className="mt-3 flex snap-x snap-mandatory gap-2 overflow-x-auto pb-1">
          {steps.map((step, index) => (
            <li
              key={step.id}
              aria-current={step.status === 'current' ? 'step' : undefined}
              className={[
                'min-w-[10.5rem] snap-start rounded-md border px-3 py-2 text-sm',
                step.status === 'current'
                  ? 'border-accent-info bg-accent-info/10 text-accent-info'
                  : step.status === 'complete'
                    ? 'border-accent-winner/40 bg-accent-winner/10 text-accent-winner'
                    : 'border-border bg-bg-secondary text-text-secondary',
              ].join(' ')}
            >
              <div className="font-mono text-[10px] uppercase tracking-[0.12em] opacity-80">
                Step {index + 1}
              </div>
              <div className="mt-1">{step.label}</div>
            </li>
          ))}
        </ol>
      </section>

      <ol
        className="hidden gap-2 sm:grid sm:grid-cols-4"
        aria-label="Arena journey progress"
      >
        {steps.map((step, index) => (
          <li
            key={step.id}
            aria-current={step.status === 'current' ? 'step' : undefined}
            className={[
              'rounded-md border px-3 py-2 text-sm',
              step.status === 'current'
                ? 'border-accent-info bg-accent-info/10 text-accent-info'
                : step.status === 'complete'
                  ? 'border-accent-winner/40 bg-accent-winner/10 text-accent-winner'
                  : 'border-border bg-bg-secondary text-text-secondary',
            ].join(' ')}
          >
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] opacity-80">
              Step {index + 1}
            </div>
            <div className="mt-1">{step.label}</div>
          </li>
        ))}
      </ol>
    </>
  )
}
