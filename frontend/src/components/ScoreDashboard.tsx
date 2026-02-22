import { memo, useMemo, useState } from 'react'
import type { RunResults, EvalResult, RunMetrics } from '../types'
import { COPY } from '../content/copy'
import { Button } from './primitives/Button'
import { Icon } from './primitives/Icon'

interface ScoreDashboardProps {
  results: RunResults
  winnerId: string | null
  isCached?: boolean
  scaffoldNames?: Record<string, string>
  onRunComparison: (winningScaffoldId: string) => void
  onRunAutopsy: (scaffoldId: string) => void
  onExportReport?: () => void
  onExportJson?: () => void
  onShare?: () => void
}

interface RankedEntry {
  scaffoldId: string
  score: number
  metrics: RunMetrics
  evaluation: EvalResult
  hasEvaluation: boolean
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

const EMPTY_METRICS: RunMetrics = {
  input_tokens: 0,
  output_tokens: 0,
  cost_usd: 0,
  wall_time_ms: 0,
  num_api_calls: 0,
}

const EMPTY_EVALUATION: EvalResult = {
  total_score: 0,
  breakdown: {},
  weights: {},
  notes: [],
  judge: null,
}

interface TooltipProps {
  evaluation: EvalResult
  id: string
}

const BreakdownTooltip = memo(function BreakdownTooltip({ evaluation, id }: TooltipProps) {
  const entries = Object.entries(evaluation.breakdown)

  return (
    <div
      id={id}
      role="tooltip"
      className="absolute z-10 bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 rounded border border-border bg-bg-primary p-3 shadow-lg"
    >
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
})

interface ScoreCellProps {
  scaffoldId: string
  score: number
  evaluation: EvalResult
}

const ScoreCell = memo(function ScoreCell({ scaffoldId, score, evaluation }: ScoreCellProps) {
  const [visible, setVisible] = useState(false)
  const tooltipId = `score-tooltip-${scaffoldId}`

  return (
    <td
      className="relative px-4 py-3 tabular-nums font-mono text-sm"
    >
      <button
        type="button"
        className="cursor-default underline decoration-dotted decoration-text-secondary focus:outline-none focus:ring-1 focus:ring-accent-info rounded px-1"
        aria-describedby={visible ? tooltipId : undefined}
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setVisible(false)
            ;(e.currentTarget as HTMLButtonElement).blur()
          }
        }}
      >
        {score.toFixed(1)}
      </button>
      {visible && <BreakdownTooltip id={tooltipId} evaluation={evaluation} />}
    </td>
  )
})

export const ScoreDashboard = memo(function ScoreDashboard({
  results,
  winnerId,
  isCached = false,
  scaffoldNames,
  onRunComparison,
  onRunAutopsy,
  onExportReport,
  onExportJson,
  onShare,
}: ScoreDashboardProps) {
  const ranked: RankedEntry[] = useMemo(
    () =>
      Object.entries(results)
        .map(([scaffoldId, result]) => {
          const hasEvaluation =
            !!result.evaluation &&
            Number.isFinite((result.evaluation as EvalResult).total_score)
          const evaluation = hasEvaluation
            ? (result.evaluation as EvalResult)
            : EMPTY_EVALUATION
          const metrics = result.metrics ?? EMPTY_METRICS
          return {
            scaffoldId,
            score: evaluation.total_score,
            metrics,
            evaluation,
            hasEvaluation,
          }
        })
        .sort((a, b) => b.score - a.score),
    [results],
  )

  const winner = winnerId
    ? ranked.find((entry) => entry.scaffoldId === winnerId) ?? null
    : null

  return (
    <div className="rounded-lg border border-border bg-bg-secondary p-6">
      <h2 className="font-mono text-sm font-semibold uppercase tracking-wider text-text-secondary mb-4">
        Results
        {isCached && (
          <span className="ml-2 rounded border border-accent-info/50 bg-accent-info/10 px-2 py-0.5 text-[10px] text-accent-info">
            Cached
          </span>
        )}
      </h2>

      <div className="space-y-3 md:hidden">
        {ranked.map((entry, index) => {
          const isWinner = entry.scaffoldId === winnerId
          return (
            <article
              key={entry.scaffoldId}
              className={[
                'rounded border p-3',
                isWinner
                  ? 'border-accent-winner/50 bg-accent-winner/10'
                  : 'border-border bg-bg-primary',
              ].join(' ')}
            >
              <div className="flex items-center justify-between text-xs">
                <div className="text-text-primary">
                  {index + 1}. {scaffoldNames?.[entry.scaffoldId] ?? entry.scaffoldId}
                </div>
                <div className="font-mono tabular-nums text-text-primary">
                  {entry.score.toFixed(1)}
                </div>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-text-secondary">
                <div>Cost {formatCost(entry.metrics.cost_usd)}</div>
                <div>Time {formatTime(entry.metrics.wall_time_ms)}</div>
                <div>Tok {formatTokens(entry.metrics).toLocaleString()}</div>
              </div>
              {!isWinner && entry.hasEvaluation && (
                <Button
                  type="button"
                  aria-label={`Run autopsy for ${scaffoldNames?.[entry.scaffoldId] ?? entry.scaffoldId}`}
                  onClick={() => onRunAutopsy(entry.scaffoldId)}
                  className="mt-3 border-border px-2 py-1 text-xs"
                >
                  Autopsy
                </Button>
              )}
            </article>
          )
        })}
      </div>

      <div className="hidden overflow-x-auto rounded border border-border md:block">
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
                  <ScoreCell scaffoldId={entry.scaffoldId} score={entry.score} evaluation={entry.evaluation} />
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
                    {!isWinner && entry.hasEvaluation && (
                      <Button
                        onClick={() => onRunAutopsy(entry.scaffoldId)}
                        aria-label={`Run autopsy for ${scaffoldNames?.[entry.scaffoldId] ?? entry.scaffoldId}`}
                        className="border-border px-2 py-1 text-xs"
                      >
                        Autopsy
                      </Button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex gap-3 flex-wrap">
        <Button
          onClick={() => winner && onRunComparison(winner.scaffoldId)}
          disabled={!winner}
          aria-label="Run proof comparison for winning scaffold"
          tone="primary"
          className="px-4 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5">
            <Icon name="leaderboard" className="h-3 w-3" />
            Run Proof Comparison
          </span>
        </Button>
        <Button
          onClick={onExportReport}
          disabled={!onExportReport}
          aria-label="Export markdown and PDF report"
          className="px-4 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5">
            <Icon name="download" className="h-3 w-3" />
            {COPY.actions.exportReport}
          </span>
        </Button>
        <Button
          onClick={onExportJson}
          disabled={!onExportJson}
          aria-label="Export JSON results"
          className="px-4 py-2 text-sm"
        >
          {COPY.actions.exportJson}
        </Button>
        <Button
          onClick={onShare}
          disabled={!onShare}
          aria-label="Copy share link"
          className="px-4 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5">
            <Icon name="share" className="h-3 w-3" />
            {COPY.actions.share}
          </span>
        </Button>
      </div>
    </div>
  )
})
