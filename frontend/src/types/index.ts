// --- Meta types ---

export interface ModelMeta {
  id: string
  label: string
  provider: string
  input_usd_per_mtok: number
  output_usd_per_mtok: number
}

export interface TaskMeta {
  id: string
  name: string
  subtitle: string
  type: string
  synthetic_sources?: boolean
}

export interface ScaffoldMeta {
  id: string
  name: string
  subtitle: string
}

export interface AppMeta {
  models: ModelMeta[]
  tasks: TaskMeta[]
  scaffolds: ScaffoldMeta[]
  features: {
    llm_judge: boolean
    pdf_export: boolean
    evaluation_profiles?: Array<'balanced' | 'strict' | 'cost_first'>
  }
  budget?: {
    daily_budget_usd?: number
    spent_today_usd?: number
    remaining_today_usd?: number
    max_cost_per_run_usd?: number
    [key: string]: unknown
  }
}

// --- Run types ---

export interface RunMetrics {
  input_tokens: number
  output_tokens: number
  cost_usd: number
  wall_time_ms: number
  num_api_calls: number
}

export interface EvalBreakdown {
  [metric: string]: number
}

export interface EvalResult {
  total_score: number
  breakdown: EvalBreakdown
  weights: Record<string, { weight: number; type: string }>
  notes: string[]
  judge?: { scores: Record<string, number>; explanation: string; model_id: string } | null
}

export interface ScaffoldResult {
  output: string
  metrics: RunMetrics
  evaluation: EvalResult
  error?: string
}

export type RunResults = Record<string, ScaffoldResult>

// --- SSE event payloads ---

export interface RunStartedEvent {
  run_id: string
  ts_ms: number
  task_id: string
  scaffold_ids: string[]
}

export interface ScaffoldPhaseEvent {
  run_id: string
  ts_ms: number
  scaffold_id: string
  phase: string
}

export interface ScaffoldDeltaEvent {
  run_id: string
  ts_ms: number
  scaffold_id: string
  delta: string
}

export interface ScaffoldCompletedEvent {
  run_id: string
  ts_ms: number
  scaffold_id: string
  output: string
  metrics: RunMetrics
}

export interface EvaluationCompletedEvent {
  run_id: string
  ts_ms: number
  scaffold_id: string
  total_score: number
  breakdown: EvalBreakdown
  weights: Record<string, { weight: number; type: string }>
  notes: string[]
  judge?: { scores: Record<string, number>; explanation: string; model_id: string } | null
}

export interface RunCompleteEvent {
  run_id: string
  ts_ms: number
  winner_scaffold_id: string | null
  results: RunResults
}

export type ArenaSseEvent =
  | { type: 'run_started'; data: RunStartedEvent }
  | { type: 'scaffold_phase'; data: ScaffoldPhaseEvent }
  | { type: 'scaffold_delta'; data: ScaffoldDeltaEvent }
  | { type: 'scaffold_completed'; data: ScaffoldCompletedEvent }
  | { type: 'evaluation_completed'; data: EvaluationCompletedEvent }
  | { type: 'run_complete'; data: RunCompleteEvent }
  | { type: 'heartbeat'; data: { run_id?: string; ts_ms?: number } }

export interface RunTimelineEvent {
  seq: number
  event: string
  ts_ms: number
  scaffold_id?: string | null
  summary: string
}

export interface RunDiagnostics {
  run_id: string
  kind: string
  status: string
  created_at?: number
  completed_at?: number
  duration_ms?: number | null
  task_id: string
  model_id: string
  scaffold_ids: string[]
  options: Record<string, unknown>
  event_count: number
  event_type_counts: Record<string, number>
  scaffold_status: Record<string, string>
  errors: Record<string, string>
  timeline: RunTimelineEvent[]
}

// --- Panel state ---

export type PanelStatus = 'idle' | 'running' | 'completed' | 'failed' | 'winner' | 'loser'

export interface PanelState {
  scaffoldId: string
  scaffoldName: string
  status: PanelStatus
  phase: string
  streamedText: string
  output: string
  metrics: RunMetrics | null
  evaluation: EvalResult | null
  error: string | null
}

export type RunLifecycleState =
  | 'idle'
  | 'preflight'
  | 'streaming'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'cached'

export interface RunSession {
  runId: string | null
  lifecycle: RunLifecycleState
  taskId: string
  modelId: string
  winnerId: string | null
  isCached: boolean
  timeline: RunTimelineEvent[]
}

export interface WorkspaceState {
  view: 'arena' | 'results' | 'history' | 'leaderboard' | 'settings'
  stage: 'setup' | 'running' | 'review' | 'iterate'
  nextActionKey: string
}

export interface InspectorContext {
  title: string
  body: string
  cta: string
  runSession: RunSession
  preflight?: {
    can_run: boolean
    checks: Array<{ id: string; status: string; message: string }>
  } | null
}

// --- Comparison types ---

export interface ComparisonCase {
  case_id: string
  model_id: string
  scaffold_id: string
  metrics?: RunMetrics
  evaluation?: EvalResult
}

// --- Autopsy types ---

export interface AutopsyFailure {
  type: string
  description: string
  severity: string
  evidence: string
}

export interface AutopsyResult {
  failures: AutopsyFailure[]
  patch: Record<string, unknown>
  summary: string
}

// --- Leaderboard / stats types ---

export interface LeaderboardBin {
  label: string
  count: number
}

export interface LeaderboardDistribution {
  scaffold_id: string
  bins: LeaderboardBin[]
}

export interface LeaderboardScaffoldStat {
  scaffold_id: string
  wins: number
  win_rate: number
  avg_score: number
  avg_cost: number
  samples: number
}

export interface LeaderboardTaskStat {
  scaffold_id: string
  avg_score: number
  samples: number
}

export interface LeaderboardStats {
  run_count: number
  scaffolds: LeaderboardScaffoldStat[]
  by_task: Record<string, LeaderboardTaskStat[]>
  distributions: LeaderboardDistribution[]
}
