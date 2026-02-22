import { classifyApiError, type ErrorKind } from '../../errors/classify'

type TaskKind = 'extraction' | 'risk' | 'research' | 'custom'

export type HelpBlocker =
  | 'none'
  | 'offline'
  | 'retrying'
  | 'failed'
  | ErrorKind

export type PlaybookAction =
  | 'open_settings'
  | 'retry'
  | 'wait'
  | 'open_tour'
  | 'open_shortcuts'
  | 'run'

export interface PlaybookStep {
  text: string
  action?: PlaybookAction
}

export interface TroubleshootingPlaybook {
  task: TaskKind
  blocker: HelpBlocker
  title: string
  summary: string
  primaryAction: PlaybookAction
  steps: PlaybookStep[]
}

interface ResolveHelpBlockerInput {
  isOnline: boolean
  connectionState: 'idle' | 'connected' | 'retrying' | 'failed'
  hasApiToken: boolean
  errorMessage: string | null
}

const TASK_STEPS: Record<TaskKind, string[]> = {
  extraction: [
    'Verify schema shape and every required field before rerunning.',
    'Check missing required fields in the output and tighten extraction instructions.',
    'Confirm field naming exactly matches the expected schema contract.',
  ],
  risk: [
    'Ensure risk severity is explicit for each flagged issue.',
    'Re-check must-flag clauses and reduce false positives in recommendations.',
    'Confirm response structure complies with the required risk format.',
  ],
  research: [
    'Ensure every key claim is supported with citations.',
    'Re-check required findings coverage before comparing scaffolds.',
    'Verify synthesis is concise and recommendation quality is actionable.',
  ],
  custom: [
    'Validate your custom task prompt and expected schema together.',
    'If schema is used, confirm it is valid JSON and fields are explicit.',
    'Run once with conservative temperature before broader comparisons.',
  ],
}

const BLOCKER_STEPS: Record<HelpBlocker, PlaybookStep[]> = {
  none: [
    {
      text: 'Run the guided tour once, then execute one full benchmark run.',
      action: 'open_tour',
    },
    {
      text: 'Use the checklist panel and complete the next highlighted step.',
      action: 'run',
    },
  ],
  offline: [
    {
      text: 'Reconnect to the internet, then retry the run action.',
      action: 'retry',
    },
    {
      text: 'If connectivity is unstable, wait for a steady connection before rerunning.',
      action: 'wait',
    },
  ],
  retrying: [
    {
      text: 'Wait while the stream reconnects before starting a new run.',
      action: 'wait',
    },
    {
      text: 'If retries exceed one minute, use Retry in the warning banner.',
      action: 'retry',
    },
  ],
  failed: [
    {
      text: 'Use Retry first, then rerun only after stream health recovers.',
      action: 'retry',
    },
    {
      text: 'If failure repeats, open guided tour and confirm the canonical run flow.',
      action: 'open_tour',
    },
  ],
  auth: [
    {
      text: 'Open settings and configure a valid API token.',
      action: 'open_settings',
    },
    {
      text: 'After saving token values, retry the run from Arena.',
      action: 'retry',
    },
  ],
  rate_limit: [
    {
      text: 'Pause briefly, then retry to allow provider limits to reset.',
      action: 'wait',
    },
    {
      text: 'Lower token and timeout settings if repeated limits occur.',
      action: 'open_settings',
    },
  ],
  validation: [
    {
      text: 'Check task inputs, custom schema JSON, and selected options.',
      action: 'open_settings',
    },
    {
      text: 'Rerun after fixing invalid fields or malformed schema.',
      action: 'retry',
    },
  ],
  server: [
    {
      text: 'Retry once after a short delay to clear transient backend issues.',
      action: 'retry',
    },
    {
      text: 'If persistent, use guided tour and confirm full setup before rerun.',
      action: 'open_tour',
    },
  ],
  network: [
    {
      text: 'Stabilize network access, then retry the same run context.',
      action: 'retry',
    },
    {
      text: 'Use shortcuts/help to avoid losing flow while reconnecting.',
      action: 'open_shortcuts',
    },
  ],
  unknown: [
    {
      text: 'Retry once and capture the exact error message for diagnosis.',
      action: 'retry',
    },
    {
      text: 'Use guided tour to validate each run-flow step and isolate the break.',
      action: 'open_tour',
    },
  ],
}

function normalizeTask(taskId: string): TaskKind {
  if (taskId === 'extraction' || taskId === 'risk' || taskId === 'research') {
    return taskId
  }
  return 'custom'
}

export function resolveHelpBlocker({
  isOnline,
  connectionState,
  hasApiToken,
  errorMessage,
}: ResolveHelpBlockerInput): HelpBlocker {
  if (!isOnline) return 'offline'
  if (connectionState === 'retrying') return 'retrying'
  if (connectionState === 'failed') return 'failed'
  if (!hasApiToken) return 'auth'
  if (!errorMessage) return 'none'
  return classifyApiError(errorMessage).kind
}

export function getTaskPlaybook(
  taskId: string,
  blocker: HelpBlocker,
): TroubleshootingPlaybook {
  const task = normalizeTask(taskId)
  const base = TASK_STEPS[task].map((text) => ({ text }))
  const blockerSteps = BLOCKER_STEPS[blocker]
  const steps = [...blockerSteps, ...base]
  const title =
    blocker === 'none'
      ? `${task[0].toUpperCase()}${task.slice(1)} success playbook`
      : `${task[0].toUpperCase()}${task.slice(1)} recovery playbook`
  const summary =
    blocker === 'none'
      ? 'Follow these steps to complete your first run with no guesswork.'
      : 'Follow these steps in order to clear the blocker and continue.'
  const primaryAction = blockerSteps[0]?.action ?? 'open_tour'
  return {
    task,
    blocker,
    title,
    summary,
    primaryAction,
    steps,
  }
}

export function playbookActionLabel(action: PlaybookAction): string {
  switch (action) {
    case 'open_settings':
      return 'Open settings now'
    case 'retry':
      return 'Retry now'
    case 'wait':
      return 'Acknowledge and wait'
    case 'open_tour':
      return 'Open guided tour now'
    case 'open_shortcuts':
      return 'Open shortcuts now'
    case 'run':
      return 'Run arena now'
  }
}
