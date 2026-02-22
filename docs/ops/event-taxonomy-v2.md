# Event Taxonomy v2

This taxonomy maps telemetry events to journey stages and UX governance outcomes.

## Stage Mapping

| Journey stage | Core events | Purpose |
| --- | --- | --- |
| `setup` | `route_changed`, `onboarding_step_completed` (`task_selected`, `model_selected`) | Detect setup completion and early drop-off |
| `running` | `run_started`, `onboarding_primary_action`, `onboarding_blocker_detected`, `nav_confusion_signal` | Detect execution friction and flow thrash |
| `review` | `run_completed`, `onboarding_step_completed` (`results_reviewed`) | Validate first-value activation and review progression |
| `iterate` | `comparison_started`, `comparison_completed`, `autopsy_started`, `report_exported`, `json_exported`, `run_shared` | Measure depth-of-use and evidence completion |

## Recovery Funnel Events

- `onboarding_blocker_detected`
- `onboarding_blocker_resolved`
- `fallback_mode_enabled`
- `fallback_mode_disabled`

These are used for recovery rate and blocker-resolution timing KPIs.

## Activation Event Definition (WS2-T01)

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
- Business meaning: this user reached end-to-end comparative value, not just first click.

## Experiment Events

- `experiment_exposed` with `experiment` + `variant` payload:
  - `tour_entry`
  - `post_run_rail_order`
  - `persona_path`

## Payload Contract Notes

- Every event includes:
  - `name`
  - `ts_ms`
  - `payload` object
- Route-related events must include route/view identifiers.
- Workflow events should include `task_id` and/or `run_id` where available.

## Analytics Surfaces Consuming v2

- Conversion Funnel (activation path).
- Onboarding Funnel.
- Failure Recovery dashboard slice.
- Route confusion telemetry (pogo/back-forth signal).
- Role-segmented analytics slice (Evaluator, Operator, Analyst, Executive).
- Weekly UX regression report with HEART metrics.
