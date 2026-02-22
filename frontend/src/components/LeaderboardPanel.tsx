import { memo } from 'react'

import type { LeaderboardStats } from '../types'
import { Button } from './primitives/Button'
import { Card } from './primitives/Card'

interface LeaderboardPanelProps {
  stats: LeaderboardStats | null
  scaffoldNames: Record<string, string>
  onStartRun?: () => void
}

function displayTaskName(taskId: string): string {
  switch (taskId) {
    case 'extraction':
      return 'Extraction'
    case 'risk':
      return 'Risk'
    case 'research':
      return 'Research'
    default:
      return taskId
  }
}

function LeaderboardPanel({
  stats,
  scaffoldNames,
  onStartRun,
}: LeaderboardPanelProps) {
  const runCount = stats?.run_count ?? 0
  if (!stats || runCount < 3) {
    return (
      <Card title="Leaderboard" className="font-mono">
        <div className="mt-2 text-xs text-text-muted">
          Run at least 3 arenas to see stats
        </div>
        <div className="mt-1 text-[11px] text-text-muted">
          Once you have enough runs, this view highlights consistent winners by score and cost.
        </div>
        {onStartRun && (
          <Button
            type="button"
            onClick={onStartRun}
            tone="primary"
            className="mt-3 text-[11px]"
          >
            Run arena now
          </Button>
        )}
      </Card>
    )
  }

  return (
    <Card className="font-mono">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-xs uppercase tracking-widest text-text-secondary">
          Leaderboard
        </div>
        <div className="text-[10px] text-text-muted">
          {runCount} runs
        </div>
      </div>

      <div className="space-y-3">
        {stats.scaffolds.map((row) => (
          <div key={row.scaffold_id} className="rounded border border-border/60 bg-bg-primary p-3">
            <div className="flex items-center justify-between text-xs">
              <span className="text-text-primary">
                {scaffoldNames[row.scaffold_id] ?? row.scaffold_id}
              </span>
              <span className="text-text-secondary">
                Win rate {row.win_rate.toFixed(1)}%
              </span>
            </div>
            <div className="mt-2 h-2 rounded bg-bg-secondary">
              <div
                className="h-2 rounded bg-accent-winner"
                style={{ width: `${Math.min(100, row.avg_score)}%` }}
              />
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-text-muted">
              <span>Avg score {row.avg_score.toFixed(1)}</span>
              <span>Avg cost ${row.avg_cost.toFixed(4)}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded border border-border/60 bg-bg-primary p-3">
        <div className="text-[11px] uppercase tracking-widest text-text-secondary">
          Avg Score By Task
        </div>
        <div className="mt-2 space-y-2">
          {Object.entries(stats.by_task).map(([taskId, rows]) => (
            <div key={taskId}>
              <div className="text-[11px] text-text-muted">{displayTaskName(taskId)}</div>
              <div className="mt-1 grid gap-1">
                {rows.map((row) => (
                  <div key={`${taskId}-${row.scaffold_id}`} className="flex items-center justify-between text-[11px]">
                    <span className="text-text-secondary">
                      {scaffoldNames[row.scaffold_id] ?? row.scaffold_id}
                    </span>
                    <span className="text-text-primary">
                      {row.avg_score.toFixed(1)} ({row.samples})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 rounded border border-border/60 bg-bg-primary p-3">
        <div className="text-[11px] uppercase tracking-widest text-text-secondary">
          Score Distribution
        </div>
        <div className="mt-2 space-y-3">
          {stats.distributions.map((dist) => {
            const maxCount = Math.max(1, ...dist.bins.map((bin) => bin.count))
            return (
              <div key={dist.scaffold_id}>
                <div className="text-[11px] text-text-secondary">
                  {scaffoldNames[dist.scaffold_id] ?? dist.scaffold_id}
                </div>
                <div className="mt-1 grid grid-cols-5 gap-1">
                  {dist.bins.map((bin) => (
                    <div key={`${dist.scaffold_id}-${bin.label}`}>
                      <div className="h-12 rounded border border-border/50 bg-bg-secondary p-1 flex items-end">
                        <div
                          className="w-full rounded bg-accent-info/60"
                          style={{ height: `${(bin.count / maxCount) * 100}%` }}
                        />
                      </div>
                      <div className="mt-1 text-center text-[10px] text-text-muted">{bin.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </Card>
  )
}

export default memo(LeaderboardPanel)
