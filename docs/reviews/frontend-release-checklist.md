# Frontend Release Checklist

## Build and Test
- [x] `pnpm lint`
- [x] `pnpm test`
- [x] `pnpm test:content`
- [x] `pnpm build`
- [x] `pnpm perf:budget`

## Accessibility
- [x] Keyboard-only pass for run, history, leaderboard, settings
- [x] Screen-reader pass for dialogs, run state, toasts
- [x] Color contrast and focus-visible checks

## Reliability
- [x] Offline/online transition behavior verified
- [x] SSE retry/failure behavior verified
- [x] Error remediation messaging reviewed

## Security/Trust
- [x] Session token status visible in Settings
- [x] Notification permission controls verified
- [x] Dependency audit clean (`pnpm audit --prod --audit-level high`)

## Final Go/No-Go
- [x] Smoke script passes against target env (`pnpm smoke:prod -- <base_url>`)
- [x] Rollback plan validated
- [x] Product/design sign-off captured

## Evidence (2026-02-19)
- `pnpm lint && pnpm test && pnpm build && pnpm perf:budget` passed.
- `pnpm test:e2e`, `pnpm test:a11y`, and `pnpm test:visual` passed.
- `pnpm audit --prod --audit-level high` reported no known vulnerabilities.
- `pnpm smoke:prod -- http://127.0.0.1:4317` passed against live local frontend+backend stack.
- Rollback procedure documented in `/Users/jasonlovell/AI/Scaffold Arena/docs/ops/frontend-smoke-and-rollback.md`.
- Panel/design sign-off captured in `/Users/jasonlovell/AI/Scaffold Arena/docs/reviews/frontend-panel-scorecard.md`.
