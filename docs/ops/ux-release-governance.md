# UX Release Governance

This policy defines how UX defects are classified, gated, and managed through release decisions.

## Severity Rubric (P0-P3)

| Severity | Definition | Example | Launch impact |
| --- | --- | --- | --- |
| P0 | Core journey blocked for most users | Cannot start run or recover from blocker | No-launch |
| P1 | Critical friction with workaround | Export path broken but manual workaround exists | Launch blocked unless owner-approved exception |
| P2 | Noticeable degradation, non-critical | Misleading helper text, weak visual hierarchy | Can launch with dated fix commitment |
| P3 | Minor polish issue | Alignment inconsistency, copy nit | Track in backlog |

## Feature Merge Acceptance Gates

Every UX-impacting PR must show:

1. Relevant automated tests updated or added.
2. No new accessibility critical/serious violations.
3. No regression in route-level performance budgets.
4. Updated docs if behavior or guidance changed.
5. Recovery path defined for new error states.

## Launch / No-Launch Checklist

Launch only if all pass:

1. `pnpm lint`
2. `pnpm test`
3. `pnpm test:e2e`
4. `pnpm test:a11y`
5. `pnpm test:visual`
6. `pnpm perf:budget`
7. Weekly UX regression report artifact is current in CI.
8. No unresolved P0 defects.

## UX Regression Rollback Protocol

1. Detect: telemetry, CI failure, or production report indicates P0/P1 UX regression.
2. Stabilize: disable affected path if possible, route users to safe fallback mode.
3. Roll back: revert offending frontend change set.
4. Verify: rerun a11y, journeys, and perf budget gates.
5. Communicate: publish incident note with root cause and prevention action.

## Monthly Product Quality Review Template

Use this format each month:

### 1. Snapshot
- Release train covered:
- Open P0/P1/P2 counts:
- Activation and recovery trends:

### 2. Journey Health
- First-run completion:
- Blocker recovery success:
- Compare/export usage:

### 3. Accessibility and Performance
- A11y critical/serious trend:
- Lighthouse and budget trend:

### 4. Top Regressions
- Regression summary:
- Root cause:
- Preventive action:

### 5. Priorities Next Month
- Top 3 UX debt items:
- Owners and target dates:
