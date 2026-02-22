# Journey Performance Budgets

Perceived-speed budgets for core Scaffold Arena journeys.

## Budget Targets

| Journey | First paint | First actionable | First value |
| --- | --- | --- | --- |
| Arena setup (`/arena`) | <= 1.0s | <= 1.8s | <= 3.5s (task+model selectable, run CTA available) |
| Results review (`/results`) | <= 1.1s | <= 2.0s | <= 4.0s (state callout + role summary visible) |
| History restore (`/history`) | <= 1.0s | <= 1.8s | <= 3.0s (run list + load action visible) |
| Leaderboard (`/leaderboard`) | <= 1.1s | <= 2.0s | <= 3.2s (aggregate panels visible) |

## Measurement Notes

- Route-transition dwell is captured via `route_timing` telemetry events.
- Conversion and recovery funnels are tracked separately in telemetry dashboard.
- E2E, visual, and accessibility suites run as baseline release gates.

## Enforcement Guidance

- Treat repeated budget breaches as UX defects.
- Prioritize above-the-fold content and progressive disclosure over dense initial render.
- Use route-level telemetry trends to identify and triage performance regressions.
