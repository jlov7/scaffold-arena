# Event Taxonomy v2

This taxonomy documents the implemented, consent-gated client telemetry vocabulary. When enabled, the current client retains events in browser memory for the active page; it does not transmit them. Event names and payload shape are defined in `frontend/src/telemetry/events.ts` and `frontend/src/telemetry/schema.ts`.

## Stage Mapping

| Journey stage | Core events | Purpose |
| --- | --- | --- |
| `setup` | `route_changed`, `onboarding_step_completed` (`task_selected`, `model_selected`) | Record setup navigation and selections. |
| `running` | `run_started`, `onboarding_primary_action`, `onboarding_blocker_detected`, `nav_confusion_signal` | Record run-start and recovery interactions. |
| `review` | `run_completed`, `onboarding_step_completed` (`results_reviewed`) | Record completion and review interactions. |
| `iterate` | `comparison_started`, `comparison_completed`, `autopsy_started`, `report_exported`, `json_exported`, `run_shared` | Record comparison, analysis, export, and sharing interactions. |

## Recovery Funnel Events

- `onboarding_blocker_detected`
- `onboarding_blocker_resolved`
- `fallback_mode_enabled`
- `fallback_mode_disabled`

These support the local recovery views when telemetry is enabled. They do not establish user behavior, conversion, or usability outcomes.

## Activation event definition

`activation_completed` is the activation event for Scaffold Arena.

- Trigger: first time a user completes the full first-value flow in guided mode:
  - task selected
  - model selected
  - run started
  - results reviewed
  - comparison completed
- Event payload requirements:
  - `profile`
  - `experience_mode`
- The event records the declared sequence in the client. It is not evidence that a user obtained comparative value.

## Payload Contract Notes

- Every event includes:
  - `name`
  - `ts_ms`
  - `payload` object
- Route-related events must include route/view identifiers.
- Workflow events include `task_id` and/or `run_id` where the current caller has them available.

## Limits

The in-memory client tracker is an implementation aid and test surface. It is not a durable analytics service, a dashboard data source outside the active page, or evidence of product adoption, user outcomes, or UX quality.
