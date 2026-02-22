# Assistive Technology Smoke Protocol

Use this checklist before release candidates and after major UX changes.

## Scope

- Core routes: `/arena`, `/results`, `/history`, `/settings`.
- Core workflows: first run, blocker recovery, proof comparison, report export.
- Platforms:
  - macOS + VoiceOver + Safari.
  - Windows + NVDA + Chrome.

## VoiceOver Checklist (macOS)

1. Enable VoiceOver and navigate landmarks on each route (`Control + Option + U` rotor).
2. Verify heading hierarchy announces route purpose and stage context.
3. Trigger Help Center with keyboard and confirm focus enters dialog and returns on close.
4. Run a mocked arena flow and confirm live-region announcements for stage transitions and completion.
5. Trigger a blocker state and confirm recovery callouts are announced with actionable wording.

## NVDA Checklist (Windows)

1. Navigate by buttons/landmarks to verify discoverability of top actions.
2. Confirm nav controls expose descriptive accessible names (`Open Arena view`, etc.).
3. Open and close modal dialogs using keyboard only (`Enter`, `Escape`, `Tab` loop).
4. Verify form controls in Settings announce labels and helper text in a logical order.
5. Validate no critical task requires pointer-only interaction.

## Pass/Fail Criteria

- Pass:
  - All critical journeys are keyboard-complete.
  - No focus traps or focus loss in dialogs.
  - Announcements occur for transitions and outcomes.
  - Recovery guidance is understandable without visual context.
- Fail:
  - Any blocker in first-run, recovery, compare, or export flow for SR users.

## Evidence To Store

- Latest automated a11y run: `pnpm test:a11y`.
- CI artifact: `playwright-a11y-report`.
- Notes file in `docs/reviews/` with date, tester, findings, and fixes.
