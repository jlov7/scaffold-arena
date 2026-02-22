# Human Validation Runbook (Remaining LV Tasks)

This runbook operationalizes the final four launch-validation tasks that require real participants:

- LV-T01: 12 moderated usability sessions (persona-balanced).
- LV-T04: unmoderated onboarding-copy comprehension test.
- LV-T05: mobile-only validation sessions.
- LV-T06: accessibility user testing with keyboard/screen-reader users.

## Prerequisites

1. Use latest branch with green gates (`lint`, `test`, `playwright`, `build`).
2. Provide participants this stable demo URL/environment.
3. Capture outcomes in:
   - `docs/reviews/templates/moderated-usability-log.csv`
   - `docs/reviews/templates/unmoderated-copy-results.csv`
   - `docs/reviews/templates/mobile-validation-log.csv`
   - `docs/reviews/templates/accessibility-user-test-log.csv`

## Execution Matrix

| Task | Sample | Duration | Success Gate |
|---|---:|---:|---|
| LV-T01 Moderated usability | 12 total, 3 per persona | 30-40 min | 90% complete canonical flow without facilitator intervention |
| LV-T04 Copy comprehension | 20 unmoderated | 10-15 min | 85% correct interpretation of onboarding purpose and next action |
| LV-T05 Mobile-only validation | 12 mobile users | 20-30 min | 90% can complete first run + results review with no dead-end |
| LV-T06 Accessibility user test | 8 users (keyboard and SR mix) | 30-45 min | 0 critical blockers, 95% task completion with assistive tooling |

## Scripted Core Tasks (Use Across Sessions)

1. Select a benchmark task and model.
2. Start a run and interpret stage progress.
3. Open Results and identify winner with rationale.
4. Trigger help flow when blocked.
5. Run proof comparison and locate export action.

## Output Requirement

After sessions complete, publish:

- `docs/reviews/usability-test-results.md` update with quantitative summaries.
- `docs/reviews/frontend-panel-scorecard.md` delta notes.
- Tracker update in `.codex/UX_REARCH_EXECUTION_TRACKER.md` marking LV-T01/T04/T05/T06 complete.
