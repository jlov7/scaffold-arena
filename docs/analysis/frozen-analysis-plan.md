# Frozen binary-outcome analysis plan

Scaffold Arena can assess prospective binary main-effect adequacy before a provider call is started. The plan is strict declarative data stored in the existing protocol-v1 experiment extension map:

```text
org.scaffold-arena.analysis-plan
```

Because experiment extensions are canonical, immutable and included in the experiment freeze hash, the declared assumptions become part of the same frozen study identity without changing protocol version `1.0`.

## Initial supported design

The `binary-outcome-v1` planner deliberately supports one narrow design class:

- fixed-sample studies;
- a full factorial design;
- binary factors only;
- pooled two-group main effects;
- a binary primary outcome;
- the risk-difference estimand;
- a two-sided normal-approximation sample-size calculation;
- optional cluster design-effect inflation;
- explicit planned comparison identities and multiplicity correction.

Fractional designs, custom matrices, categorical or ordinal factors, interaction-power claims, sequential stopping, continuous outcomes and fitted hierarchical-model power are explicit HOLDs. They are not approximated silently.

## Extension schema

```json
{
  "org.scaffold-arena.analysis-plan": {
    "schema_version": "binary-outcome-v1",
    "primary_outcome": "mission_success",
    "estimand": "risk_difference",
    "baseline_rate": 0.50,
    "minimum_detectable_effect": 0.20,
    "expected_direction": "increase",
    "alpha": 0.05,
    "power": 0.80,
    "comparison_ids": ["planning_main_effect"],
    "intracluster_correlation": 0.00,
    "mean_cluster_size": 1.0,
    "stopping_policy": "fixed_sample",
    "missingness_policy": "complete_case_with_exclusions"
  }
}
```

The plan rejects unknown fields, coercion, duplicate or blank comparison IDs, non-finite values, out-of-range probabilities, unsupported estimands, adaptive stopping labels and undeclared missingness behavior.

## Prospective calculation

For declared control and treatment rates `p0` and `p1`, two-sided per-comparison alpha `α`, and target power `1-β`, the nominal equal group size is:

```text
p̄ = (p0 + p1) / 2

n = ceil(
      [
        z(1-α/2) * sqrt(2 p̄ (1-p̄))
        + z(1-β) * sqrt(p0(1-p0) + p1(1-p1))
      ]²
      / (p1-p0)²
    )
```

Cluster inflation is:

```text
design_effect = 1 + (mean_cluster_size - 1) * intracluster_correlation
required_per_group = ceil(n * design_effect)
```

The available pooled observations on each side of one full-binary-factor main effect are calculated from the frozen design:

```text
scenario_count
× harness_count
× max(endpoint_count, 1)
× repetitions
× half_of_full_factorial_treatment_arms
```

This is the **scheduled** count before missingness, provider failure, exclusions, protocol HOLDs or unusable evidence.

## Multiplicity

A plan with more than one comparison ID and `multiple_comparison_correction: none` receives a HOLD.

Bonferroni uses:

```text
alpha_per_comparison = alpha / comparison_count
```

Holm and Benjamini–Hochberg planning also use this conservative Bonferroni value. Their final registered procedures may be less conservative, but the prospective gate does not assume that advantage.

## Adequacy gates

The planner returns:

- `PASS` — the strict plan and supported design pass every prospective gate;
- `HOLD` — the plan is valid but the design is unsupported, underpowered, multiplicity-uncontrolled, outcome-mismatched or unsuitable for the normal approximation;
- `INVALID` — the declared extension cannot satisfy the strict plan contract or produces an impossible expected treatment rate;
- `NOT_DECLARED` — no frozen plan exists.

The normal approximation requires at least ten expected events and ten expected non-events in each scheduled pooled group under the declared rates.

## Provider-free interfaces

### CLI

```bash
arena experiment analysis-plan --spec /path/to/experiment.json
```

The installed command writes one machine-readable JSON object. Exit status is `0` only for `PASS`; all HOLD, INVALID, NOT_DECLARED and malformed-input states return `2`.

### API

```http
POST /api/v1/analysis-plans/assess
Content-Type: application/json
```

The request body is a strict protocol-v1 `ExperimentSpec`. The endpoint is registered on the ordinary `/api/v1` router, reads no project records, result rows, provider credentials or prior effects, returns `409 HOLD` for a valid but inadequate plan, and returns `400` for an invalid request or invalid plan.

Both interfaces include:

```json
{"provider_execution_started": false}
```

## Claim boundary

This assessment is prospective design metadata, not outcome evidence. It does not prove:

- that the declared baseline rate is correct;
- that the minimum detectable effect is scientifically important;
- that attempts are independent;
- that the declared intracluster correlation is correct;
- that scheduled attempts will complete or remain eligible;
- that a normal approximation is the final inferential model;
- that a passed plan achieves its nominal power in the realized study;
- that an observed effect is causal, transferable or externally valid.

Assumptions must be justified by preregistration or external evidence rather than selected after observing Scaffold Arena results. Final analysis remains governed by frozen outcomes, exclusions, fidelity, comparison invariants, evaluator independence, multiplicity and evidence maturity.
