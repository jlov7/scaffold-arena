# Usability Test Results

Date: 2026-02-19

## Journey Map (Top 5)
1. First run (task + model selection -> run -> scoreboard)
2. Rerun with patch (autopsy -> patch rerun)
3. Compare models/scaffolds (proof comparison)
4. Share run URL (history/deep-link restore)
5. Export report (report generation and copy/download)

## Test Method
- Scripted end-to-end checks using Playwright:
  - `frontend/tests/e2e/journeys.spec.ts`
  - `frontend/tests/e2e/nav.spec.ts`
  - `frontend/tests/e2e/interaction.spec.ts`
  - `frontend/tests/e2e/failure-recovery.spec.ts`
  - `frontend/tests/e2e/viewports.spec.ts`
- Device/viewport matrix:
  - iPhone 13 (390x844)
  - iPhone 14 (393x852)
  - iPad (768x1024)
  - Laptop (1280x800)

## Result Summary
- Completed journeys: 12/12 passing.
- Severity-1 usability defects: 0 open.
- Key fixes verified:
  - Resume state restoration from URL/local context.
  - Focused run controls during active execution.
  - Post-run action prioritization rail.
  - Error/retry actions for 429/500/timeout scenarios.

## Follow-up
- Continue monitoring journey completion funnel in telemetry dashboard to catch regressions.
