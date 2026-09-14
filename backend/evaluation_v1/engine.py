from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from protocol_v1 import EvaluationRecord, OutcomeVector

from .cost import reconciled_cost_status
from .graders import (
    DeterministicGrader,
    ManipulationFidelityGrader,
    StateOracleGrader,
    TrustedGraderRegistry,
)
from .models import (
    EvaluationContext,
    EvaluationResult,
    GraderPlan,
    GraderResult,
    QualitativeResult,
)


def evaluate_attempt(
    *,
    attempt: Any,
    output: str,
    context: EvaluationContext,
    plan: GraderPlan,
    registry: TrustedGraderRegistry,
    trace_hash: str,
    evaluation_id: str = "evaluation-v1",
    cost_usd: float | None = None,
    budget_limit_usd: float | None = None,
    latency_seconds: float | None = None,
    tool_calls: int = 0,
    qualitative_results: Iterable[QualitativeResult] = (),
) -> EvaluationResult:
    """Evaluate a completed attempt without mutating the adapter, run, or control plane."""
    episode_id = (
        attempt.episode_id
        if hasattr(attempt, "episode_id")
        else str(attempt.get("episode_id"))
    )
    supplied_qualitative = tuple(qualitative_results)
    qualitative_by_metric = {
        result.metric_id: result for result in supplied_qualitative
    }
    if len(qualitative_by_metric) != len(supplied_qualitative):
        raise ValueError("qualitative results may contain each metric only once")
    qualitative_bindings = {
        binding.metric_id: binding
        for binding in plan.bindings
        if binding.kind == "qualitative"
    }
    unexpected = set(qualitative_by_metric) - set(qualitative_bindings)
    if unexpected:
        raise ValueError(
            f"qualitative results are not declared in the plan: {sorted(unexpected)}"
        )
    results: list[GraderResult] = []
    deterministic: dict[str, float] = {}
    deterministic_passed: dict[str, bool] = {}
    qualitative: dict[str, float] = {}
    weighted = 0.0
    state_score: float | None = None
    severe: list[str] = []
    exclusions: list[str] = []
    qualitative_complete = (
        bool(qualitative_bindings) and plan.human_calibration_receipt is not None
    )
    for binding in plan.bindings:
        if binding.kind == "qualitative":
            observed = qualitative_by_metric.get(binding.metric_id)
            calibration = plan.human_calibration_receipt
            if observed is None:
                qualitative_complete = False
                exclusions.append(
                    f"qualitative metric {binding.metric_id} has no explicit observed result"
                )
                continue
            if calibration is None:
                qualitative_complete = False
                exclusions.append(
                    f"qualitative metric {binding.metric_id} has no bound HumanCalibrationReceipt"
                )
                continue
            bound = (
                observed.evaluator_id == binding.installation.grader_id
                and observed.evaluator_version == binding.installation.version
                and observed.evaluator_digest == binding.installation.digest
                and observed.calibration_receipt_id == calibration.receipt_id
                and observed.calibration_batch_hash == calibration.batch_hash
            )
            if not bound:
                qualitative_complete = False
                exclusions.append(
                    f"qualitative metric {binding.metric_id} does not bind to its plan installation and calibration receipt"
                )
                continue
            qualitative[binding.metric_id] = observed.score
            continue
        grader = plan.resolve_builtin(binding.installation) or registry.resolve(binding.installation)
        if not isinstance(grader, DeterministicGrader):
            raise TypeError(
                f"HOLD: deterministic binding {binding.metric_id} does not resolve to a deterministic trusted grader"
            )
        if isinstance(grader, ManipulationFidelityGrader):
            missing_observed = set(grader.expected_assignments) - set(context.factor_assignments)
            if missing_observed:
                raise ValueError(
                    "HOLD: manipulation fidelity requires trace-derived observed assignments for "
                    f"{sorted(missing_observed)}"
                )
        result = grader.evaluate(output, context)
        results.append(result)
        deterministic[binding.metric_id] = result.score
        deterministic_passed[binding.metric_id] = result.passed
        weighted += result.score * binding.weight
        severe.extend(result.severe_failures)
        if isinstance(grader, StateOracleGrader):
            state_score = result.score
    for rule_id, rule in context.severe_failure_rules.items():
        metric_id = rule.get("metric_id")
        if (
            rule.get("when") == "failed"
            and metric_id in deterministic
            and not deterministic_passed[metric_id]
        ):
            severe.append(rule_id)
    severe = sorted(set(severe))
    mission_success = (
        state_score
        if state_score is not None
        else (weighted / plan.deterministic_weight)
    )
    hard_gate_passed = not severe
    if qualitative_bindings and not qualitative_complete:
        exclusions.append(
            "qualitative judge metrics are ineligible until every metric has a bound observed result and HumanCalibrationReceipt"
        )
    outcome = OutcomeVector(
        episode_id=episode_id,
        mission_success=mission_success if hard_gate_passed else 0.0,
        severe_failures=tuple(severe),
        consistency=1.0 if hard_gate_passed else 0.0,
        cost_status=reconciled_cost_status(cost_usd, budget_limit_usd),
        cost_usd=cost_usd,
        latency_seconds=latency_seconds,
        tool_calls=tool_calls,
        auditability=1.0 if trace_hash else 0.0,
        deterministic=deterministic,
        # Mission success deliberately remains the normalized deterministic score or the state oracle.
        model_judged=qualitative if qualitative_complete else {},
    )
    record = EvaluationRecord(
        evaluation_id=evaluation_id,
        episode_id=episode_id,
        outcome=outcome,
        deterministic_weight=plan.deterministic_weight,
        evaluator_version="evaluation-v1",
        trace_hash=trace_hash,
    )
    return EvaluationResult(
        record,
        tuple(results),
        hard_gate_passed,
        qualitative_complete,
        tuple(exclusions),
    )
