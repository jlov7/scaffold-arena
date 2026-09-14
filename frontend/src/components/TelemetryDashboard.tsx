import { useMemo, type ReactNode } from 'react'

import type { TelemetryEvent } from '../telemetry/events'
import './TelemetryDashboard.css'

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

type FunnelRow = {
  key: string
  label: string
  count: number
  conversion: number
}

function safePercent(numerator: number, denominator: number): number {
  if (denominator <= 0) return 0
  return Math.max(0, Math.min(100, (numerator / denominator) * 100))
}

function funnelRows(
  order: readonly string[],
  labels: Record<string, string>,
  counts: Map<string, number>,
): FunnelRow[] {
  return order.map((key, index) => {
    const count = counts.get(key) ?? 0
    const previous = index === 0 ? count : counts.get(order[index - 1]) ?? 0
    return {
      key,
      label: labels[key],
      count,
      conversion: index === 0 || previous === 0
        ? 1
        : Math.max(0, Math.min(1, count / previous)),
    }
  })
}

function Funnel({
  title,
  rows,
  tone,
  separated = false,
}: {
  title: string
  rows: FunnelRow[]
  tone: 'info' | 'winner'
  separated?: boolean
}) {
  return (
    <div className={separated ? 'td-s' : undefined}>
      <div className="td-h">{title}</div>
      <div className="td-l">
        {rows.map((row) => (
          <div key={row.key} className="td-c">
            <div className="td-fh">
              <span>{row.label}</span>
              <span>{row.count}</span>
            </div>
            <div className="td-ft">
              <div
                className={`td-fb td-fb--${tone}`}
                style={{ width: `${Math.round(row.conversion * 100)}%` }}
              />
            </div>
            <div className="td-cap">
              Step conversion: {(row.conversion * 100).toFixed(0)}%
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function MetricCard({
  label,
  value,
  emphasis = false,
  uppercase = false,
}: {
  label: string
  value: ReactNode
  emphasis?: boolean
  uppercase?: boolean
}) {
  return (
    <div className="td-c">
      <div className={uppercase ? 'td-lab td-lab--upper' : 'td-lab'}>
        {label}
      </div>
      <div className={emphasis ? 'td-val td-val--emphasis' : 'td-val'}>
        {value}
      </div>
    </div>
  )
}

export default function TelemetryDashboard({ events }: TelemetryDashboardProps) {
  const {
    rows,
    onboardingRows,
    recoveryStats,
    routeTimingStats,
    roleSegments,
    activationCount,
    feedbackCount,
  } = useMemo(() => {
    const counts = new Map<string, number>()
    const roles = new Map<string, number>()
    const durations: number[] = []
    const dwellValues: number[] = []
    let blockersDetected = 0
    let blockersResolved = 0
    let fallbackEnabled = 0
    let activationCount = 0
    let feedbackCount = 0
    for (const event of events) {
      counts.set(event.name, (counts.get(event.name) ?? 0) + 1)
      if (event.name === 'onboarding_blocker_detected') blockersDetected += 1
      if (event.name === 'onboarding_blocker_resolved') {
        blockersResolved += 1
        const duration = Number(event.payload.duration_ms)
        if (Number.isFinite(duration) && duration >= 0) durations.push(duration)
      }
      if (event.name === 'fallback_mode_enabled') fallbackEnabled += 1
      if (event.name === 'route_timing') {
        const dwell = Number(event.payload.dwell_ms)
        if (Number.isFinite(dwell) && dwell >= 0) dwellValues.push(dwell)
      }
      if (event.name === 'persona_selected') {
        const profile = String(event.payload.profile ?? 'unknown')
        roles.set(profile, (roles.get(profile) ?? 0) + 1)
      }
      if (event.name === 'activation_completed') activationCount += 1
      if (event.name === 'ux_feedback_submitted') feedbackCount += 1
    }
    return {
      rows: funnelRows(FUNNEL_ORDER, LABELS, counts),
      onboardingRows: funnelRows(
        ONBOARDING_FUNNEL_ORDER,
        ONBOARDING_LABELS,
        counts,
      ),
      recoveryStats: {
        blockersDetected,
        blockersResolved,
        fallbackEnabled,
        recoveryRate: safePercent(blockersResolved, blockersDetected),
        averageDurationMs: durations.length
          ? durations.reduce((sum, value) => sum + value, 0) / durations.length
          : null,
      },
      routeTimingStats: {
        transitions: dwellValues.length,
        averageMs: dwellValues.length
          ? dwellValues.reduce((sum, value) => sum + value, 0) / dwellValues.length
          : null,
      },
      roleSegments: ['evaluator', 'operator', 'analyst', 'executive'].map(
        (profile) => ({ profile, count: roles.get(profile) ?? 0 }),
      ),
      activationCount,
      feedbackCount,
    }
  }, [events])

  return (
    <section className="td">
      <Funnel title="Conversion Funnel" rows={rows} tone="info" />
      <Funnel
        title="Onboarding Funnel"
        rows={onboardingRows}
        tone="winner"
        separated
      />
      <div className="td-s">
        <div className="td-h">
          Failure Recovery
        </div>
        <div className="td-g">
          <MetricCard
            label="Blockers detected"
            value={recoveryStats.blockersDetected}
          />
          <MetricCard
            label="Blockers resolved"
            value={recoveryStats.blockersResolved}
          />
          <MetricCard
            label="Recovery success rate"
            value={`${recoveryStats.recoveryRate.toFixed(0)}%`}
            emphasis
          />
          <MetricCard
            label="Fallback mode activations"
            value={recoveryStats.fallbackEnabled}
          />
        </div>
        <div className="td-cap">
          Avg blocker recovery time:{' '}
          {recoveryStats.averageDurationMs === null
            ? 'n/a'
            : `${Math.round(recoveryStats.averageDurationMs / 1000)}s`}
        </div>
      </div>
      <div className="td-s">
        <div className="td-h">
          Route Timing
        </div>
        <div className="td-g">
          <MetricCard
            label="Route transitions"
            value={routeTimingStats.transitions}
          />
          <MetricCard
            label="Avg dwell before transition"
            value={routeTimingStats.averageMs === null
              ? 'n/a'
              : `${Math.round(routeTimingStats.averageMs / 1000)}s`}
          />
        </div>
      </div>
      <div className="td-s">
        <div className="td-h">
          Role Segments
        </div>
        <div className="td-g">
          {roleSegments.map((segment) => (
            <MetricCard
              key={segment.profile}
              label={segment.profile}
              value={segment.count}
              uppercase
            />
          ))}
        </div>
        <div className="td-g">
          <MetricCard
            label="Activation completions"
            value={activationCount}
            emphasis
          />
          <MetricCard
            label="Feedback submissions"
            value={feedbackCount}
          />
        </div>
      </div>
    </section>
  )
}
