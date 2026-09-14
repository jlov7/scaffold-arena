# Frontend

Scaffold Arena uses React, TypeScript, Vite, and Tailwind CSS for two separated browser surfaces: the Protocol-v1 Workbench and the legacy compatibility application.

## Current route boundary

- `src/main.tsx` sends `/` and `/workbench/*` to the lazy-loaded Protocol-v1 Workbench.
- `src/workbench-v1/` contains the Workbench shell, typed client, journeys, and Study, Design, Preflight, Execute, Analyze, Review, Trace Lab, Evidence, Settings, and optional diagnostic surfaces.
- `src/App.tsx`, `src/features/`, and `src/components/` retain the legacy compatibility experience for routes such as `/arena`, `/results`, `/history`, `/leaderboard`, and `/settings`.
- `src/telemetry/` defines consent-gated client events retained in browser memory; it is not a remote analytics service.

The Workbench is evidence-bounded: fixture, blocked, unknown, and persisted-record states do not imply a live benchmark, provider result, usability outcome, or release approval.

## Local development

```bash
cd frontend
npx -y pnpm@10 install --frozen-lockfile
npx -y pnpm@10 dev
```

The development server normally listens on `http://localhost:5173`. Configure its API proxy only for the local backend you intend to use.

## Build and verification

```bash
cd frontend
npx -y pnpm@10 lint
npx -y pnpm@10 test
npx -y pnpm@10 build
npx -y pnpm@10 test:e2e
npx -y pnpm@10 test:a11y
npx -y pnpm@10 verify:visual
```

These commands are local engineering checks. Run the repository release gate on the exact candidate before making a release claim.
