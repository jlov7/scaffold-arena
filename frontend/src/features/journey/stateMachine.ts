import type { RunResults } from '../../types'

export type JourneyStage = 'setup' | 'running' | 'review' | 'iterate'

export interface JourneySignals {
  isRunning: boolean
  hasEverRun: boolean
  finalResults: RunResults | null
  comparisonCount: number
  autopsyOpen: boolean
  hasExported: boolean
}

export interface JourneyTransition {
  from: JourneyStage
  to: JourneyStage
  guard: string
}

export const CANONICAL_HAPPY_PATH: JourneyStage[] = [
  'setup',
  'running',
  'review',
  'iterate',
]

export const JOURNEY_TRANSITIONS: JourneyTransition[] = [
  { from: 'setup', to: 'running', guard: 'run starts' },
  { from: 'running', to: 'review', guard: 'results completed' },
  { from: 'review', to: 'iterate', guard: 'comparison or autopsy begins' },
]

export function resolveJourneyStage({
  isRunning,
  hasEverRun,
  finalResults,
  comparisonCount,
  autopsyOpen,
  hasExported,
}: JourneySignals): JourneyStage {
  if (isRunning) return 'running'
  if (finalResults && (comparisonCount > 0 || autopsyOpen || hasExported)) return 'iterate'
  if (finalResults) return 'review'
  return hasEverRun ? 'review' : 'setup'
}
