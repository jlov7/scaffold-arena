import { useMemo } from 'react'
import {
  getTaskPlaybook,
  playbookActionLabel,
  resolveHelpBlocker,
  type PlaybookAction,
} from '../../features/help/playbook'
import { classifyApiError } from '../../errors/classify'
import type { UserProfile } from '../journey/ExperienceModeCard'
import { Modal } from '../primitives/Modal'

interface HelpCenterModalProps {
  isOpen: boolean
  isOnline: boolean
  connectionState: 'idle' | 'connected' | 'retrying' | 'failed'
  hasApiToken: boolean
  profile: UserProfile
  taskId: string
  errorMessage: string | null
  onClose: () => void
  onOpenTour: () => void
  onOpenShortcuts: () => void
  onOpenSettings: () => void
  onRetry: () => void
  onRun: () => void
}

export default function HelpCenterModal({
  isOpen,
  isOnline,
  connectionState,
  hasApiToken,
  profile,
  taskId,
  errorMessage,
  onClose,
  onOpenTour,
  onOpenShortcuts,
  onOpenSettings,
  onRetry,
  onRun,
}: HelpCenterModalProps) {
  const stuckMessage = useMemo(() => {
    if (!isOnline) {
      return 'You appear to be offline. Reconnect to the internet, then retry your run.'
    }
    if (connectionState === 'retrying') {
      return 'The stream is reconnecting. Wait a moment; if it does not recover, use Retry in the warning banner.'
    }
    if (connectionState === 'failed') {
      return 'The stream failed to reconnect. Use the Retry action shown in the banner before starting a new run.'
    }
    if (!hasApiToken) {
      return 'Session token is missing. Open Settings and configure your API token before running protected actions.'
    }
    return 'If anything feels unclear, use Guided Tour for context and keyboard shortcuts for faster navigation.'
  }, [connectionState, hasApiToken, isOnline])

  const blocker = useMemo(
    () =>
      resolveHelpBlocker({
        isOnline,
        connectionState,
        errorMessage,
      }),
    [connectionState, errorMessage, isOnline],
  )
  const playbook = useMemo(
    () => getTaskPlaybook(taskId, blocker),
    [blocker, taskId],
  )
  const rolePath = useMemo(
    () =>
      ({
        evaluator: {
          label: 'Evaluator',
          summary: 'Move quickly to a winner you can defend with clear evidence.',
          recommendedAction: 'run' as PlaybookAction,
          checkpoints: [
            'Complete one full arena run.',
            'Confirm winner using score, cost, and time together.',
            'Run proof comparison before sharing conclusions.',
          ],
        },
        operator: {
          label: 'Operator',
          summary: 'Prioritize reliability, retries, and stable execution behavior.',
          recommendedAction: 'open_settings' as PlaybookAction,
          checkpoints: [
            'Validate token and advanced run controls before reruns.',
            'Resolve blockers using the recovery playbook in order.',
            'Capture operational risks in the report handoff.',
          ],
        },
        analyst: {
          label: 'Analyst',
          summary: 'Dig into evidence depth, deltas, and reproducible rationale.',
          recommendedAction: 'open_shortcuts' as PlaybookAction,
          checkpoints: [
            'Review scoreboard and diff evidence together in Results.',
            'Use shortcuts to move faster across analysis surfaces.',
            'Package rationale with comparison and report export.',
          ],
        },
        executive: {
          label: 'Executive',
          summary: 'Use a concise path to confidence, then share decision-ready evidence.',
          recommendedAction: 'open_tour' as PlaybookAction,
          checkpoints: [
            'Run the guided tour for a fast workflow overview.',
            'Confirm final winner, score, and cost in Results.',
            'Export evidence for stakeholder review.',
          ],
        },
      })[profile],
    [profile],
  )

  function runPrimaryAction(action: PlaybookAction): void {
    onClose()
    switch (action) {
      case 'open_settings':
        onOpenSettings()
        break
      case 'retry':
        onRetry()
        break
      case 'wait':
        break
      case 'open_tour':
        onOpenTour()
        break
      case 'open_shortcuts':
        onOpenShortcuts()
        break
      case 'run':
        onRun()
        break
    }
  }

  const primaryActionLabel = useMemo(
    () => playbookActionLabel(playbook.primaryAction),
    [playbook.primaryAction],
  )
  const diagnostics = useMemo(() => {
    const errorKind = errorMessage ? classifyApiError(errorMessage).kind : 'none'
    return {
      blocker,
      errorKind,
      connectionState,
      tokenConfigured: hasApiToken,
      online: isOnline,
    }
  }, [blocker, connectionState, errorMessage, hasApiToken, isOnline])

  if (!isOpen) return null

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Help Center"
      closeLabel="Close help center"
      className="max-h-[88vh] max-w-2xl font-mono"
      contentClassName="max-h-[88vh] overflow-y-auto p-5"
    >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-widest text-text-secondary">
              Help Center
            </div>
            <p className="mt-2 text-sm text-text-primary">
              No guesswork. Follow this exact path to complete a run and resolve blockers.
            </p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="rounded border border-border/60 bg-bg-primary p-3">
            <div className="text-[11px] uppercase tracking-widest text-text-secondary">Quick actions</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  onClose()
                  onOpenTour()
                }}
                className="rounded border border-border min-h-11 px-3 py-2 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info sm:min-h-0 sm:px-2 sm:py-1 sm:text-[11px]"
              >
                Open guided tour
              </button>
              <button
                type="button"
                onClick={() => {
                  onClose()
                  onOpenShortcuts()
                }}
                className="rounded border border-border min-h-11 px-3 py-2 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info sm:min-h-0 sm:px-2 sm:py-1 sm:text-[11px]"
              >
                Show shortcuts
              </button>
              <button
                type="button"
                onClick={() => {
                  onClose()
                  onOpenSettings()
                }}
                className="rounded border border-border min-h-11 px-3 py-2 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info sm:min-h-0 sm:px-2 sm:py-1 sm:text-[11px]"
              >
                Open settings
              </button>
            </div>
          </div>

          <div className="rounded border border-border/60 bg-bg-primary p-3">
            <div className="text-[11px] uppercase tracking-widest text-text-secondary">If you get stuck</div>
            <p className="mt-2 text-xs text-text-secondary">{stuckMessage}</p>
          </div>
        </div>

        <div className="mt-3 rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[11px] uppercase tracking-widest text-text-secondary">
              {playbook.title}
            </div>
            <button
              type="button"
              onClick={() => runPrimaryAction(playbook.primaryAction)}
              className="rounded border border-accent-info/70 min-h-11 px-3 py-2 text-xs text-accent-info hover:bg-accent-info/15 sm:min-h-0 sm:px-2 sm:py-1 sm:text-[11px]"
            >
              {primaryActionLabel}
            </button>
          </div>
          <p className="mt-2 text-xs text-text-secondary">{playbook.summary}</p>
          <ol className="mt-2 list-decimal space-y-1 pl-4">
            {playbook.steps.slice(0, 4).map((step, index) => (
              <li key={`${step.text}-${index}`}>{step.text}</li>
            ))}
          </ol>
        </div>

        <div className="mt-3 rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[11px] uppercase tracking-widest text-text-secondary">
              Role path: {rolePath.label}
            </div>
            <button
              type="button"
              onClick={() => runPrimaryAction(rolePath.recommendedAction)}
              className="rounded border border-accent-info/70 min-h-11 px-3 py-2 text-xs text-accent-info hover:bg-accent-info/15 sm:min-h-0 sm:px-2 sm:py-1 sm:text-[11px]"
            >
              Recommended: {playbookActionLabel(rolePath.recommendedAction)}
            </button>
          </div>
          <p className="mt-2 text-xs text-text-secondary">{rolePath.summary}</p>
          <ul className="mt-2 list-disc space-y-1 pl-4">
            {rolePath.checkpoints.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>

        <div className="mt-3 rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
          <div className="text-[11px] uppercase tracking-widest text-text-secondary">Canonical run flow</div>
          <ol className="mt-2 list-decimal space-y-1 pl-4">
            <li>Choose task and model.</li>
            <li>Click <span className="text-text-primary">Run arena</span>.</li>
            <li>Wait for all scaffold panels to complete.</li>
            <li>Review score, cost, and time together.</li>
            <li>Run proof comparison and export report.</li>
          </ol>
        </div>

        <details className="mt-3 rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
          <summary className="cursor-pointer text-[11px] uppercase tracking-widest text-text-secondary">
            Quick glossary
          </summary>
          <dl className="mt-2 space-y-2">
            <div>
              <dt className="text-text-primary">Scaffold</dt>
              <dd>Execution strategy wrapped around the same base model prompt.</dd>
            </div>
            <div>
              <dt className="text-text-primary">Autopsy</dt>
              <dd>Failure analysis that surfaces concrete misses and a candidate patch.</dd>
            </div>
            <div>
              <dt className="text-text-primary">Proof comparison</dt>
              <dd>
                Three-case validation showing why the selected orchestration wins on value.
              </dd>
            </div>
            <div>
              <dt className="text-text-primary">Safe fallback mode</dt>
              <dd>
                Continue with history/results/report workflows while live run blockers are resolved.
              </dd>
            </div>
          </dl>
        </details>

        <details className="mt-3 rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
          <summary className="cursor-pointer text-[11px] uppercase tracking-widest text-text-secondary">
            Inline diagnostics
          </summary>
          <div className="mt-2 space-y-1">
            <div>Blocker: {diagnostics.blocker}</div>
            <div>Error class: {diagnostics.errorKind}</div>
            <div>Connection state: {diagnostics.connectionState}</div>
            <div>Online: {diagnostics.online ? 'yes' : 'no'}</div>
            <div>Token configured: {diagnostics.tokenConfigured ? 'yes' : 'no'}</div>
            {errorMessage && (
              <pre className="mt-2 whitespace-pre-wrap rounded border border-border/50 bg-bg-secondary p-2 text-[11px] text-text-muted">
                {errorMessage}
              </pre>
            )}
          </div>
        </details>
    </Modal>
  )
}
