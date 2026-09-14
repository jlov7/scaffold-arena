# StudyPack authoring guide

StudyPacks make a comparison inspectable before it runs. They are declarative JSON: the loader rejects executable source and symlinks, and a pack does not grant an adapter or evidence authority by itself.

## Start from the bundled fixture

Use [`offline-demo-v1`](../../study_packs/offline-demo-v1/) as the smallest working reference. It declares synthetic scenarios, a recorded offline harness, a factorized design, deterministic evaluation, controls, and an explicit fixture-only claim ceiling.

The import and list responses include the immutable pack's readiness report immediately. A deterministic contribution below 70% is returned as `HOLD`; it is not deferred until execution preflight, and does not elevate the pack's evidence or execution claim ceiling.

## Author in this order

1. Define scenarios, sources, expected state, and the allowed claim ceiling.
2. Reference a trusted, separately installed harness adapter; do not place executable code in the pack.
3. Define factors, control conditions, budgets, repetitions, and a deterministic evaluation weight of at least 70% for every task family.
4. Declare limitations and preregistration before freezing an experiment.
5. Validate the pack, freeze the experiment, and respect any typed `HOLD` from preflight.

## Validate locally

```bash
uv run --project backend arena pack validate study_packs/offline-demo-v1/study-pack.json
```

The protocol-v1 [schema entry point](../../specs/v1/README.md) is the authoritative static contract. The generated OpenAPI document at `http://localhost:8000/openapi.json` is the authoritative runtime request/response contract when the backend is running; it is generated from FastAPI routes and models so a checked-in duplicate cannot silently drift.

## Before making a claim

Validate schema and fixture bindings first. That validation remains fixture-only. Provider execution, calibrated review, and independent reproduction require their own evidence paths. See [evidence status](../evidence-status.md) and [adapter certification](../adapters/certification.md).
