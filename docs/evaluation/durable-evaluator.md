# Durable evaluator worker

The evaluator is separate from the agent harness, not externally independent. It accepts only a project and an attempt identifier, rereads the frozen pack and captured artifacts, and writes one immutable evaluation record per attempt.

`within_budget` is not inferred from the presence of a cost. The evaluator requires reconciled provider cost evidence and a matching immutable per-attempt budget recovered from both the persisted attempt envelope and the execution's persisted budget envelope. A missing, malformed, or mismatched envelope leaves the outcome cost status `unknown`; a reconciled cost above that bound is `over_budget`.

Integration contract for the execution worker: terminalize an attempt through `JobLeaseRepository.finalize_with_followup(..., followup_kind="evaluation")`; this writes the terminal metadata, completes the attempt job, and queues evaluation in one transaction before execution terminal status is derived. `DurableEvaluationService(...).enqueue(project_id, attempt_id)` remains the idempotent API/control-plane enqueue path for already captured attempts.

`EvaluationWorker.run_once()` claims only `evaluation` jobs. A successfully evaluated adapter failure completes its evaluation job; evaluator infrastructure failures fail that job and the execution without changing the attempt status.

A worker that captures an adapter terminal result completes its attempt job,
even when the task outcome is failed, timed out, or incomplete. A retry is
allowed only for those captured non-success outcomes with a persisted declared
transient adapter/provider classification. The retry adds an ordinal attempt to
the same episode, preserves prior attempt/evaluation evidence, and leaves the
execution nonterminal while either prior or retry evaluation work remains.

`arena worker` runs bounded passes in this order: one `attempt` lease, then one
`evaluation` lease. The attempt worker never claims evaluation jobs, so an
evaluation-only queue does not invoke an adapter or start a provider. The CLI
uses an empty `TrustedGraderRegistry`: built-in deterministic graders remain
available through the compiler, while installed graders remain HOLD until a
runtime owner explicitly injects them.

## Grader identity boundary

Built-in grader declarations use a canonical digest of their validated configuration.
An `installed_plugin` declaration instead carries the installed plugin's supplied
64-hex artifact or code digest and has an empty configuration. Before compilation,
the exact `(grader_id, version, digest)` must already be present in the local trusted
grader registry. Study packs cannot name imports, packages, paths, or executable
code; a predictable hash of empty plugin metadata is not an installation credential.

## Source provenance grader

`source_provenance` grades only the completed canonical output. Its declaration
requires `claims_pointer` (an RFC 6901 JSON Pointer) and `required_sources` (a
non-empty `source_id` to SHA-256 mapping). The compiler rejects the pack unless every
required source exists in the selected frozen `ScenarioSpec.evidence_sources` with the
same hash. It may also declare `required_claim_sources` for preregistered claim/source
pairs and `unsupported_evidence_severe_rule_id` for an explicit severe failure on
unknown source IDs or hash mismatches.

The pointed value must be an array. Each entry is a consequential claim and must have
`claim_id` plus a non-empty `evidence` array of `{source_id, content_hash}` objects.
All cited sources must match the frozen scenario registry; every required source must
be cited, and preregistered pairs must be present. Harness trace payload, agent
narration, and caller-provided provenance metadata are never inputs to this grader.
