# Arena Forge, next-best-experiment planning, and process safety v1

Arena Forge is a provider-free product-control boundary. It records an untrusted candidate, an independent evaluation record, a human-or-policy admission decision, a constrained planning report, and digest-only process-safety findings. It does not execute a candidate, inspect sealed holdout contents, launch a provider or tool, call a network destination, apply a patch, or merge a change.

```text
Forge proposes.
Arena Core evaluates.
Humans or policy admit.
```

## Forge lifecycle

1. `POST /api/v1/forge/proposals` stores an untrusted, content-addressed proposal as `PENDING_APPROVAL`.
2. A distinct owner or policy actor makes one immutable `APPROVED` or `REJECTED` decision through the proposal approval route. Approval grants neither execution nor merge authority.
3. An evaluation can be recorded only for an approved proposal, a project-scoped `PASS` process-safety report, a distinct evaluator, and a distinct admitting human or policy actor.
4. The service atomically creates an immutable Evolution Receipt and moves the proposal from `APPROVED` to one of `ADMITTED`, `REJECTED`, `QUARANTINED`, or `INCONCLUSIVE`.

An Evolution Receipt is content-addressed and protected from update or deletion in the durable schema. A receipt is custody evidence; it is not a model result, security assessment, containment proof, or permission to execute or merge.

## Proposal and evaluation bindings

A proposal binds the proposer identity, source-provenance digest, distinct base and candidate Genome digests, exactly one changed mechanism, patch/config digest, falsifiable prediction, expected quality/safety/cost/latency trade-off, triggering evidence digests, rollback and recovery identities, and a narrow claim scope. The contract rejects execution requests, auto-merge requests, self-evaluation, and unconstrained scalar optimization.

An evaluation binds an independent evaluator, a frozen experiment and analysis plan, cancellation and recovery policies, deterministic score weight of at least 70%, matched-compute budget, result/evidence digests, effect estimates with uncertainty, retained failure records, and observed-or-unknown usage and cost. Its workflow is explicitly `completed`, `interrupted`, `cancelled`, or `recovered`; interrupted/cancelled work requires interruption evidence, recovered work requires both interruption and recovery evidence, and neither interrupted nor cancelled work can be admitted. A recorded rollback requires its own evidence digest. Development, safety, and optional transfer item sets are checked for disjointness. Sealed holdout contents are never supplied to Forge: the contract holds only a sealed manifest and sealed-runner receipt digest.

Every evaluation includes these matched controls under the same frozen evaluator configuration and compute budget:

- random search;
- heuristic edits;
- no change; and
- matched-compute test-time search.

The contract rejects evaluator changes, sealed-holdout inspection, failure erasure, self-grading, self-promotion, and automatic merge. Severe or admission-blocking retained failures prevent `ADMITTED`. `ADMITTED` is a record-only policy outcome: it grants no execution or merge authority and establishes neither evidence validity nor a security, containment, deployment, or model-performance claim.

## Next-best-experiment planner

`POST /api/v1/experiment-plans/next-best` is a bounded design simulation. Its inputs are declared mechanism and interaction uncertainty, task coverage, prior evidence, per-attempt cost, risk, MDE, and remaining budget. It ranks only caller-declared candidate designs that fit the maximum risk and minimum affordable attempt constraints. Rankings report expected information gain, attempt count, cost interval, risk, assumptions, alternatives, and the claim ceiling. Designs that do not fit are retained with an exclusion reason.

Exploratory requests may rank alternatives but do not carry a frozen confirmatory analysis plan. Confirmatory requests require a frozen analysis-plan digest and reject exploratory adaptation. A `READY` planner report means only that an input design fits the declared simulation constraints; it is not an execution, admission, performance, or security result.

## Process safety and information flow

`POST /api/v1/process-safety-reports` accepts only digest and redacted-manifest references. It labels every flow as `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`, or `SECRET`, and tracks the source and destination across `context`, `model`, `tool`, `memory`, `artifact`, and `external`.

Every report contains exactly one typed outcome for each of:

- unnecessary sensitive-data access;
- prohibited tool;
- permission escalation;
- network egress;
- secret exposure;
- unsafe intermediate artifact;
- policy-bypassing retry;
- sensitive persistent memory;
- trace/log leakage; and
- cleanup failure.

The checks fail closed for sensitivity scope, unallowlisted tool flows, external destinations, delegation depth, secret retention, and unsafe lifecycle transitions. Each typed outcome is `NOT_OBSERVED`, `BLOCKED`, `DETECTED`, or `UNKNOWN`: detected controls fail the report and unknown controls keep it on HOLD. Restricted and secret flows require a redacted manifest. The report keeps digests and redacted manifests rather than raw sensitive content.

## API and CLI

The API is project-scoped; team-mode mutations require normal session, CSRF, and role controls. Proposal approval requires an administrator role in team mode. The primary routes are listed in the [API reference](api-reference.md).

The public CLI is deliberately limited:

```bash
arena forge proposal --input examples/arena-forge/proposal.json
arena forge plan --input examples/arena-forge/planner-exploratory.json
arena forge process-safety --input examples/arena-forge/process-safety-pass.json
arena forge evaluate
```

The proposal command always returns `HOLD`; the evaluation command also returns `HOLD` with its durable, independently separated prerequisites. Neither command can approve, self-grade, execute, promote, or merge a candidate.

## Evidence boundary

These controls are tested with provider-free fixtures and exact-head repository verification. A local `PASS`, artifact digest, planner ranking, or Evolution Receipt establishes product-control behavior only. It does not establish security assurance, containment, a live model-performance result, human calibration, deployment approval, or independent reproduction.
