# Tree Test Findability Report

Date: 2026-02-20

## Objective

Validate that the top 8 user intents are discoverable with first-click success from the primary shell.

## Method

- Scripted tree test implemented in:
  - `frontend/tests/e2e/tree-findability.spec.ts`
- Environment:
  - mocked API
  - start route `/arena`

## Intents Covered (8)

1. Find Help Center.
2. Start guided tour.
3. Open Settings.
4. Open Results workspace.
5. Open History.
6. Open Leaderboard.
7. Find Run Arena action.
8. Find Export Report action from historical run context.

## Outcome

- Result: **8/8 first-click success**
- Blockers found: **0**
- Recommendation: pass for IA findability baseline.
