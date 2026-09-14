# Failure Taxonomy

The failure taxonomy is the public vocabulary for trace-audit findings. Each finding should include severity, scope, evidence, recommendation, regression key, and a suggested fixture or test.

The machine-readable taxonomy sample is `docs/benchmarking/failure_taxonomy.json` and is validated against `specs/failure-taxonomy.schema.json`.

## Core Failure Types

| Type | Why It Matters |
| --- | --- |
| `low_total_score` | Prevents weak scaffold outputs from being treated as success. |
| `schema_missing_required_fields` | Blocks invalid structured outputs before downstream scoring or reporting. |
| `research_missing_citations` | Keeps synthetic research claims tied to source labels. |
| `unsupported_claims` | Flags claims that are not grounded in scenario evidence. |
| `privacy_boundary_violation` | Blocks outputs that repeat data the task required minimizing or excluding. |
| `scaffold_overreach` | Catches scaffolds that invent tools, actions, requirements, or unsupported assumptions. |
| `regression_from_previous_best` | Detects a scaffold falling behind a stored best result for the same task family. |
| `weak_evidence_trail` | Prevents high scores from being published without auditable evidence. |

## Severity Guidance

- Critical: privacy boundary, data minimization, or report-integrity breach.
- High: invalid schema, unsupported claims, winner mismatch, scaffold overreach, or missing cost from token usage.
- Medium: low score or weak evidence that blocks public release but not local iteration.
- Low/info: diagnostic findings that improve future investigation.
