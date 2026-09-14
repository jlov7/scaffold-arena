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

## Build Bundle Gate

`pnpm perf:budget` enforces the production build's transfer budgets. The Workbench
first-load ceiling remains **550,000 bytes**; it includes only the shell and the
selected Workbench route's static dependency closure. Individual deferred chunks
remain capped at 210,000 bytes.

Harness X-Ray, Observatory, Counterfactual Replay, Arena Forge, and Trace Lab are optional
analysis routes. They are loaded only after the user navigates to their route,
and the bundle gate asserts that each surface stays outside the Workbench static
import closure. This makes a future static import a hard regression even if the
aggregate output happens to fit.

The aggregate emitted-JavaScript ceiling is **610,000 bytes** and the aggregate
emitted-asset ceiling is **820,000 bytes**. A recorded candidate build measured
609,190 bytes while preserving the stricter first-load ceiling. The change does
not relax initial Workbench transfer;
the route-split assertions and first-load cap are the regression tests for that
contract.
