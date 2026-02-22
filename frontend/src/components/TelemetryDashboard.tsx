import { useMemo } from 'react'

import type { TelemetryEvent } from '../telemetry/events'

interface TelemetryDashboardProps {
  events: TelemetryEvent[]
}

const FUNNEL_ORDER = [
  'run_started',
  'run_completed',
  'comparison_started',
  'comparison_completed',
  'report_exported',
] as const

const ONBOARDING_FUNNEL_ORDER = [
  'onboarding_step_completed',
  'onboarding_help_opened',
  'onboarding_primary_action',
] as const

const LABELS: Record<(typeof FUNNEL_ORDER)[number], string> = {
  run_started: 'Runs started',
  run_completed: 'Runs completed',
  comparison_started: 'Comparisons started',
  comparison_completed: 'Comparisons completed',
  report_exported: 'Reports exported',
}

const ONBOARDING_LABELS: Record<
  (typeof ONBOARDING_FUNNEL_ORDER)[number],
  string
> = {
  onboarding_step_completed: 'Onboarding steps completed',
  onboarding_help_opened: 'Help opened',
  onboarding_primary_action: 'Primary actions used',
}

function safePercent(numerator: number, denominator: number): number {
  if (denominator <= 0) return 0
  return Math.max(0, Math.min(100, (numerator / denominator) * 100))
}

export default function TelemetryDashboard({ events }: TelemetryDashboardProps) {
  const rows = useMemo(() => {
    const counts = new Map<string, number>()
    for (const event of events) {
      counts.set(event.name, (counts.get(event.name) ?? 0) + 1)
    }

    const initialPrevious = counts.get(FUNNEL_ORDER[0]) ?? 0
    return FUNNEL_ORDER.reduce<
      { key: string; label: string; count: number; conversion: number }[]
    >((acc, name, index) => {
      const count = counts.get(name) ?? 0
      const previous = index === 0 ? initialPrevious : acc[index - 1].count
      const conversion =
        index === 0 || previous === 0
          ? 1
          : Math.max(0, Math.min(1, count / previous))
      acc.push({
        key: name,
        label: LABELS[name],
        count,
        conversion,
      })
      return acc
    }, [])
  }, [events])

  const onboardingRows = useMemo(() => {
    const counts = new Map<string, number>()
    for (const event of events) {
      counts.set(event.name, (counts.get(event.name) ?? 0) + 1)
    }
    const first = counts.get(ONBOARDING_FUNNEL_ORDER[0]) ?? 0
    return ONBOARDING_FUNNEL_ORDER.reduce<
      { key: string; label: string; count: number; conversion: number }[]
    >((acc, key, index) => {
      const count = counts.get(key) ?? 0
      const previous = index === 0 ? first : acc[index - 1].count
      const conversion =
        index === 0 || previous === 0
          ? 1
          : Math.max(0, Math.min(1, count / previous))
      acc.push({
        key,
        label: ONBOARDING_LABELS[key],
        count,
        conversion,
      })
      return acc
    }, [])
  }, [events])
  const recoveryStats = useMemo(() => {
    let blockersDetected = 0
    let blockersResolved = 0
    let fallbackEnabled = 0
    const durations: number[] = []
    for (const event of events) {
      if (event.name === 'onboarding_blocker_detected') {
        blockersDetected += 1
      } else if (event.name === 'onboarding_blocker_resolved') {
        blockersResolved += 1
        const durationRaw = Number(event.payload.duration_ms)
        if (Number.isFinite(durationRaw) && durationRaw >= 0) {
          durations.push(durationRaw)
        }
      } else if (event.name === 'fallback_mode_enabled') {
        fallbackEnabled += 1
      }
    }
    const averageDurationMs =
      durations.length > 0
        ? durations.reduce((sum, value) => sum + value, 0) / durations.length
        : null
    return {
      blockersDetected,
      blockersResolved,
      fallbackEnabled,
      recoveryRate: safePercent(blockersResolved, blockersDetected),
      averageDurationMs,
    }
  }, [events])
  const routeTimingStats = useMemo(() => {
    const dwellValues: number[] = []
    for (const event of events) {
      if (event.name !== 'route_timing') continue
      const dwell = Number(event.payload.dwell_ms)
      if (Number.isFinite(dwell) && dwell >= 0) {
        dwellValues.push(dwell)
      }
    }
    if (dwellValues.length === 0) {
      return { transitions: 0, averageMs: null as number | null }
    }
    return {
      transitions: dwellValues.length,
      averageMs:
        dwellValues.reduce((sum, value) => sum + value, 0) / dwellValues.length,
    }
  }, [events])
  const roleSegments = useMemo(() => {
    const counts = new Map<string, number>()
    for (const event of events) {
      if (event.name !== 'persona_selected') continue
      const profile = String(event.payload.profile ?? 'unknown')
      counts.set(profile, (counts.get(profile) ?? 0) + 1)
    }
    return ['evaluator', 'operator', 'analyst', 'executive'].map((profile) => ({
      profile,
      count: counts.get(profile) ?? 0,
    }))
  }, [events])
  const activationCount = useMemo(
    () => events.filter((event) => event.name === 'activation_completed').length,
    [events],
  )
  const feedbackCount = useMemo(
    () => events.filter((event) => event.name === 'ux_feedback_submitted').length,
    [events],
  )

  return (
    <section className="rounded border border-border/60 bg-bg-primary p-3">
      <div className="text-[11px] uppercase tracking-widest text-text-secondary">
        Conversion Funnel
      </div>
      <div className="mt-2 space-y-2">
        {rows.map((row) => (
          <div key={row.key} className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-text-secondary">{row.label}</span>
              <span className="text-text-primary tabular-nums">{row.count}</span>
            </div>
            <div className="mt-1 h-1.5 rounded bg-bg-tertiary">
              <div
                className="h-1.5 rounded bg-accent-info"
                style={{ width: `${Math.round(row.conversion * 100)}%` }}
              />
            </div>
            <div className="mt-1 text-[10px] text-text-muted">
              Step conversion: {(row.conversion * 100).toFixed(0)}%
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 border-t border-border/60 pt-3">
        <div className="text-[11px] uppercase tracking-widest text-text-secondary">
          Onboarding Funnel
        </div>
        <div className="mt-2 space-y-2">
          {onboardingRows.map((row) => (
            <div key={row.key} className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-secondary">{row.label}</span>
                <span className="text-text-primary tabular-nums">{row.count}</span>
              </div>
              <div className="mt-1 h-1.5 rounded bg-bg-tertiary">
                <div
                  className="h-1.5 rounded bg-accent-winner"
                  style={{ width: `${Math.round(row.conversion * 100)}%` }}
                />
              </div>
              <div className="mt-1 text-[10px] text-text-muted">
                Step conversion: {(row.conversion * 100).toFixed(0)}%
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="mt-4 border-t border-border/60 pt-3">
        <div className="text-[11px] uppercase tracking-widest text-text-secondary">
          Failure Recovery
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">Blockers detected</div>
            <div className="text-sm tabular-nums text-text-primary">
              {recoveryStats.blockersDetected}
            </div>
          </div>
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">Blockers resolved</div>
            <div className="text-sm tabular-nums text-text-primary">
              {recoveryStats.blockersResolved}
            </div>
          </div>
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">Recovery success rate</div>
            <div className="text-sm tabular-nums text-accent-winner">
              {recoveryStats.recoveryRate.toFixed(0)}%
            </div>
          </div>
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">Fallback mode activations</div>
            <div className="text-sm tabular-nums text-text-primary">
              {recoveryStats.fallbackEnabled}
            </div>
          </div>
        </div>
        <div className="mt-2 text-[10px] text-text-muted">
          Avg blocker recovery time:{' '}
          {recoveryStats.averageDurationMs === null
            ? 'n/a'
            : `${Math.round(recoveryStats.averageDurationMs / 1000)}s`}
        </div>
      </div>
      <div className="mt-4 border-t border-border/60 pt-3">
        <div className="text-[11px] uppercase tracking-widest text-text-secondary">
          Route Timing
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">Route transitions</div>
            <div className="text-sm tabular-nums text-text-primary">
              {routeTimingStats.transitions}
            </div>
          </div>
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">
              Avg dwell before transition
            </div>
            <div className="text-sm tabular-nums text-text-primary">
              {routeTimingStats.averageMs === null
                ? 'n/a'
                : `${Math.round(routeTimingStats.averageMs / 1000)}s`}
            </div>
          </div>
        </div>
      </div>
      <div className="mt-4 border-t border-border/60 pt-3">
        <div className="text-[11px] uppercase tracking-widest text-text-secondary">
          Role Segments
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {roleSegments.map((segment) => (
            <div
              key={segment.profile}
              className="rounded border border-border/60 bg-bg-secondary px-2 py-2"
            >
              <div className="text-[10px] uppercase text-text-muted">
                {segment.profile}
              </div>
              <div className="text-sm tabular-nums text-text-primary">
                {segment.count}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">Activation completions</div>
            <div className="text-sm tabular-nums text-accent-winner">
              {activationCount}
            </div>
          </div>
          <div className="rounded border border-border/60 bg-bg-secondary px-2 py-2">
            <div className="text-[10px] text-text-muted">Feedback submissions</div>
            <div className="text-sm tabular-nums text-text-primary">
              {feedbackCount}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
