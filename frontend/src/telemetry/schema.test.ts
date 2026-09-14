import { describe, expect, test } from 'vitest'

import type { TelemetryEventName } from './events'
import { TELEMETRY_EVENT_SCHEMA, validateTelemetryPayload } from './schema'

const SAMPLE_PAYLOADS: Record<TelemetryEventName, Record<string, unknown>> = {
  run_started: { task_id: 'extraction', model_id: 'claude-sonnet-4-6', run_id: 'run_1' },
  run_completed: { run_id: 'run_1' },
  comparison_started: { run_id: 'run_1', winner_id: 'plan_execute_verify' },
  comparison_completed: { run_id: 'run_1' },
  autopsy_started: { run_id: 'run_1', scaffold_id: 'bare' },
  report_exported: { run_id: 'run_1' },
  json_exported: { run_id: 'run_1' },
  run_shared: { run_id: 'run_1' },
  web_vital: { name: 'LCP', value: 1234 },
  route_changed: { route: '/arena' },
  route_timing: { from: '/arena', to: '/results', dwell_ms: 2042 },
  nav_confusion_signal: { count: 4, window_ms: 8000 },
  experiment_exposed: { experiment: 'persona_path', variant: 'control' },
  onboarding_step_completed: { step: 'task_selected' },
  onboarding_help_opened: { source: 'header', blocker: 'auth_missing', task_id: 'extraction' },
  onboarding_blocker_detected: { blocker: 'auth_missing', task_id: 'extraction' },
  onboarding_primary_action: { action: 'open_settings', blocker: 'auth_missing', task_id: 'extraction' },
  persona_selected: { profile: 'evaluator', experience_mode: 'guided' },
  activation_completed: { profile: 'evaluator', experience_mode: 'guided' },
  ux_feedback_submitted: { sentiment: 'helpful', profile: 'evaluator', stage: 'review' },
  onboarding_blocker_resolved: {
    blocker: 'auth_missing',
    duration_ms: 3200,
    recovery_mode: 'standard',
    task_id: 'extraction',
  },
  fallback_mode_enabled: { blocker: 'auth_missing', task_id: 'extraction' },
  fallback_mode_disabled: { task_id: 'extraction' },
}

describe('telemetry event schema', () => {
  test('defines schema for every telemetry event', () => {
    const names = Object.keys(SAMPLE_PAYLOADS).sort()
    const schemaNames = Object.keys(TELEMETRY_EVENT_SCHEMA).sort()
    expect(schemaNames).toEqual(names)
  })

  for (const [name, payload] of Object.entries(SAMPLE_PAYLOADS) as [
    TelemetryEventName,
    Record<string, unknown>,
  ][]) {
    test(`${name} payload fixture satisfies required keys`, () => {
      const result = validateTelemetryPayload(name, payload)
      expect(result.valid).toBe(true)
      expect(result.missing).toEqual([])
    })

    test(`${name} rejects payload missing one required key`, () => {
      const required = TELEMETRY_EVENT_SCHEMA[name].required
      if (required.length === 0) return
      const missingKey = required[0]
      const invalid = { ...payload }
      delete invalid[missingKey]
      const result = validateTelemetryPayload(name, invalid)
      expect(result.valid).toBe(false)
      expect(result.missing).toContain(missingKey)
    })
  }
})
