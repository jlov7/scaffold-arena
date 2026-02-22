# ADR 002: Frontend Migration Rollout and Rollback Points

## Status
Accepted

## Context

The UX re-architecture moves behavior from a monolithic shell toward clearer route, feature, and governance boundaries. This improves velocity but introduces migration risk if regressions appear in core journeys.

## Decision

Adopt phased migration with explicit rollback points:

1. **Phase A: UX safety rails and instrumentation**
   - Keep existing shell structure.
   - Add telemetry, guidance, and recovery controls.
2. **Phase B: route and contract hardening**
   - Enforce shell contracts and route-level tests.
   - Add architecture/layer checks in CI.
3. **Phase C: deeper modular extraction**
   - Move orchestration logic from `App.tsx` into feature modules incrementally.

## Rollback Points

- **R1 (after Phase A):** revert UX guidance deltas if activation or recovery metrics regress.
- **R2 (after Phase B):** revert shell-contract/nav changes if route findability drops or nav becomes unstable.
- **R3 (during Phase C):** revert specific extraction PRs if boundary checks pass but journey tests regress.

Each rollback point requires:

1. Revert offending change set.
2. Re-run `lint`, `test`, `test:e2e`, `test:a11y`, `perf:budget`.
3. Re-publish weekly UX regression report artifact.

## Consequences

### Positive

- Safer path to architecture modernization.
- Faster incident containment via pre-defined rollback anchors.
- Clearer accountability for launch/no-launch decisions.

### Negative

- Additional release process overhead.
- Requires disciplined CI artifact review every cycle.
