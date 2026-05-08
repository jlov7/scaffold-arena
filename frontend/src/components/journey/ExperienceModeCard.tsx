export type ExperienceMode = 'guided' | 'advanced'
export type UserProfile = 'evaluator' | 'operator' | 'analyst' | 'executive'

interface ExperienceModeCardProps {
  mode: ExperienceMode
  profile: UserProfile
  onModeChange: (mode: ExperienceMode) => void
  onProfileChange: (profile: UserProfile) => void
}

const PROFILE_HELP: Record<UserProfile, string> = {
  evaluator: 'Fast, guided flow to a clear winner and evidence.',
  operator: 'Operational controls with clear failure recovery steps.',
  analyst: 'Deeper result interpretation, diffs, and decision evidence.',
  executive: 'Concise summary path focused on decision confidence.',
}

const PROFILE_LABEL: Record<UserProfile, string> = {
  evaluator: 'Evaluator',
  operator: 'Operator',
  analyst: 'Analyst',
  executive: 'Executive',
}

export function ExperienceModeCard({
  mode,
  profile,
  onModeChange,
  onProfileChange,
}: ExperienceModeCardProps) {
  return (
    <section className="lab-panel p-4" aria-label="Workspace personalization">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="lab-label text-accent-info">Quick start setup</div>
          <h2 className="mt-1 text-lg font-semibold text-text-primary">
            Choose your experience
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onModeChange('guided')}
            className={[
              'ui-control rounded-md border px-3 py-1.5 text-sm font-medium transition-colors',
              mode === 'guided'
                ? 'border-accent-info bg-accent-info/20 text-accent-info'
                : 'border-border text-text-secondary hover:border-accent-info hover:text-accent-info',
            ].join(' ')}
          >
            Guided
          </button>
          <button
            type="button"
            onClick={() => onModeChange('advanced')}
            className={[
              'ui-control rounded-md border px-3 py-1.5 text-sm font-medium transition-colors',
              mode === 'advanced'
                ? 'border-accent-info bg-accent-info/20 text-accent-info'
                : 'border-border text-text-secondary hover:border-accent-info hover:text-accent-info',
            ].join(' ')}
          >
            Advanced
          </button>
        </div>
      </div>

      <div className="mt-3">
        <div className="lab-label">
          I am a...
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-4">
          {(Object.keys(PROFILE_LABEL) as UserProfile[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => onProfileChange(key)}
              className={[
                'ui-control rounded-md border px-3 py-2 text-left text-sm transition-colors',
                profile === key
                  ? 'border-accent-info bg-bg-primary text-text-primary'
                  : 'border-border bg-bg-secondary text-text-secondary hover:border-accent-info hover:text-accent-info',
              ].join(' ')}
            >
              {PROFILE_LABEL[key]}
            </button>
          ))}
        </div>
      </div>

      <p className="lab-copy mt-3 text-sm">
        {PROFILE_HELP[profile]}
      </p>
    </section>
  )
}
