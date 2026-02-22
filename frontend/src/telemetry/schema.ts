import type { TelemetryEventName } from './events'

export const TELEMETRY_EVENT_SCHEMA: Record<
  TelemetryEventName,
  { required: readonly string[] }
> = {
  run_started: { required: ['task_id', 'model_id', 'run_id'] },
  run_completed: { required: ['run_id'] },
  comparison_started: { required: ['run_id', 'winner_id'] },
  comparison_completed: { required: ['run_id'] },
  autopsy_started: { required: ['run_id', 'scaffold_id'] },
  report_exported: { required: ['run_id'] },
  json_exported: { required: ['run_id'] },
  run_shared: { required: ['run_id'] },
  web_vital: { required: ['name', 'value'] },
  route_changed: { required: ['route'] },
  route_timing: { required: ['from', 'to', 'dwell_ms'] },
  nav_confusion_signal: { required: ['count', 'window_ms'] },
  experiment_exposed: { required: ['experiment', 'variant'] },
  onboarding_step_completed: { required: ['step'] },
  onboarding_help_opened: { required: ['source', 'blocker', 'task_id'] },
  onboarding_blocker_detected: { required: ['blocker', 'task_id'] },
  onboarding_primary_action: { required: ['action', 'blocker', 'task_id'] },
  persona_selected: { required: ['profile', 'experience_mode'] },
  activation_completed: { required: ['profile', 'experience_mode'] },
  ux_feedback_submitted: { required: ['sentiment', 'profile', 'stage'] },
  onboarding_blocker_resolved: {
    required: ['blocker', 'duration_ms', 'recovery_mode', 'task_id'],
  },
  fallback_mode_enabled: { required: ['blocker', 'task_id'] },
  fallback_mode_disabled: { required: ['task_id'] },
}

export function validateTelemetryPayload(
  name: TelemetryEventName,
  payload: Record<string, unknown>,
): { valid: boolean; missing: string[] } {
  const schema = TELEMETRY_EVENT_SCHEMA[name]
  const missing = schema.required.filter((key) => payload[key] === undefined)
  return {
    valid: missing.length === 0,
    missing,
  }
}
