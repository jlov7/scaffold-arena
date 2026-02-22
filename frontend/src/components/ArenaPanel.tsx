import { memo } from 'react'
import StreamingText from './StreamingText'
import type { PanelState } from '../types'
import { emitAppToast } from '../utils/toast'

interface ArenaPanelProps {
  panel: PanelState
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function formatCost(usd: number): string {
  if (usd < 0.01) return `$${(usd * 100).toFixed(2)}¢`
  return `$${usd.toFixed(3)}`
}

function formatTime(ms: number): string {
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms}ms`
}

const SCAFFOLD_INFO: Record<string, { strategy: string; description: string; calls: string; strength: string }> = {
  bare: {
    strategy: 'Zero Scaffolding',
    description: 'Single API call. No planning, no validation, no self-correction. The control group — every other scaffold is measured against this.',
    calls: '1 API call',
    strength: 'Speed & cost',
  },
  plan_execute_verify: {
    strategy: 'Plan \u2192 Execute \u2192 Verify',
    description: 'Creates an execution plan, follows it to produce output, then self-verifies against requirements. Three phases that prevent the "generate and pray" pattern.',
    calls: '3 API calls',
    strength: 'Structured accuracy',
  },
  tool_error_recovery: {
    strategy: 'Validate + Auto-Repair',
    description: 'Generates output, validates against the JSON schema, and automatically repairs any errors. Loops until valid or max retries reached.',
    calls: '2\u20135 API calls',
    strength: 'Schema compliance',
  },
  memory_critique: {
    strategy: 'Decompose \u2192 Critique \u2192 Refine',
    description: 'Breaks the task into subtasks, solves each independently, synthesizes results, self-critiques for weaknesses, then refines the final output.',
    calls: '5\u20137 API calls',
    strength: 'Output quality',
  },
}

const STATUS_BORDER: Record<PanelState['status'], string> = {
  idle: 'border-border',
  running: 'border-accent-info',
  completed: 'border-border',
  winner: 'border-accent-winner shadow-[0_0_15px_rgba(16,185,129,0.3)]',
  loser: 'border-accent-loser/30',
  failed: 'border-red-500',
}

function ArenaPanelComponent({ panel }: ArenaPanelProps) {
  const { scaffoldId, scaffoldName, status, phase, streamedText, metrics, evaluation, error } = panel
  const info = SCAFFOLD_INFO[scaffoldId]

  const scoreTarget = evaluation?.total_score ?? null
  const animatedScore = scoreTarget ?? 0

  const isRunning = status === 'running'
  const showMetrics = metrics !== null && status !== 'idle' && status !== 'running'
  const showScore = evaluation !== null && status !== 'idle' && status !== 'running'
  const copyableText = panel.output || streamedText
  const hasOutput = copyableText.trim().length > 0
  const showNoOutputState = status !== 'idle' && !isRunning && !hasOutput
  const noOutputMessage =
    status === 'failed'
      ? 'Run failed before output was generated. Open settings, verify credentials, then rerun.'
      : 'No output was captured for this run. Review guidance and rerun for comparison-ready results.'

  async function handleCopy(): Promise<void> {
    if (!copyableText) return
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(copyableText)
      } else {
        const el = document.createElement('textarea')
        el.value = copyableText
        document.body.appendChild(el)
        el.select()
        document.execCommand('copy')
        document.body.removeChild(el)
      }
      emitAppToast({ type: 'success', message: 'Copied to clipboard' })
    } catch {
      emitAppToast({ type: 'error', message: 'Copy failed' })
    }
  }

  const statusLabel =
    status === 'idle' ? `${scaffoldName} ready` :
    status === 'running' ? `${scaffoldName} running` :
    status === 'completed' ? `${scaffoldName} completed` :
    status === 'winner' ? `${scaffoldName} won` :
    status === 'loser' ? `${scaffoldName} lost` :
    status === 'failed' ? `${scaffoldName} failed` : ''

  return (
    <div
      role="region"
      aria-label={scaffoldName}
      className={[
        'group relative flex flex-col bg-bg-secondary border rounded-lg p-4 min-h-[420px] transition-all duration-300',
        STATUS_BORDER[status],
      ].join(' ')}
    >
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {statusLabel}
      </div>
      {copyableText && status !== 'idle' && (
        <button
          type="button"
          onClick={() => void handleCopy()}
          className="absolute right-3 top-3 rounded border border-border bg-bg-primary px-2 py-1 text-[10px] font-mono text-text-secondary opacity-0 transition-opacity hover:border-accent-info hover:text-accent-info focus:opacity-100 group-hover:opacity-100"
        >
          Copy
        </button>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          {isRunning && (
            <span className="shrink-0 w-2 h-2 rounded-full bg-accent-info animate-pulse" />
          )}
          <span className="font-semibold text-text-primary truncate">{scaffoldName}</span>
        </div>

        {status === 'winner' && (
          <span className="shrink-0 ml-2 text-xs font-bold text-accent-winner bg-accent-winner/10 border border-accent-winner/30 rounded px-2 py-0.5">
            WINNER
          </span>
        )}
        {status === 'failed' && (
          <span className="shrink-0 ml-2 text-xs font-bold text-red-400 bg-red-400/10 border border-red-400/30 rounded px-2 py-0.5">
            FAILED
          </span>
        )}
      </div>

      {/* Phase */}
      <div className="text-xs text-text-secondary mb-3 font-mono">
        {isRunning ? (
          <span className="text-accent-info">
            Phase: {phase || 'initializing'} &mdash; Streaming...
          </span>
        ) : phase ? (
          <span>Phase: {phase}</span>
        ) : null}
      </div>

      {/* Streaming output / Idle scaffold info */}
      <div className="flex-1 overflow-hidden mb-3">
        {status === 'idle' ? (
          info ? (
            <div className="flex flex-col justify-center h-full px-1 py-2 space-y-3">
              <div className="text-[10px] text-accent-info uppercase tracking-widest font-mono font-bold">
                {info.strategy}
              </div>
              <p className="text-xs text-text-secondary/80 leading-relaxed">
                {info.description}
              </p>
              <div className="flex items-center gap-3 text-[10px] text-text-muted font-mono mt-auto">
                <span>{info.calls}</span>
                <span className="text-border">|</span>
                <span>Best for: {info.strength}</span>
              </div>
            </div>
          ) : (
            <div className="text-text-secondary text-xs font-mono opacity-40 p-3">Ready</div>
          )
        ) : showNoOutputState ? (
          <div className="rounded border border-border/70 bg-bg-primary p-3 text-xs text-text-secondary leading-relaxed">
            {noOutputMessage}
          </div>
        ) : (
          <StreamingText text={streamedText} isStreaming={isRunning} />
        )}
      </div>

      {/* Error message */}
      {status === 'failed' && error && (
        <div className="text-xs text-red-400 font-mono bg-red-400/10 rounded p-2 mb-3 break-words">
          {error}
        </div>
      )}

      {/* Metrics row */}
      {showMetrics && metrics && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs font-mono text-text-secondary border-t border-border pt-3 mb-2 tabular-nums animate-in fade-in slide-in-from-bottom-1 duration-300">
          <span>
            <span className="text-text-secondary/60">tokens </span>
            <span className="text-text-primary">
              {formatTokens(metrics.input_tokens + metrics.output_tokens)}
            </span>
          </span>
          <span>
            <span className="text-text-secondary/60">cost </span>
            <span className="text-text-primary">{formatCost(metrics.cost_usd)}</span>
          </span>
          <span>
            <span className="text-text-secondary/60">time </span>
            <span className="text-text-primary">{formatTime(metrics.wall_time_ms)}</span>
          </span>
          <span>
            <span className="text-text-secondary/60">calls </span>
            <span className="text-text-primary">{metrics.num_api_calls}</span>
          </span>
        </div>
      )}

      {/* Score */}
      {showScore && (
        <div className="flex items-baseline gap-2 pt-1">
          <span className="text-xs text-text-secondary font-mono">Score</span>
          <span
            className={[
              'text-xl font-bold font-mono tabular-nums',
              status === 'winner' ? 'text-accent-winner' : 'text-text-primary',
            ].join(' ')}
          >
            {animatedScore.toFixed(1)}
          </span>
          <span className="text-xs text-text-secondary font-mono">/ 100</span>
        </div>
      )}
    </div>
  )
}

const ArenaPanel = memo(
  ArenaPanelComponent,
  (prev, next) => prev.panel === next.panel,
)

export default ArenaPanel
