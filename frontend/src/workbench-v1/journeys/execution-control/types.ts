import type { ExecutionDetail, ExecutionEvent, ExecutionProvenance, PreflightReport } from '../../../api/v1/client'

export type ExecutionMode = 'guided' | 'lab'

export type ExecutionRemoteState = 'loading' | 'ready' | 'empty' | 'offline' | 'permission' | 'error'

export interface ExecutionControlInput {
  /** This ID is supplied only after the caller has selected a persisted frozen experiment. */
  frozenExperimentId: string | null
  /** The caller owns preflight; this surface never substitutes or fabricates a report. */
  preflightReport: PreflightReport | null
  /** URL-owned identity; it must never silently select a different execution. */
  requestedExecutionId?: string | null
}

export interface ExecutionActivity {
  event: ExecutionEvent
  receivedAt: string
}

export type ProvenanceDraft = ExecutionProvenance

export interface ExecutionSelection {
  execution: ExecutionDetail | null
  events: ExecutionActivity[]
}
