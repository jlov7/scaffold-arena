# ADR 001: Frontend Shell + Feature Boundaries

## Status
Superseded by [ADR 007](007-workbench-v1-frontend-boundaries.md)

## Context
The frontend gained substantial capabilities quickly, causing orchestration logic to accumulate in `App.tsx`. This increases cognitive load and makes high-velocity iteration risky.

## Decision
Adopt a route-view shell with explicit module boundaries:
- `app/` controls shell and navigation.
- Feature orchestration migrates from `App.tsx` to feature modules.
- Cross-cutting concerns (`errors`, `telemetry`) remain isolated and testable.

## Consequences
### Positive
- Reduced blast radius for changes.
- Clear ownership and test boundaries.
- Easier onboarding for additional contributors.

### Negative
- Short-term migration effort.
- Additional files and structure overhead.

## Follow-up Work
- Extract arena/comparison/autopsy/report orchestration into feature folders.
- Add import-boundary lint rules.
- Add architecture regression checks in CI.

## Supersession note

This decision records the earlier shell-boundary direction. Protocol-v1 Workbench boundaries are now governed by ADR 007; retain this ADR as decision history, not as a description of the current route structure.
