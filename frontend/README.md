# Frontend

Scaffold Arena frontend application (React + TypeScript + Vite + Tailwind CSS).

## Purpose

- Provide a guided benchmark UX for first-time users.
- Stream live scaffold output over SSE.
- Support compare -> diagnose -> patch -> rerun workflows.
- Surface onboarding, accessibility, and diagnostics tooling in one UI shell.

## Stack

- React 18 + TypeScript
- Vite 7
- Tailwind CSS 4
- Playwright (E2E, a11y, visual)
- Vitest + Testing Library

## Local Development

```bash
cd frontend
pnpm install
pnpm dev
```

The app runs at `http://localhost:5173`.

## Build and Verification

```bash
cd frontend
pnpm lint
pnpm test
pnpm build
pnpm test:e2e
pnpm test:a11y
pnpm test:visual
```

## Key Directories

- `src/features/workspaces/`: route-level Arena/Results/History/Leaderboard/Settings containers
- `src/components/`: reusable UI and journey primitives
- `src/hooks/`: streaming and runtime hooks (`useArenaRun`, `useSSE`, etc.)
- `src/styles/`: design tokens and theme system
- `tests/`: Playwright suites (`e2e`, `a11y`, `visual`)
- `scripts/`: performance checks, screenshot capture, smoke tooling

## Production Notes

- API base URL is driven by `VITE_API_BASE_URL`.
- Vercel config is in `vercel.json` (security headers + SPA rewrites).
- Text-size preferences are persisted in-browser (`comfortable`, `standard`, `dense`).
