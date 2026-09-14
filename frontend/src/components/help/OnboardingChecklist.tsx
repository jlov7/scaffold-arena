import type { UserProfile } from '../journey/ExperienceModeCard'

interface OnboardingChecklistProps {
  hasTask: boolean
  hasModel: boolean
  hasRun: boolean
  hasResults: boolean
  hasComparison: boolean
  profile?: UserProfile
  onHide?: () => void
}

interface ChecklistStep {
  id: string
  label: string
  description: string
  done: boolean
}

export default function OnboardingChecklist({
  hasTask,
  hasModel,
  hasRun,
  hasResults,
  hasComparison,
  profile = 'evaluator',
  onHide,
}: OnboardingChecklistProps) {
  const PROFILE_LABEL: Record<UserProfile, string> = {
    evaluator: 'Evaluator',
    operator: 'Operator',
    analyst: 'Analyst',
    executive: 'Executive',
  }

  const stepTextByProfile: Record<
    UserProfile,
    {
      reviewDescription: string
      proveDescription: string
    }
  > = {
    evaluator: {
      reviewDescription:
        'Use all three signals together to identify the real winner.',
      proveDescription:
        'Validate value by comparing cheap+winning vs expensive+bare.',
    },
    operator: {
      reviewDescription:
        'Verify output quality, latency, and retries before promoting a winner.',
      proveDescription:
        'Run proof comparison and capture operational tradeoffs for handoff.',
    },
    analyst: {
      reviewDescription:
        'Inspect score breakdown and diff evidence to justify the decision.',
      proveDescription:
        'Run proof comparison and package rationale for stakeholders.',
    },
    executive: {
      reviewDescription:
        'Confirm winner confidence quickly using score, cost, and time summary.',
      proveDescription:
        'Export and share concise proof that orchestration choice improves outcomes.',
    },
  }

  const profileText = stepTextByProfile[profile]

  const steps: ChecklistStep[] = [
    {
      id: 'task',
      label: 'Choose a task',
      description: 'Pick one benchmark scenario to define what quality means.',
      done: hasTask,
    },
    {
      id: 'model',
      label: 'Choose a model',
      description: 'Select the model you want to test scaffolding around.',
      done: hasModel,
    },
    {
      id: 'run',
      label: 'Run the arena',
      description: 'Execute all scaffolds on the same input for fair comparison.',
      done: hasRun,
    },
    {
      id: 'review',
      label: 'Review score, cost, and time',
      description: profileText.reviewDescription,
      done: hasResults,
    },
    {
      id: 'prove',
      label: 'Run proof comparison',
      description: profileText.proveDescription,
      done: hasComparison,
    },
  ]

  const nextStep = steps.find((step) => !step.done)

  return (
    <aside
      className="rounded-lg border border-border/70 bg-bg-secondary p-4"
      aria-label="Getting started checklist"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] font-mono uppercase tracking-widest text-text-secondary">
          Getting started checklist
        </div>
        <div className="flex items-center gap-2">
          <div className="text-[11px] font-mono text-text-secondary">
            {steps.filter((step) => step.done).length}/{steps.length} complete
          </div>
          {onHide && (
            <button
              type="button"
              onClick={onHide}
              className="rounded border border-border px-2 py-1 text-[10px] font-mono text-text-muted hover:border-accent-info hover:text-accent-info"
            >
              Hide
            </button>
          )}
        </div>
      </div>
      <div className="mt-2 text-[11px] font-mono text-text-muted">
        Audience: {PROFILE_LABEL[profile]}
      </div>

      <ol className="mt-3 space-y-2">
        {steps.map((step, index) => (
          <li
            key={step.id}
            className={[
              'rounded border px-3 py-2 text-xs',
              step.done
                ? 'border-accent-winner/50 bg-accent-winner/10'
                : index === steps.findIndex((candidate) => !candidate.done)
                  ? 'border-accent-info/60 bg-accent-info/10'
                  : 'border-border/60 bg-bg-primary',
            ].join(' ')}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-text-primary">{step.label}</span>
              <span
                className={[
                  'text-[11px] font-mono uppercase tracking-wider',
                  step.done ? 'text-accent-winner' : 'text-text-muted',
                ].join(' ')}
              >
                {step.done ? 'Done' : 'Next'}
              </span>
            </div>
            <p className="mt-1 text-text-secondary">{step.description}</p>
          </li>
        ))}
      </ol>

      <div className="mt-3 rounded border border-border/60 bg-bg-primary px-3 py-2 text-xs text-text-secondary">
        {nextStep
          ? `No guesswork: your next action is "${nextStep.label}".`
          : 'You are fully through the core flow. Next: export and share your run evidence.'}
      </div>
    </aside>
  )
}
