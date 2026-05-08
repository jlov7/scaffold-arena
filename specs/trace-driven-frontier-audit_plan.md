## Trace-Driven Frontier Audit Plan

### Step 1: Red Tests

- Add backend tests for a representative flawed run record.
- Assert winner mismatch, zero-cost token usage, low metric classification, report summaries, and JSON fixture ingestion.

### Step 2: Audit Core

- Add `backend/audit/trace_audit.py`.
- Define dataclasses for findings and reports.
- Implement run/scaffold classification, severity sorting, taxonomy summaries, and Markdown rendering.

### Step 3: CLI

- Add `scripts/trace-audit.py`.
- Support `--input` JSON file and optional `--output` Markdown file.
- Support storage-backed audits later through the same core functions.

### Step 4: Evidence Artifact

- Add `backend/tests/fixtures/trace_audit/sample_runs.json`.
- Generate `docs/reviews/trace-driven-frontier-audit.md` from the fixture.

### Step 5: Verification

- Run targeted red/green backend test.
- Run full backend pytest.
- Run the CLI against the fixture and confirm the report is deterministic.
