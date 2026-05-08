# Frontend

Scaffold Arena frontend application (React + TypeScript + Vite + Tailwind CSS).

## Purpose

- Provide a guided benchmark UX for first-time users.
- Stream live scaffold output over SSE.
- Support compare -> diagnose -> patch -> rerun workflows.
- Surface onboarding, accessibility, and diagnostics tooling in one UI shell.

## Stack

- React 19 + TypeScript
- Vite 7
- Tailwind CSS 4
- Playwright (E2E, a11y, visual)
- Vitest + Testing Library

## Local Development

```bash
cd frontend
npx -y pnpm@10 install
npx -y pnpm@10 dev
```

The app runs at `http://localhost:5173`.

## Build and Verification

```bash
cd frontend
npx -y pnpm@10 lint
npx -y pnpm@10 test
npx -y pnpm@10 build
npx -y pnpm@10 test:e2e
npx -y pnpm@10 test:a11y
npx -y pnpm@10 verify:visual
```

## Key Directories

- `src/features/workspaces/`: route-level Arena/Results/History/Leaderboard/Settings containers
- `src/components/`: reusable UI and journey primitives
- `src/components/shell/`: research workbench shell and mobile navigation
- `src/hooks/`: streaming and runtime hooks (`useArenaRun`, `useSSE`, etc.)
- `src/styles/`: design tokens and theme system
- `tests/`: Playwright suites (`e2e`, `a11y`, `visual`)
- `scripts/`: performance checks, screenshot capture, smoke tooling

## Production Notes

- API base URL is driven by `VITE_API_BASE_URL`.
- Vercel config is in `vercel.json` (security headers + SPA rewrites).
- Text-size preferences are persisted in-browser (`comfortable`, `standard`, `dense`).
