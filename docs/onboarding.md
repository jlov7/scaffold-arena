# Contributor onboarding

## First hour

1. Read the [product overview](../README.md) and [evidence status](evidence-status.md).
2. Complete the offline setup in [getting started](getting-started.md).
3. Inspect the [protocol-v1 boundary](adr/003-protocol-v1-boundaries.md).
4. Run `./scripts/verify-all.sh` from the repository root.
5. Choose the relevant architecture or authoring guide from the [documentation index](README.md).

## Development commands

Backend:

```bash
cd backend
uv sync --frozen --extra dev --extra research
uv run pytest
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm lint
pnpm test
pnpm build
```

## Invariants

- SSE remains GET-only.
- Deterministic evaluation weight is at least 70 percent per task family.
- Provider cost comes from reported usage and the versioned model catalogue.
- Synthetic material is labelled in prompts, UI, reports, and documentation.
- Missing evidence lowers the claim ceiling; it is never inferred.
- Public claims link to reproducible artifacts or commands.

## Where changes belong

- Protocol objects and schemas: `backend/protocol_v1/`, `specs/v1/`
- Durable persistence and migrations: `backend/persistence_v1/`, `backend/migrations/`
- Execution and evaluation: `backend/execution_v1/`, `backend/evaluation_v1/`
- Analysis and evidence: `backend/analysis_v1/`, `backend/evidence_v1/`
- API and services: `backend/api/v1/`, `backend/services_v1/`
- Workbench: `frontend/src/workbench-v1/`
- StudyPacks: `study_packs/`

Update tests, documentation, and evidence boundaries in the same change. Do not present fixture output as live research.
