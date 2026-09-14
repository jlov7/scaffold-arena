# Decision Brief and Claim Ledger v1

`analysis_v1.claims.build_decision_artifacts()` is a pure, deterministic gate
from one frozen `AnalysisReport` to two machine-readable artifacts:

- `DecisionBrief`: the verdict, severe failures first, outcome vector,
  uncertainty, exclusions, derived claim ceiling, blockers, and next lawful
  action. Its outcome vector carries each profile's observed pass, severe
  failure, auditability, latency, and cost components without synthesizing a
  caller-provided aggregate score.
- `ClaimLedger`: one row for every proposed claim, with its exact immutable
  receipt references, disposition, limitations, falsifiers, and the input
  AnalysisReport hash.

Neither artifact reads storage, calls a provider, runs an evaluation, writes a
receipt, or changes the input report. Both exclude their own `canonical_hash`
from canonical SHA-256 serialization. Inputs and output models are strict,
frozen Pydantic contracts; unknown fields and non-finite values fail.

## Required inputs

Build a frozen `DecisionRequest` from:

1. An immutable `AnalysisReport`.
2. Immutable `EvidenceReceiptReference` values. Each has a receipt ID,
   receipt SHA-256, maturity, artifact reference, and the exact
   `analysis_report_hash` it supports.
3. Frozen `RiskConstraints`.
4. `ProposedClaim` values, each linking one or more receipt IDs.

The allowed maturity values are `fixture`, `local_live`, `replicated`,
`cross_model`, `human_calibrated`, and `independent`. A request fails if a
receipt is not bound to the supplied report hash, receipt IDs repeat, a claim
ID repeats, or a claim links an unknown receipt.

`ProposedClaim` intentionally has no aggregate score, severe-failure,
estimate, exclusion, adequacy, or requested-ceiling field. The engine derives
all of those from the report. Risk constraints can only narrow a claim ceiling
or choose whether an already-present severe failure produces `HOLD` or
`REJECT`; they cannot waive any hard gate.

## Claim gates

Every proposed claim requires the maturity receipt linked to that specific
claim. A text label is never evidence.

| Claim kind | Required linked maturity | Additional hard gate |
| --- | --- | --- |
| `fixture_observation` | `fixture` | none beyond global gates |
| `local_live_observation` | `local_live` | none beyond global gates |
| `causal_effect` | `local_live` | confirmatory adequacy and an estimated effect |
| `generalized_effect` | `replicated` | confirmatory adequacy and an estimated effect |
| `cost_comparison` / `pareto_comparison` | `local_live` | no profile may have unknown cost |
| `cross_model_replication` | `cross_model` | corresponding linked cross-model receipt |
| `human_calibrated_assessment` | `human_calibrated` | corresponding linked human-calibration receipt |
| `independent_validation` | `independent` | corresponding linked independent receipt |

The linked-receipt rule means a fixture receipt cannot be relabelled in a
claim statement as cross-model, human-calibrated, or independent evidence.
Those claims remain `HOLD` until the corresponding distinct receipt is linked.

Global gates are fail-closed:

- Any severe failure blocks every claim. The verdict and affected rows are
  always `HOLD` or, when the frozen risk policy requires it, `REJECT` and
  `REJECTED`; no aggregate outcome can mask it.
- Any source exclusion blocks promotion; Pareto exclusions remain visible in
  the brief and block Pareto claims through their own eligibility rules.
- `DESCRIPTIVE_ONLY` adequacy blocks causal and generalized claims.
- Unknown profile cost blocks cost and Pareto claims. It is never zero-filled,
  estimated, or used to infer a Pareto result.

`SUPPORTED` means only that exact claim clears these gates for that exact
report and linked receipts. It does not imply deployment approval, broad model
capability, independent reproduction, human calibration, or a claim beyond
the ledger row's ceiling.

## Minimal use

```python
from analysis_v1.claims import build_decision_artifacts

artifacts = build_decision_artifacts(decision_request)
brief = artifacts.brief
ledger = artifacts.ledger
```

For a `HOLD`, follow `brief.next_lawful_action`, create a new immutable
AnalysisReport after the blocker is addressed, then bind new receipt references
to that new report hash. Do not edit or reuse the old decision artifacts as if
they proved the new result.
