import { memo } from 'react'

import { COPY } from '../content/copy'
import { Button } from './primitives/Button'
import { Card } from './primitives/Card'

interface RunHistoryItem {
  run_id: string
  kind: string
  task_id: string
  model_id: string
  status: string
  created_at?: number
  completed_at?: number
  winner_id?: string | null
  results?: Record<string, unknown>
}

interface RunHistoryPanelProps {
  runs: RunHistoryItem[]
  onLoadRun: (runId: string) => void
  onStartFirstRun?: () => void
}

function formatRelativeTime(ts?: number): string {
  if (!ts) return '—'
  const now = Date.now()
  const diffMs = now - ts * 1000
  const diffSec = Math.floor(diffMs / 1000)

  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`

  return new Date(ts * 1000).toLocaleDateString()
}

function topScore(results?: Record<string, unknown>): number | null {
  if (!results) return null
  let best: number | null = null
  for (const value of Object.values(results)) {
    if (!value || typeof value !== 'object') continue
    const evaluation = (value as { evaluation?: { total_score?: number } }).evaluation
    const score = evaluation?.total_score
    if (typeof score !== 'number') continue
    if (best === null || score > best) best = score
  }
  return best
}

function RunHistoryPanel({
  runs,
  onLoadRun,
  onStartFirstRun,
}: RunHistoryPanelProps) {
  return (
    <Card title="Run History" className="font-mono">
      {runs.length === 0 ? (
        <div className="rounded border border-border/60 bg-bg-primary p-3">
          <div className="text-xs text-text-secondary">{COPY.labels.noRuns}</div>
          <div className="mt-1 text-[11px] text-text-muted">
            Start an arena run to capture your first benchmark and compare scaffold performance over time.
          </div>
          {onStartFirstRun && (
            <Button
              type="button"
              onClick={onStartFirstRun}
              tone="primary"
              className="mt-3 text-[11px]"
            >
              Start first run
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => {
            const bestScore = topScore(run.results)
            return (
              <button
                key={run.run_id}
                type="button"
                onClick={() => onLoadRun(run.run_id)}
                className="w-full rounded border border-border/70 bg-bg-primary px-3 py-2 text-left hover:border-accent-info"
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="text-text-primary font-semibold">{run.task_id.replace(/_/g, ' ')}</span>
                  <span className={[
                    'text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5 border',
                    run.status === 'completed'
                      ? 'text-accent-winner border-accent-winner/30 bg-accent-winner/10'
                      : run.status === 'failed'
                        ? 'text-accent-loser border-accent-loser/30 bg-accent-loser/10'
                        : 'text-text-muted border-border',
                  ].join(' ')}>{run.status}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-[11px] text-text-muted">
                  <span>{run.model_id}</span>
                  <span className="text-border">&middot;</span>
                  <time title={new Date((run.completed_at ?? run.created_at ?? 0) * 1000).toLocaleString()}>
                    {formatRelativeTime(run.completed_at ?? run.created_at)}
                  </time>
                </div>
                <div className="mt-1.5 flex items-center justify-between text-[11px]">
                  {run.winner_id ? (
                    <span className="text-accent-winner">Winner: {run.winner_id}</span>
                  ) : (
                    <span className="text-text-muted">No winner</span>
                  )}
                  {bestScore !== null && (
                    <span className="tabular-nums text-text-primary font-semibold">{bestScore.toFixed(1)}</span>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </Card>
  )
}

export default memo(RunHistoryPanel)
