# Scaffold Arena Agent Guide

## Mission

Scaffold Arena is a prospective public benchmark/workbench for investigating how scaffold and orchestration choices may change LLM output quality, reliability, cost, latency, and failure profile.

Research question, not a current result: can the same model under different scaffolds produce measurably different outcomes? Every current product and research claim is bounded by [`docs/evidence-status.md`](docs/evidence-status.md).

## Build And Test

```bash
# Repo release gate
./scripts/verify-all.sh

# Backend
cd backend && uv sync --extra dev && uv run pytest
cd backend && uv run uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npx -y pnpm@10 lint
cd frontend && npx -y pnpm@10 test
cd frontend && npx -y pnpm@10 build
cd frontend && npx -y pnpm@10 verify:visual
```

## Non-Negotiables

- SSE is GET-only: `POST /api/runs` then `GET /api/runs/{id}/events`.
- Keep deterministic evaluation weight at or above 70 percent for every task family.
- Costs must come from provider usage and `backend/config/models.py`; do not hardcode prices elsewhere.
- Synthetic sources must be labeled in task prompts, UI surfaces, reports, and docs.
- Use `backend/utils/json_extract.py` for JSON extraction resilience.
- Do not fake benchmark results, fixture results, screenshots, traces, costs, or release scores.
- Evidence before claims: every public claim must point to a protocol artifact, fixture, trace audit, report, or reproducible command.

## Change Discipline

- Prefer small, composable changes that preserve the FastAPI + React + TypeScript + SSE architecture.
- Do not add production dependencies unless the protocol or release gate cannot be credible without them.
- Do not optimize UI polish before benchmark/protocol credibility is strong.
- Record user-visible changes in `CHANGELOG.md`; keep private build diaries and model-routing notes out of the public tree.

## Release Stop Criteria

Stop only when `./scripts/verify-all.sh` passes for the exact candidate. Research claims remain bounded by the evidence status in `docs/evidence-status.md`; never promote fixture validation into live, human-calibrated, or independently reproduced evidence.
