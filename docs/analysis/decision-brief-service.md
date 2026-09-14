# Decision Brief service

`POST /api/v1/decision-briefs` accepts either `analysis_report_id` or the exact
`experiment_id` and `execution_id` pair, plus `risk_constraints` and
`proposed_claims`. Proposed claims may link only durable evidence receipt IDs.
Caller-provided maturity labels, receipt hashes, report hashes, and artifact
references are rejected.

The service reloads the immutable report artifact, verifies both its content
address and AnalysisReport canonical hash, and freshly verifies every linked
receipt against its registered custody artifacts. Each receipt must also carry
the exact analysis execution ID; its manifest experiment and frozen hashes must
match the immutable report's execution binding. Null, cross-execution, or
mismatched-manifest receipts are recorded as `HOLD`, never rebound to a report.
Only the service-owned
`fixture` and `local_live` receipt types receive a maturity. Generic
reproduction, cross-model, human-calibration, and independence records cannot
self-promote; linked claims are durably recorded as `HOLD` until a dedicated
workflow admits them.

Each report has one immutable decision record. An exact semantic replay is
idempotent; a changed request for that report conflicts. The paired canonical
Decision Brief and Claim Ledger are content-addressed artifacts. `GET
/api/v1/decision-briefs/{id}` returns metadata, claim ceiling, receipt links,
and artifact references only; artifact contents remain withheld.

`arena results brief --database <url> --artifacts <root> --project <id>
--input <request.json>` calls this same service and never starts a provider.
