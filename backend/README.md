# Backend Service

FastAPI backend for Scaffold Arena run orchestration, evaluation, diagnostics, and report/export APIs.

## Responsibilities

- Register tasks and scaffolds at startup.
- Create and stream runs via SSE (`POST /api/runs` -> `GET /api/runs/{id}/events`).
- Score outputs with deterministic-first evaluation profiles.
- Provide diagnostics (`/api/runs/{id}/diagnostics`) and export bundles (`/api/runs/{id}/export-bundle`).
- Persist completed runs to SQLite.

## Local Development

```bash
cd backend
cp .env.example .env
uv sync
uv run uvicorn main:app --reload --port 8000
```

## Verification

```bash
cd backend
uv run pytest -q
```

## Key Modules

- `main.py`: API routes and app lifecycle.
- `core/run_engine.py`: run lifecycle, SSE queue, diagnostics timeline.
- `core/provider.py`: model-provider abstraction and retry behavior.
- `evaluation/harness.py`: weighted scoring and evaluation profiles.
- `core/storage.py`: SQLite persistence.
