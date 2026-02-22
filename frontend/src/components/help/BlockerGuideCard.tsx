import {
  playbookActionLabel,
  type TroubleshootingPlaybook,
} from '../../features/help/playbook'

interface BlockerGuideCardProps {
  playbook: TroubleshootingPlaybook
  onPrimaryAction: () => void
  onOpenHelp: () => void
}

export default function BlockerGuideCard({
  playbook,
  onPrimaryAction,
  onOpenHelp,
}: BlockerGuideCardProps) {
  return (
    <section className="rounded-lg border border-accent-warning/50 bg-accent-warning/10 p-4 font-mono">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-accent-warning">
            Immediate guidance
          </div>
          <h2 className="mt-1 text-sm font-semibold text-text-primary">
            {playbook.title}
          </h2>
          <p className="mt-1 text-xs text-text-secondary">{playbook.summary}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPrimaryAction}
            className="rounded border border-accent-warning/70 min-h-11 px-3.5 py-2 text-xs text-accent-warning hover:bg-accent-warning/20 sm:min-h-0 sm:px-3 sm:py-1"
          >
            {playbookActionLabel(playbook.primaryAction)}
          </button>
          <button
            type="button"
            onClick={onOpenHelp}
            className="rounded border border-border min-h-11 px-3.5 py-2 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info sm:min-h-0 sm:px-3 sm:py-1"
          >
            Open full help center
          </button>
        </div>
      </div>

      <ol className="mt-3 list-decimal space-y-1 pl-4 text-xs text-text-secondary">
        {playbook.steps.slice(0, 4).map((step, index) => (
          <li key={`${step.text}-${index}`}>{step.text}</li>
        ))}
      </ol>
    </section>
  )
}
