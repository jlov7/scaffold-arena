# Technical Explainer

## System Intent

Scaffold Arena is designed to benchmark orchestration quality with high observability and deterministic scoring.

## Runtime Architecture

- Frontend: React + TypeScript + Vite.
- Backend: FastAPI + async run engine.
- Provider integration: pluggable provider layer (Anthropic + OpenAI + Gemini + OpenRouter).
- Streaming protocol: SSE (`EventSource`, GET-only stream endpoint).

## Core Execution Flow

1. Frontend posts run request to `/api/runs`.
2. Backend creates run, launches concurrent scaffold tasks.
3. Each scaffold emits lifecycle and token events.
4. Run engine fans events into queue and streams via SSE.
5. Evaluation computes deterministic + optional judge scores.
6. Frontend renders panel states, scoreboard, and follow-up actions.

## Design Constraints

- Deterministic scoring weight >=70% for each task.
- Costs computed from token usage + centralized price table.
- Autopsy outputs evidence-backed failure analysis and machine-applicable patches.
- Patch-rerun loop is one-click from UI.

## Frontend Design

- Feature hooks extracted from monolithic orchestration paths.
- Route-aware app shell: Arena, Results, History, Leaderboard, Settings.
- Progressive disclosure via workspace lanes:
  - Arena: Onboarding, Configure, Live run.
  - Results: Summary, Diagnostics.
- Primitive UI layer and tokenized visual system.
- Accessibility and motion baselines enforced with tests.
- Experiment framework for controlled UX variants.

## Quality Gates

### Backend
- `uv run pytest -q`

### Frontend
- `pnpm lint`
- `pnpm test`
- `pnpm build`
- `pnpm perf:budget`
- `pnpm arch:layers`
- `pnpm test:e2e`
- `pnpm test:a11y`
- `pnpm test:visual`
- `pnpm perf:lighthouse`
- `pnpm exec vitest run --coverage`

## Extension Points

- Add scaffold: implement base scaffold contract and register.
- Add task: implement task definition and gold/schema rules.
- Add metrics: extend evaluation harness + weight tables.
- Add dashboards: consume telemetry events and funnel data.

## Reference Docs

- Architecture deep dive: [`../architecture.md`](../architecture.md)
- API reference: [`../api-reference.md`](../api-reference.md)
- Evaluation methodology: [`../evaluation.md`](../evaluation.md)
- Frontend boundaries: [`../architecture/frontend-module-boundaries.md`](../architecture/frontend-module-boundaries.md)
