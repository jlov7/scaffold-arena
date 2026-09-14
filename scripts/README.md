# Scripts

Repository-level maintenance and verification utilities.

## Public release checks

```bash
./scripts/scan-secrets.sh
python scripts/check-public-repo-hygiene.py
./scripts/verify-all.sh
./scripts/verify-release-gates.sh
uv run --project backend python scripts/trace-audit.py --limit 100
uv run --project backend python scripts/generate-protocol-v1-schemas.py --check
```

## Script index

- `scan-secrets.sh` - scans tracked and untracked non-ignored files for high-risk secret patterns.
- `check-public-repo-hygiene.py` - rejects private agent material, machine-local references, personal email literals, secrets, symlinks, unapproved root entries, missing public governance/evidence documents, and fixture-to-live claim escalation.
- `trace-audit.py` - audits saved run traces or JSON fixtures for ranked system-quality findings.
- `verify-all.sh` - runs the authoritative repository, backend, evidence, packaging, and frontend lint/test/build checks.
- `verify-release-gates.sh` - runs `verify-all.sh` plus locked Python and production-frontend dependency audits, content, coverage, layering, performance-budget, E2E, accessibility, visual, Lighthouse, and Docker production-integration gates. Docker/Compose absence fails closed, and the release gate rejects `SCAFFOLD_ARENA_SKIP_PRODUCTION_INTEGRATION=1`.
- `verify-clean-clone.sh` - clones the committed revision into an isolated temporary directory and runs the authoritative gate.
- `generate-protocol-v1-schemas.py` - deterministically exports public Draft 2020-12 Protocol v1 schemas from `backend/protocol_v1/models.py`; use `--check` in CI to detect drift without writing.
- `scale/validate_v1_scale.py` - bounded analytical validation of the persistence-v1 50,000-attempt/10,000,000-event capacity model; use `--check` in CI, and reserve `--materialize PATH` for explicit manual SQLite exercises.
- `test-postgres-v1.sh` - starts an isolated local PostgreSQL 16.4 container, runs Alembic-backed persistence-v1 parity contracts, and removes its named volume on exit. The image is pinned to its verified immutable digest.

## PostgreSQL persistence-v1 parity

```bash
./scripts/test-postgres-v1.sh
```

The script uses loopback only, chooses an unused local port unless `POSTGRES_TEST_PORT` is set, and always tears down its unique Compose project and volume.

## Trace audits

Audit saved SQLite runs:

```bash
uv run --project backend python scripts/trace-audit.py --limit 100
```

Audit explicit JSON fixtures and write Markdown:

```bash
uv run --project backend python scripts/trace-audit.py \
  --input backend/tests/fixtures/trace_audit/sample_runs.json \
  --output docs/reviews/trace-driven-frontier-audit.md
```
