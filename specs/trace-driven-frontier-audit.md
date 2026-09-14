## Feature: Trace-Driven Frontier Audit

### Requirements

- [R1] Must ingest persisted Scaffold Arena run records from JSON fixtures or the existing SQLite-backed storage shape.
- [R2] Must classify concrete failure modes across run integrity, scaffold output, evaluation evidence, cost/token accounting, and patch-rerun candidates.
- [R3] Must rank findings by severity and produce stable regression keys for follow-up tests.
- [R4] Must render a Markdown report suitable for `docs/reviews/` without live provider calls.
- [R5] Must keep the existing FastAPI/SSE/report/export API contracts unchanged.

### Constraints

- [C1] Cannot require Anthropic/OpenAI keys or paid model calls.
- [C2] Cannot change evaluator scoring semantics.
- [C3] Cannot depend on frontend runtime state.
- [C4] Cannot hide low-confidence findings as pass/fail claims; evidence must name the run/scaffold and observed anomaly.

### Acceptance Criteria

- [x] Given a run whose `winner_id` is not the highest scored result, the audit reports a high-severity `winner_not_highest_score` finding.
- [x] Given scaffold token usage with zero cost, the audit reports a cost-accounting finding.
- [x] Given low task-specific metric scores, the audit reports task-relevant failure types.
- [x] Given JSON input containing one or more run records, the CLI writes a Markdown report with severity and taxonomy summaries.
- [x] Backend tests cover ingestion, classification, sorting, and report rendering.

### Out of Scope

- Frontend integration of audit reports.
- New backend HTTP endpoints.
- Live provider benchmarking.
- Rewriting the evaluator or autopsy patch generator.
