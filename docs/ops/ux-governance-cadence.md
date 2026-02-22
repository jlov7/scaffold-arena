# UX Governance Cadence

This operating cadence keeps UX quality measurable and prevents silent regressions.

## Weekly UX Council (30 minutes)

- Cadence: every Friday.
- Inputs:
  - `output/weekly-ux-regression-report.md`
  - Lighthouse artifacts from CI.
  - Accessibility report artifact (`playwright-a11y-report`).
  - Open UX tracker items in `.codex/UX_REARCH_EXECUTION_TRACKER.md`.
- Required outputs:
  - Top 3 UX risks with named owner and due date.
  - One experiment or copy refinement candidate.
  - Go/no-go recommendation for current release branch.

## HEART Scorecard Ownership

| Dimension | Primary event signals | Review question |
| --- | --- | --- |
| Happiness | `ux_feedback_submitted` | Did guidance quality improve week over week? |
| Engagement | `onboarding_step_completed`, `onboarding_primary_action` | Are users progressing through stages without stall? |
| Adoption | `activation_completed` | Are first-time users reaching first value? |
| Retention | `comparison_completed`, `report_exported`, `run_shared` | Are users returning for deeper evidence workflows? |
| Task Success | `run_completed`, `onboarding_blocker_resolved` | Are users completing core jobs with fewer blockers? |

## Monthly Product Quality Review (60 minutes)

- Summarize trendlines from the last four weekly reports.
- Review open P0-P2 UX defects and their aging.
- Confirm roadmap adjustments for the next month:
  - IA/navigation debt.
  - Onboarding friction.
  - Mobile and accessibility regressions.
  - Performance budget drifts.

## Launch Gate Policy

No launch candidate is approved unless all are true:

1. Latest weekly regression report is generated in CI and attached as artifact.
2. Accessibility and Lighthouse checks pass.
3. No unresolved P0 UX defects.
4. At least one named owner exists for each top open workstream risk.
