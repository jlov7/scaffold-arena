# Persistence-v1 scale validation

`scripts/scale/validate_v1_scale.py` checks the declared v1 logical scale of
50,000 attempts and 10,000,000 trace events without allocating those rows or
calling a provider. The default analytical path checks integer cursor bounds,
deterministic ID/sequence arithmetic, batch counts, the persistence-v1 index
contract, and SQLite query-plan assumptions for event pagination and job lease
filtering.

```bash
uv run --project backend python scripts/scale/validate_v1_scale.py
uv run --project backend python scripts/scale/validate_v1_scale.py --write
uv run --project backend python scripts/scale/validate_v1_scale.py --check
```

`--check` is the fast CI freshness check. It never writes. `--write` updates
`outputs/scale_validation.json`; the report is deterministic, so changes to
the persistence schema or validator contract make the check stale.

## Optional materialization

Materialization is manual and always requires an explicit new or empty SQLite
path. Inserts are batched and the provider layer is never invoked:

```bash
uv run --project backend python scripts/scale/validate_v1_scale.py \
  --materialize /tmp/scaffold-arena-scale.db
```

The materialized database is a small SQLite projection of attempts, events,
execution cursor, and the two event indexes. It is a resource-planning aid,
not a production migration or a substitute for a PostgreSQL load test. Do not
point it at an existing non-empty file.

## Claim ceiling and caveats

The exact claim ceiling is: **capacity model/schema validation only; not
production load evidence**. The arithmetic proves that the declared event
coordinates fit the positive SQL `INTEGER` cursor range and that the declared
unique-key mappings do not reuse a logical key. It does not prove throughput,
latency, lock behavior, recovery, connection-pool sizing, disk capacity,
replication, provider behavior, or production query performance.

The report's storage number is an explicitly parameterized planning estimate.
It excludes database pages, WAL, vacuum/fillfactor, JSON/TOAST encoding,
foreign-key indexes, jobs, backups, and provider artifacts. The lease index
covers `status`/`available_at` readiness filtering; v1 does not claim that it
covers `created_at,id` queue ordering, and the observed plan may use a sort.

10-million-event materialization remains optional/manual and must not be
described as production load evidence.
