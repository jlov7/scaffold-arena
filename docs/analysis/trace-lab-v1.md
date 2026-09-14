# Trace Lab v1

Trace Lab is a bounded, persistence-backed comparison of two attempts in one
project and one experiment. It accepts only attempt identifiers, an optional
event-id-to-semantic-anchor declaration, and `diagnostic_partial_mode`.
Callers cannot submit events, payloads, outcomes, costs, or reconstructed
traces.

`POST /api/v1/trace-analyses`

```json
{
  "left_attempt_id": "attempt-left",
  "right_attempt_id": "attempt-right",
  "declared_semantic_anchors": {},
  "diagnostic_partial_mode": false
}
```

Supply project context through `X-Arena-Project-Id` (or `project_id`). The
service re-reads append-only `trace` events through `ArenaRepository`, verifies
ownership and shared experiment binding, normalizes declared trace sequence,
aligns semantic anchors without comparing clocks, and hashes the canonical
response. Repeating the same request against unchanged persistence returns the
same `analysis_digest`.

The response links the two raw persisted attempts, reports source event IDs,
alignment numerator/denominator/exclusions, and the first observed meaningful
divergence. That divergence is always `DIAGNOSTIC_ONLY`; it does not attribute
cause or reconstruct an outcome. State context is limited to observed
`state_ref` values (including the bounded `payload.state_ref` shape). Credential
keys use the execution-control redaction convention.

Incomplete attempts, absent `trace_complete=true` evidence, sequence gaps, and persisted ordering anomalies are
rejected with `HOLD` unless `diagnostic_partial_mode` is explicitly `true`.
Malformed, duplicate-sequence, or absent persisted traces remain `HOLD`: Trace
Lab will not invent missing or ambiguous events.

## Runtime wiring

The application lifespan instantiates
`TraceLabService(repository, personal_project_id=...)` at
`app.state.trace_lab_service`, and the v1 router aggregate includes
`api.v1.trace_lab.router`. No separate worker or provider is started.
