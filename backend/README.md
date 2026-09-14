# Backend service

FastAPI backend for the Protocol-v1 Workbench and the legacy v0.1
run/evaluation compatibility API. The repository is an undeployed 0.9.1 beta
release candidate; local development is not deployment evidence.

## Responsibilities

- Register tasks and scaffolds at startup.
- Create and stream runs via SSE (`POST /api/runs` -> `GET /api/runs/{id}/events`).
- Score outputs with deterministic-first evaluation profiles.
- Provide diagnostics (`/api/runs/{id}/diagnostics`) and export bundles (`/api/runs/{id}/export-bundle`).
- Persist completed runs to SQLite.
- Support offline trace audits over saved run records.

Protocol v1 adds durable StudyPack and ExperimentSpec lifecycle, project-scoped
execution and event recovery, adapter/evaluator boundaries, analysis and
evidence services, and typed `/api/v1/*` routes. Personal mode is local and
does not perform login. Team mode is a separate PostgreSQL/OIDC/S3-compatible
configuration that fails closed when prerequisites are missing; configuration
and tests are not deployment evidence.

The legacy `/api/*` routes remain available in personal mode for migration and
comparison. Team mode disables them completely; authenticated team traffic is
limited to the project-scoped `/api/v1/*` boundary. Legacy imports are
quarantined before any explicit v1 conversion.

## Local Development

```bash
cp backend/.env.example backend/.env
cd backend
uv sync --extra dev
uv run uvicorn main:app --reload --port 8000
```

## Verified fixture demo and provenance

```bash
demo_dir="$(mktemp -d /tmp/scaffold-arena-demo.XXXXXX)"
cd backend
uv run arena demo --path "$demo_dir"
uv run arena provenance capture \
  --root .. \
  --study-pack ../study_packs/offline-demo-v1/study-pack.json \
  --output "$demo_dir/provenance.json"
```

Both commands are provider-free, machine-readable, and fail closed. The demo is a hash-verified synthetic fixture replay; its descriptive effects are not model-performance evidence.

## Verification

```bash
cd backend
uv sync --extra dev
uv run pytest -q
```

Protocol-v1 focused checks from the repository root:

```bash
uv run --project backend python -m pytest backend/tests/protocol_v1 backend/tests/persistence_v1 backend/tests/integration_v1 -q
uv run --project backend arena --help
```

## Trace Audits

```bash
uv run --project backend python scripts/trace-audit.py --limit 100
```

The audit CLI can also ingest JSON fixtures and emit a Markdown report:

```bash
uv run --project backend python scripts/trace-audit.py \
  --input backend/tests/fixtures/trace_audit/sample_runs.json \
  --output docs/reviews/trace-driven-frontier-audit.md
```

## Key Modules

- `main.py`: app construction, lifespan, middleware, router inclusion, and SPA serving.
- `api/`: endpoint request models and cohesive HTTP routers.
- `api/deps.py`: shared HTTP validation, budget checks, idempotency state, and rate limiting.
- `core/run_engine.py`: run execution and SSE queue handling.
- `core/run_lifecycle.py`: in-memory run state and diagnostics helpers.
- `core/provider.py`: model-provider abstraction and retry behavior.
- `evaluation/harness.py`: weighted scoring and evaluation profiles.
- `core/storage.py`: SQLite persistence.
- `audit/trace_audit.py`: offline trace-quality audit engine.
- `protocol_v1/`, `factors_v1/`, `adapters_v1/`: versioned study, treatment,
  harness, and adapter contracts.
- `persistence_v1/`, `execution_v1/`, `evaluation_v1/`: durable jobs, event
  cursors, provider usage, deterministic evaluation, and fail-closed workers.
- `services_v1/`, `api/v1/`: project-scoped registry, execution, analysis,
  evidence, review, retention, settings, and typed HTTP routes.
- `auth_v1/`, `artifacts_v1/`: team-mode OIDC/session policy and
  content-addressed local/S3-compatible artifact stores.
