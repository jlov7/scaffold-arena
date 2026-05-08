import { memo, useMemo, useState } from 'react'
import { Award, Download, FileJson, GitCompareArrows, Share2, Stethoscope } from 'lucide-react'
import type { RunResults, EvalResult, RunMetrics } from '../types'
import { COPY } from '../content/copy'
import { Button } from './primitives/Button'
import { Metric } from './primitives/Metric'
import { StatusBadge } from './primitives/StatusBadge'

interface ScoreDashboardProps {
  results: RunResults
  winnerId: string | null
  isCached?: boolean
  scaffoldNames?: Record<string, string>
  onRunComparison: (winningScaffoldId: string) => void
  onRunAutopsy: (scaffoldId: string) => void
  onExportReport?: () => void
  onExportBundle?: () => void
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
  onExportBundle,
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
    <div className="lab-panel p-5">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="lab-label">Decision register</div>
          <h2 className="mt-1 text-xl font-semibold tracking-[-0.01em] text-text-primary">
            Results register
          </h2>
        </div>
        {isCached && <StatusBadge tone="info">Cached</StatusBadge>}
      </div>

      {winner && (
        <div className="mb-5 grid gap-3 lg:grid-cols-[1.2fr_repeat(3,minmax(0,0.7fr))]">
          <div className="lab-row flex items-center gap-3 px-3 py-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-accent-winner/35 bg-accent-winner/10 text-accent-winner">
              <Award className="h-5 w-5" strokeWidth={1.8} />
            </div>
            <div className="min-w-0">
              <div className="lab-label">Winner</div>
              <div className="truncate text-base font-semibold text-text-primary">
                {scaffoldNames?.[winner.scaffoldId] ?? winner.scaffoldId}
              </div>
            </div>
          </div>
          <Metric
            label="Score"
            value={winner.score.toFixed(1)}
            detail="Total evaluation"
            tone="success"
          />
          <Metric
            label="Cost"
            value={formatCost(winner.metrics.cost_usd)}
            detail="Provider usage"
          />
          <Metric
            label="Time"
            value={formatTime(winner.metrics.wall_time_ms)}
            detail={`${formatTokens(winner.metrics).toLocaleString()} tokens`}
          />
        </div>
      )}

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

      <div className="hidden overflow-x-auto rounded-md border border-border md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-bg-primary/55">
              <th className="px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">Rank</th>
              <th className="px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">Scaffold</th>
              <th className="px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">Score</th>
              <th className="px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">Cost</th>
              <th className="px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">Time</th>
              <th className="px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted">Tokens</th>
              <th className="px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-text-muted"></th>
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
                    isWinner ? 'bg-accent-winner/7' : ''
                  }`}
                >
                  <td className="px-4 py-3 font-mono tabular-nums text-text-secondary">
                    {rank}.
                  </td>
                  <td className="px-4 py-3">
                    <span className={[
                      'inline-flex items-center gap-2',
                      isWinner ? 'font-semibold text-accent-winner' : 'text-text-primary',
                    ].join(' ')}>
                      {isWinner && <Award className="h-4 w-4" aria-label="Winner" strokeWidth={1.8} />}
                      {scaffoldNames?.[entry.scaffoldId] ?? entry.scaffoldId}
                    </span>
                  </td>
                  <ScoreCell scaffoldId={entry.scaffoldId} score={entry.score} evaluation={entry.evaluation} />
                  <td className="px-4 py-3 font-mono tabular-nums text-text-primary">
                    {formatCost(entry.metrics.cost_usd)}
                  </td>
                  <td className="px-4 py-3 font-mono tabular-nums text-text-primary">
                    {formatTime(entry.metrics.wall_time_ms)}
                  </td>
                  <td className="px-4 py-3 font-mono tabular-nums text-text-primary">
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

      <div className="mt-5 flex flex-wrap gap-3 border-t border-border pt-4">
        <Button
          onClick={() => winner && onRunComparison(winner.scaffoldId)}
          disabled={!winner}
          aria-label="Run proof comparison for winning scaffold"
          tone="primary"
          className="px-4 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5">
            <GitCompareArrows className="h-4 w-4" strokeWidth={1.8} />
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
            <Download className="h-4 w-4" strokeWidth={1.8} />
            {COPY.actions.exportReport}
          </span>
        </Button>
        <Button
          onClick={onExportBundle}
          disabled={!onExportBundle}
          aria-label="Download export bundle"
          className="px-4 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5">
            <Stethoscope className="h-4 w-4" strokeWidth={1.8} />
            Export Bundle
          </span>
        </Button>
        <Button
          onClick={onExportJson}
          disabled={!onExportJson}
          aria-label="Export JSON results"
          className="px-4 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5">
            <FileJson className="h-4 w-4" strokeWidth={1.8} />
            {COPY.actions.exportJson}
          </span>
        </Button>
        <Button
          onClick={onShare}
          disabled={!onShare}
          aria-label="Copy share link"
          className="px-4 py-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5">
            <Share2 className="h-4 w-4" strokeWidth={1.8} />
            {COPY.actions.share}
          </span>
        </Button>
      </div>
    </div>
  )
})
