# ADR 001: Frontend Shell + Feature Boundaries

## Status
Accepted

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
