import { memo } from 'react'

import { COPY } from '../content/copy'
import { Button } from './primitives/Button'
import { Card } from './primitives/Card'
import { StatusBadge } from './primitives/StatusBadge'

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
  if (!ts) return '-'
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
    <Card title="Run History">
      {runs.length === 0 ? (
        <div className="lab-panel-inset p-4">
          <div className="text-sm font-semibold text-text-primary">{COPY.labels.noRuns}</div>
          <div className="mt-1 text-sm text-text-secondary">
            Start an arena run to capture your first benchmark and compare scaffold performance over time.
          </div>
          {onStartFirstRun && (
            <Button
              type="button"
              onClick={onStartFirstRun}
              tone="primary"
              className="mt-3"
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
                className="ui-control w-full rounded-md border border-border/70 bg-bg-primary px-3 py-3 text-left hover:border-accent-info"
              >
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate font-semibold capitalize text-text-primary">
                    {run.task_id.replace(/_/g, ' ')}
                  </span>
                  <StatusBadge
                    tone={
                      run.status === 'completed'
                        ? 'success'
                        : run.status === 'failed'
                          ? 'danger'
                          : 'neutral'
                    }
                  >
                    {run.status}
                  </StatusBadge>
                </div>
                <div className="mt-2 flex items-center gap-2 font-mono text-xs text-text-muted">
                  <span>{run.model_id}</span>
                  <span className="text-border">&middot;</span>
                  <time title={new Date((run.completed_at ?? run.created_at ?? 0) * 1000).toLocaleString()}>
                    {formatRelativeTime(run.completed_at ?? run.created_at)}
                  </time>
                </div>
                <div className="mt-2 flex items-center justify-between text-xs">
                  {run.winner_id ? (
                    <span className="text-accent-winner">Winner: {run.winner_id}</span>
                  ) : (
                    <span className="text-text-muted">No winner</span>
                  )}
                  {bestScore !== null && (
                    <span className="font-mono tabular-nums font-semibold text-text-primary">{bestScore.toFixed(1)}</span>
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
