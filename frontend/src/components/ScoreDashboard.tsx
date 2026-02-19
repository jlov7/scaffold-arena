import { useState } from 'react'
import type { RunResults, EvalResult, RunMetrics } from '../types'

interface ScoreDashboardProps {
  results: RunResults
  winnerId: string | null
  scaffoldNames?: Record<string, string>
  onRunComparison: (winningScaffoldId: string) => void
  onRunAutopsy: (scaffoldId: string) => void
  onExportReport?: () => void
}

interface RankedEntry {
  scaffoldId: string
  score: number
  metrics: RunMetrics
  evaluation: EvalResult
}

function formatCost(usd: number): string {
  return '$' + usd.toFixed(3)
}

function formatTime(ms: number): string {
  return (ms / 1000).toFixed(1) + 's'
}

function formatTokens(metrics: RunMetrics): number {
  return metrics.input_tokens + metrics.output_tokens
}

interface TooltipProps {
  evaluation: EvalResult
}

function BreakdownTooltip({ evaluation }: TooltipProps) {
  const entries = Object.entries(evaluation.breakdown)

  return (
    <div className="absolute z-10 bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 rounded border border-border bg-bg-primary p-3 shadow-lg">
      <p className="font-mono text-xs text-text-secondary mb-2 uppercase tracking-wider">Score Breakdown</p>
      <div className="space-y-1">
        {entries.map(([metric, score]) => {
          const weight = evaluation.weights[metric]?.weight ?? null
          return (
            <div key={metric} className="flex items-center justify-between gap-3">
              <span className="font-mono text-xs text-text-secondary truncate">{metric}</span>
              <span className="font-mono text-xs tabular-nums text-text-primary shrink-0">
                {score.toFixed(1)}
                {weight !== null && (
                  <span className="text-text-secondary"> ×{weight}</span>
                )}
              </span>
            </div>
          )
        })}
      </div>
      {evaluation.notes.length > 0 && (
        <div className="mt-2 pt-2 border-t border-border">
          {evaluation.notes.slice(0, 2).map((note, i) => (
            <p key={i} className="font-mono text-xs text-text-secondary truncate">{note}</p>
          ))}
        </div>
      )}
    </div>
  )
}

interface ScoreCellProps {
  score: number
  evaluation: EvalResult
}

function ScoreCell({ score, evaluation }: ScoreCellProps) {
  const [hovered, setHovered] = useState(false)

  return (
    <td
      className="relative px-4 py-3 tabular-nums font-mono text-sm cursor-default"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span className="underline decoration-dotted decoration-text-secondary">
        {score.toFixed(1)}
      </span>
      {hovered && <BreakdownTooltip evaluation={evaluation} />}
    </td>
  )
}

export function ScoreDashboard({
  results,
  winnerId,
  scaffoldNames,
  onRunComparison,
  onRunAutopsy,
  onExportReport,
}: ScoreDashboardProps) {
  const ranked: RankedEntry[] = Object.entries(results)
    .map(([scaffoldId, result]) => ({
      scaffoldId,
      score: result.evaluation.total_score,
      metrics: result.metrics,
      evaluation: result.evaluation,
    }))
    .sort((a, b) => b.score - a.score)

  const winner = ranked[0] ?? null

  return (
    <div className="rounded-lg border border-border bg-bg-secondary p-6">
      <h2 className="font-mono text-sm font-semibold uppercase tracking-wider text-text-secondary mb-4">
        Results
      </h2>

      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full font-mono text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2 text-left text-text-secondary font-normal">Rank</th>
              <th className="px-4 py-2 text-left text-text-secondary font-normal">Scaffold</th>
              <th className="px-4 py-2 text-left text-text-secondary font-normal">Score</th>
              <th className="px-4 py-2 text-left text-text-secondary font-normal">Cost</th>
              <th className="px-4 py-2 text-left text-text-secondary font-normal">Time</th>
              <th className="px-4 py-2 text-left text-text-secondary font-normal">Tok</th>
              <th className="px-4 py-2 text-left text-text-secondary font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((entry, index) => {
              const isWinner = entry.scaffoldId === winnerId
              const rank = index + 1

              return (
                <tr
                  key={entry.scaffoldId}
                  className={`border-b border-border last:border-b-0 ${
                    isWinner ? 'bg-bg-tertiary' : ''
                  }`}
                >
                  <td className="px-4 py-3 tabular-nums text-text-secondary">
                    {rank}.
                  </td>
                  <td className="px-4 py-3">
                    <span className={isWinner ? 'text-accent-winner font-semibold' : 'text-text-primary'}>
                      {isWinner && (
                        <span className="mr-2" aria-label="Winner">&#x1F3C6;</span>
                      )}
                      {scaffoldNames?.[entry.scaffoldId] ?? entry.scaffoldId}
                    </span>
                  </td>
                  <ScoreCell score={entry.score} evaluation={entry.evaluation} />
                  <td className="px-4 py-3 tabular-nums text-text-primary">
                    {formatCost(entry.metrics.cost_usd)}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-text-primary">
                    {formatTime(entry.metrics.wall_time_ms)}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-text-primary">
                    {formatTokens(entry.metrics).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    {!isWinner && (
                      <button
                        onClick={() => onRunAutopsy(entry.scaffoldId)}
                        className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:border-accent-loser hover:text-accent-loser transition-colors"
                      >
                        Autopsy
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex gap-3 flex-wrap">
        <button
          onClick={() => winner && onRunComparison(winner.scaffoldId)}
          disabled={!winner}
          className="rounded border border-accent-info px-4 py-2 font-mono text-sm text-accent-info hover:bg-accent-info hover:text-bg-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Run Proof Comparison
        </button>
        <button
          onClick={onExportReport}
          disabled={!onExportReport}
          className="rounded border border-border px-4 py-2 font-mono text-sm text-text-secondary hover:border-text-secondary hover:text-text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Export Report
        </button>
      </div>
    </div>
  )
}
