# Scripts

Repository-level maintenance and verification utilities.

## Public release checks

```bash
./scripts/scan-secrets.sh
./scripts/verify-all.sh
uv run --project backend python scripts/trace-audit.py --limit 100
```

## Script index

- `scan-secrets.sh` - scans tracked and untracked non-ignored files for high-risk secret patterns.
- `trace-audit.py` - audits saved run traces or JSON fixtures for ranked system-quality findings.
- `verify-all.sh` - runs secret scan + backend tests + trace-audit smoke + frontend lint/test/build.

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
