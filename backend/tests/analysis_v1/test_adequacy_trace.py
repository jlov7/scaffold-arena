import inspect
from datetime import UTC, datetime, timedelta

from analysis_v1.adequacy import (
    AdequacyInput,
    AnalysisClaimLevel,
    MixedEffectStatus,
    assess_analysis_adequacy,
)
from analysis_v1.trace import (
    SemanticAnchor,
    TraceEvent,
    align_traces,
    first_meaningful_divergence,
    normalize_trace,
)


def event(
    identifier: str,
    anchor: SemanticAnchor,
    sequence: int,
    seconds: int,
    ref: str | None = None,
    digest: str | None = None,
) -> TraceEvent:
    values = {
        "event_id": identifier,
        "anchor": anchor,
        "sequence": sequence,
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds),
        "monotonic_ms": float(sequence * 10),
        "evidence_ref": ref,
    }
    if "observation_digest" in inspect.signature(TraceEvent).parameters:
        values["observation_digest"] = digest
    return TraceEvent(**values)


def test_adequacy_is_descriptive_until_every_requirement_is_met_and_never_fakes_mixed_effects():
    inadequate = assess_analysis_adequacy(AdequacyInput(5, 1, 5, 0, 0.8, 0.8, external_fitted_model_result="model.pdf"))
    assert inadequate.claim_level is AnalysisClaimLevel.DESCRIPTIVE_ONLY
    assert inadequate.mixed_effect_status is MixedEffectStatus.NOT_RUN
    superficially_adequate = assess_analysis_adequacy(AdequacyInput(80, 8, 40, 40, 1.0, 1.0))
    assert superficially_adequate.claim_level is AnalysisClaimLevel.DESCRIPTIVE_ONLY
    assert "design was not preregistered" in superficially_adequate.reasons
    assert "evaluator independence gate failed" in superficially_adequate.reasons
    adequate = assess_analysis_adequacy(AdequacyInput(
        80, 8, 40, 40, 1.0, 1.0,
        preregistered_design=True,
        treatment_manipulation_fidelity_pass=True,
        comparison_invariants_pass=True,
        evaluator_independence_pass=True,
        sealed_or_held_out_tasks_pass=True,
        external_fitted_model_result="external-model-receipt",
    ))
    assert adequate.claim_level is AnalysisClaimLevel.DESCRIPTIVE_ONLY
    assert adequate.mixed_effect_status is MixedEffectStatus.NOT_RUN
    assert (
        "derived persisted comparison-invariant evidence is unavailable; caller-supplied comparison_invariants_pass cannot establish eligibility"
        in adequate.reasons
    )


def test_trace_alignment_is_clock_skew_tolerant_and_diagnosis_defaults_noncausal():
    left = normalize_trace((event("a", SemanticAnchor.REQUEST, 0, 0), event("b", SemanticAnchor.TOOL_CALL, 1, 1, "left-tool"), event("c", SemanticAnchor.MODEL_RESPONSE, 2, 2)))
    skewed = normalize_trace((event("x", SemanticAnchor.REQUEST, 0, 300), event("y", SemanticAnchor.TOOL_CALL, 1, 302, "right-tool"), event("z", SemanticAnchor.MODEL_RESPONSE, 2, 304)))
    assert align_traces(left, skewed).matched_anchors == 3
    same = first_meaningful_divergence(left, skewed)
    assert same.found is False
    assert same.diagnostic_only is True


def test_reordered_and_truncated_traces_yield_evidence_backed_diagnostic_divergences():
    left = normalize_trace((event("a", SemanticAnchor.REQUEST, 0, 0), event("b", SemanticAnchor.TOOL_CALL, 1, 1, "tool-ref"), event("c", SemanticAnchor.MODEL_RESPONSE, 2, 2, "response-ref")))
    reordered = normalize_trace((event("x", SemanticAnchor.REQUEST, 0, 9), event("y", SemanticAnchor.MODEL_RESPONSE, 1, 11, "other-response"), event("z", SemanticAnchor.TOOL_CALL, 2, 12)))
    reordered_result = first_meaningful_divergence(left, reordered)
    assert reordered_result.found is True
    assert reordered_result.evidence_refs == ("tool-ref", "other-response")
    truncated_result = first_meaningful_divergence(left, normalize_trace((event("x", SemanticAnchor.REQUEST, 0, 0),)))
    assert truncated_result.found is True
    assert "truncated" in truncated_result.reason or "unmatched" in truncated_result.reason
    asserted_invariants = first_meaningful_divergence(
        left,
        reordered,
        preregistered_intervention=True,
        counterfactual_replication=True,
        manipulation_fidelity_pass=True,
        comparison_invariants_pass=True,
    )
    assert asserted_invariants.diagnostic_only is True
    assert asserted_invariants.causal_label == "DIAGNOSTIC_ONLY"
    unreferenced_left = normalize_trace((event("l", SemanticAnchor.REQUEST, 0, 0), event("m", SemanticAnchor.TOOL_CALL, 1, 1)))
    unreferenced = normalize_trace((event("u", SemanticAnchor.REQUEST, 0, 0), event("v", SemanticAnchor.MODEL_RESPONSE, 1, 1)))
    missing_evidence = first_meaningful_divergence(
        unreferenced_left,
        unreferenced,
        preregistered_intervention=True,
        counterfactual_replication=True,
        manipulation_fidelity_pass=True,
        comparison_invariants_pass=True,
    )
    assert missing_evidence.diagnostic_only is True


def test_trace_event_contract_carries_an_observation_digest() -> None:
    assert "observation_digest" in inspect.signature(TraceEvent).parameters
    observed = event(
        "observed",
        SemanticAnchor.TOOL_CALL,
        0,
        0,
        digest="a" * 64,
    )
    assert observed.observation_digest == "a" * 64
    assert normalize_trace((observed,))[0].observation_digest == "a" * 64


def test_alignment_prefers_exact_observations_across_repeated_anchors() -> None:
    left = normalize_trace(
        (
            event("left-a", SemanticAnchor.TOOL_CALL, 0, 0, digest="a" * 64),
            event("left-b", SemanticAnchor.TOOL_CALL, 1, 1, digest="b" * 64),
        )
    )
    right = normalize_trace(
        (
            event("right-extra", SemanticAnchor.TOOL_CALL, 0, 0, digest="f" * 64),
            event("right-a", SemanticAnchor.TOOL_CALL, 1, 1, digest="a" * 64),
            event("right-b", SemanticAnchor.TOOL_CALL, 2, 2, digest="b" * 64),
        )
    )

    alignment = align_traces(left, right)
    assert [item.status for item in alignment.alignments] == [
        "RIGHT_ONLY",
        "MATCH",
        "MATCH",
    ]
    assert [
        (item.left_ordinal, item.right_ordinal)
        for item in alignment.alignments
    ] == [(None, 0), (0, 1), (1, 2)]


def test_same_anchor_with_different_observation_is_an_explicit_divergence() -> None:
    left = normalize_trace(
        (event("left", SemanticAnchor.TOOL_RESULT, 0, 0, "left-evidence", "a" * 64),)
    )
    right = normalize_trace(
        (event("right", SemanticAnchor.TOOL_RESULT, 0, 0, "right-evidence", "b" * 64),)
    )

    alignment = align_traces(left, right)
    assert alignment.content_differences == 1
    assert alignment.alignments[0].status == "CONTENT_DIFFERENCE"
    divergence = first_meaningful_divergence(left, right)
    assert divergence.found is True
    assert divergence.left_ordinal == 0
    assert divergence.right_ordinal == 0
    assert "observation digests differ" in divergence.reason
    assert divergence.evidence_refs == ("left-evidence", "right-evidence")


def test_inserted_event_does_not_shift_later_exact_matches() -> None:
    left = normalize_trace(
        (
            event("left-request", SemanticAnchor.REQUEST, 0, 0, digest="1" * 64),
            event("left-tool", SemanticAnchor.TOOL_CALL, 1, 1, digest="2" * 64),
            event("left-response", SemanticAnchor.MODEL_RESPONSE, 2, 2, digest="3" * 64),
        )
    )
    right = normalize_trace(
        (
            event("right-request", SemanticAnchor.REQUEST, 0, 0, digest="1" * 64),
            event("right-state", SemanticAnchor.STATE_CHANGE, 1, 1, "state-evidence", "4" * 64),
            event("right-tool", SemanticAnchor.TOOL_CALL, 2, 2, digest="2" * 64),
            event("right-response", SemanticAnchor.MODEL_RESPONSE, 3, 3, digest="3" * 64),
        )
    )

    alignment = align_traces(left, right)
    assert [item.status for item in alignment.alignments] == [
        "MATCH",
        "RIGHT_ONLY",
        "MATCH",
        "MATCH",
    ]
    divergence = first_meaningful_divergence(left, right)
    assert divergence.left_ordinal is None
    assert divergence.right_ordinal == 1
    assert "unmatched state_change" in divergence.reason
