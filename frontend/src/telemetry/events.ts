export type TelemetryEventName =
  | 'run_started'
  | 'run_completed'
  | 'comparison_started'
  | 'comparison_completed'
  | 'autopsy_started'
  | 'report_exported'
  | 'json_exported'
  | 'run_shared'
  | 'web_vital'
  | 'route_changed'
  | 'route_timing'
  | 'nav_confusion_signal'
  | 'experiment_exposed'
  | 'onboarding_step_completed'
  | 'onboarding_help_opened'
  | 'onboarding_blocker_detected'
  | 'onboarding_primary_action'
  | 'persona_selected'
  | 'activation_completed'
  | 'ux_feedback_submitted'
  | 'onboarding_blocker_resolved'
  | 'fallback_mode_enabled'
  | 'fallback_mode_disabled'

export interface TelemetryEvent {
  name: TelemetryEventName
  ts_ms: number
  payload: Record<string, unknown>
}
