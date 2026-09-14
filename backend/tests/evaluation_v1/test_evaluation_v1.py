from __future__ import annotations

import json

import pytest

from evaluation_v1 import (
    AdjudicationRecord,
    Annotation,
    EvaluationContext,
    GraderBinding,
    GraderInstallation,
    GraderPlan,
    QualitativeGrader,
    QualitativeResult,
    StateOracleGrader,
    TrustedGraderRegistry,
    assign_blindly,
    compile_grader_plan,
    complete_annotations,
    evaluate_attempt,
)
from protocol_v1 import ExperimentSpec, GraderSpec, HarnessSpec, ScenarioSpec, StudyPack

HASH = "a" * 64
ARTIFACT_HASH = "b" * 64


class Untrusted:
    grader_id = "evil"
    version = "1"
    digest = HASH


class InstalledQualitativeGrader(QualitativeGrader):
    def __init__(self, grader_id: str, version: str, digest: str) -> None:
        self.grader_id = grader_id
        self.version = version
        self.digest = digest


def installation(grader: StateOracleGrader) -> GraderInstallation:
    return GraderInstallation(
        grader_id=grader.grader_id, version=grader.version, digest=grader.digest
    )


def declared_grader(
    grader_id: str,
    *,
    implementation: str = "state_oracle",
    kind: str = "deterministic",
    config: dict | None = None,
    metric_id: str | None = None,
    weight: float | None = None,
    digest: str | None = None,
) -> GraderSpec:
    config = {"state_key": "committed", "expected": True} if config is None else config
    canonical_digest = GraderSpec.digest_for(
        grader_id=grader_id,
        version="1",
        implementation=implementation,
        kind=kind,
        config=config,
    )
    return GraderSpec(
        grader_id=grader_id,
        version="1",
        implementation=implementation,
        kind=kind,
        config=config,
        metric_id=metric_id,
        weight=weight,
        digest=canonical_digest if digest is None else digest,
    )


def compiler_pack(
    *graders: GraderSpec,
    deterministic_metrics: tuple[dict, ...] = ({"metric_id": "state", "weight": 1.0, "oracle": "state-check"},),
    evidence_sources: tuple[dict, ...] = (),
) -> tuple[StudyPack, ScenarioSpec]:
    scenario = ScenarioSpec(
        scenario_id="scenario-one",
        title="Scenario",
        task_family="extraction",
        prompt="Synthetic test prompt.",
        deterministic_metrics=deterministic_metrics,
        evidence_sources=evidence_sources,
    )
    pack = StudyPack(
        study_pack_id="pack-one",
        version="1.0.0",
        title="Pack",
        license_spdx="MIT",
        authors=({"name": "Protocol Test"},),
        compatibility={"protocol_min": "1.0", "protocol_max": "1.0"},
        allowed_claims=("Synthetic test only.",),
        limitations=("No live evidence.",),
        preregistration={"reference_uri": "synthetic://preregistration", "content_hash": HASH},
        scenarios=(scenario,),
        graders=graders,
        harnesses=(HarnessSpec(harness_id="harness-one", version="1", adapter="recorded"),),
        experiments=(
            ExperimentSpec(
                experiment_id="experiment-one",
                study_pack_id="pack-one",
                scenario_ids=("scenario-one",),
                harness_ids=("harness-one",),
                deterministic_weight=1.0,
            ),
        ),
    )
    return pack, scenario


def test_compiler_creates_scenario_scoped_builtin_plan_and_evaluates() -> None:
    pack, scenario = compiler_pack(declared_grader("state-check"))
    plan = compile_grader_plan(pack, scenario, TrustedGraderRegistry())
    assert plan.bindings[0].metric_id == "state"
    assert plan.bindings[0].installation.digest == pack.graders[0].digest
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output="{}",
        context=EvaluationContext(state_refs={"committed": True}),
        plan=plan,
        registry=TrustedGraderRegistry(),
        trace_hash=HASH,
    )
    assert result.record.outcome.deterministic == {"state": 1.0}


def test_compiler_bootstraps_deterministic_evaluation_without_calibration() -> None:
    plugin = declared_grader(
        "installed-judge",
        implementation="installed_plugin",
        kind="qualitative",
        config={},
        metric_id="judge",
        weight=0.3,
        digest=ARTIFACT_HASH,
    )
    deterministic = declared_grader("state-check")
    pack, scenario = compiler_pack(
        deterministic,
        plugin,
        deterministic_metrics=({"metric_id": "state", "weight": 0.7, "oracle": "state-check"},),
    )
    registry = TrustedGraderRegistry()
    with pytest.raises(LookupError, match="not installed"):
        compile_grader_plan(pack, scenario, registry)
    installed = InstalledQualitativeGrader(
        plugin.grader_id, plugin.version, plugin.digest
    )
    registry.install(installed, GraderInstallation(
        grader_id=plugin.grader_id, version=plugin.version, digest=plugin.digest
    ))
    uncalibrated = compile_grader_plan(pack, scenario, registry)
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"}, output="{}",
        context=EvaluationContext(state_refs={"committed": True}),
        plan=uncalibrated, registry=registry, trace_hash=HASH,
    )
    assert result.record.outcome.deterministic == {"state": 1.0}
    assert not result.qualitative_claims_eligible
    assert any("no explicit observed result" in exclusion for exclusion in result.exclusions)
    plan = compile_grader_plan(
        pack,
        scenario,
        registry,
        {
            "receipt_id": "calibration-one",
            "batch_hash": "b" * 64,
            "protocol_hash": "c" * 64,
            "review_completion_digest": "d" * 64,
            "annotator_count": 3,
            "resolved_conflicts": True,
            "identity_state": "verified",
            "authority_id": "review-authority",
            "attestation_ref": "evidence://review-attestation",
        },
    )
    assert plan.deterministic_weight == 0.7


def test_compiler_holds_when_deterministic_weight_is_below_floor() -> None:
    qualitative = declared_grader(
        "installed-judge", implementation="installed_plugin", kind="qualitative",
        config={}, metric_id="judge", weight=0.4, digest=ARTIFACT_HASH,
    )
    deterministic = declared_grader("state-check")
    pack, scenario = compiler_pack(
        deterministic, qualitative,
        deterministic_metrics=({"metric_id": "state", "weight": 0.6, "oracle": "state-check"},),
    )
    registry = TrustedGraderRegistry()
    registry.install(
        InstalledQualitativeGrader(qualitative.grader_id, qualitative.version, qualitative.digest),
        GraderInstallation(
            grader_id=qualitative.grader_id, version=qualitative.version, digest=qualitative.digest,
        ),
    )
    with pytest.raises(ValueError, match="at least 0.70"):
        compile_grader_plan(pack, scenario, registry)


def test_compiler_requires_exact_deterministic_plugin_artifact_digest() -> None:
    metadata_digest = GraderSpec.digest_for(
        grader_id="installed-state",
        version="1",
        implementation="installed_plugin",
        kind="deterministic",
        config={},
    )
    declared = declared_grader(
        "installed-state",
        implementation="installed_plugin",
        kind="deterministic",
        config={},
        digest=metadata_digest,
    )
    pack, scenario = compiler_pack(
        declared,
        deterministic_metrics=({"metric_id": "state", "weight": 1.0, "oracle": "installed-state"},),
    )
    registry = TrustedGraderRegistry()
    installed = StateOracleGrader("committed", True)
    installed.grader_id, installed.version, installed.digest = (
        declared.grader_id,
        declared.version,
        ARTIFACT_HASH,
    )
    registry.install(
        installed,
        GraderInstallation(
            grader_id=declared.grader_id,
            version=declared.version,
            digest=ARTIFACT_HASH,
        ),
    )
    with pytest.raises(LookupError, match="not installed"):
        compile_grader_plan(pack, scenario, registry)

    metadata_installed = StateOracleGrader("committed", True)
    metadata_installed.grader_id, metadata_installed.version, metadata_installed.digest = (
        declared.grader_id,
        declared.version,
        metadata_digest,
    )
    registry.install(
        metadata_installed,
        GraderInstallation(
            grader_id=declared.grader_id,
            version=declared.version,
            digest=metadata_digest,
        ),
    )
    metadata_plan = compile_grader_plan(pack, scenario, registry)
    assert metadata_plan.bindings[0].installation.digest == metadata_digest

    exact = declared_grader(
        "installed-state",
        implementation="installed_plugin",
        kind="deterministic",
        config={},
        digest=ARTIFACT_HASH,
    )
    exact_pack, exact_scenario = compiler_pack(
        exact,
        deterministic_metrics=({"metric_id": "state", "weight": 1.0, "oracle": "installed-state"},),
    )
    plan = compile_grader_plan(exact_pack, exact_scenario, registry)
    assert plan.bindings[0].installation.digest == ARTIFACT_HASH


def test_compiler_requires_exact_qualitative_plugin_artifact_digest() -> None:
    declared = declared_grader(
        "installed-judge",
        implementation="installed_plugin",
        kind="qualitative",
        config={},
        metric_id="judge",
        weight=0.3,
        digest=ARTIFACT_HASH,
    )
    deterministic = declared_grader("state-check")
    pack, scenario = compiler_pack(
        deterministic,
        declared,
        deterministic_metrics=({"metric_id": "state", "weight": 0.7, "oracle": "state-check"},),
    )
    registry = TrustedGraderRegistry()
    wrong_digest = "c" * 64
    registry.install(
        InstalledQualitativeGrader(declared.grader_id, declared.version, wrong_digest),
        GraderInstallation(
            grader_id=declared.grader_id,
            version=declared.version,
            digest=wrong_digest,
        ),
    )
    with pytest.raises(LookupError, match="not installed"):
        compile_grader_plan(pack, scenario, registry)

    registry.install(
        InstalledQualitativeGrader(declared.grader_id, declared.version, ARTIFACT_HASH),
        GraderInstallation(
            grader_id=declared.grader_id,
            version=declared.version,
            digest=ARTIFACT_HASH,
        ),
    )
    plan = compile_grader_plan(
        pack,
        scenario,
        registry,
        {
            "receipt_id": "calibration-one",
            "batch_hash": "b" * 64,
            "protocol_hash": "c" * 64,
            "review_completion_digest": "d" * 64,
            "annotator_count": 3,
            "resolved_conflicts": True,
            "identity_state": "verified",
            "authority_id": "review-authority",
            "attestation_ref": "evidence://review-attestation",
        },
    )
    assert plan.bindings[-1].installation.digest == ARTIFACT_HASH


def test_compiled_provenance_and_manipulation_require_observed_evidence() -> None:
    provenance = declared_grader(
        "source-check",
        implementation="source_provenance",
        config={
            "claims_pointer": "/claims",
            "required_sources": {"source-one": "b" * 64},
            "required_claim_sources": {"claim-one": ("source-one",)},
        },
    )
    pack, scenario = compiler_pack(
        provenance,
        deterministic_metrics=({"metric_id": "sources", "weight": 1.0, "oracle": "source-check"},),
        evidence_sources=({"source_id": "source-one", "source_uri": "synthetic://declared", "content_hash": "b" * 64, "classification": "synthetic"},),
    )
    plan = compile_grader_plan(pack, scenario, TrustedGraderRegistry())
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output=json.dumps({"claims": [{"claim_id": "claim-one", "evidence": [{"source_id": "source-one", "content_hash": "b" * 64}]}]}),
        context=EvaluationContext(),
        plan=plan,
        registry=TrustedGraderRegistry(),
        trace_hash=HASH,
    )
    assert result.record.outcome.deterministic == {"sources": 1.0}

    manipulation = declared_grader(
        "factor-check",
        implementation="manipulation_fidelity",
        config={"expected_assignments": {"scaffold": True}},
    )
    pack, scenario = compiler_pack(
        manipulation,
        deterministic_metrics=({"metric_id": "fidelity", "weight": 1.0, "oracle": "factor-check"},),
    )
    plan = compile_grader_plan(pack, scenario, TrustedGraderRegistry())
    with pytest.raises(ValueError, match="HOLD: manipulation fidelity"):
        evaluate_attempt(
            attempt={"episode_id": "episode-one", "factor_assignments": {"scaffold": True}},
            output="{}", context=EvaluationContext(), plan=plan,
            registry=TrustedGraderRegistry(), trace_hash=HASH,
        )


def _source_provenance_plan(*, severe: bool = False):
    config = {
        "claims_pointer": "/claims",
        "required_sources": {"source-one": "b" * 64},
        "required_claim_sources": {"claim-one": ("source-one",)},
    }
    if severe:
        config["unsupported_evidence_severe_rule_id"] = "unsupported-evidence"
    provenance = declared_grader(
        "source-check", implementation="source_provenance", config=config
    )
    pack, scenario = compiler_pack(
        provenance,
        deterministic_metrics=({"metric_id": "sources", "weight": 1.0, "oracle": "source-check"},),
        evidence_sources=(
            {
                "source_id": "source-one",
                "source_uri": "synthetic://declared",
                "content_hash": "b" * 64,
                "classification": "synthetic",
            },
        ),
    )
    return pack, scenario, compile_grader_plan(pack, scenario, TrustedGraderRegistry())


@pytest.mark.parametrize(
    ("payload", "diagnostic", "severe"),
    (
        (
            {"claims": [{"claim_id": "claim-one", "evidence": [{"source_id": "source-two", "content_hash": "b" * 64}]}]},
            "unknown evidence source: source-two",
            True,
        ),
        (
            {"claims": [{"claim_id": "claim-one", "evidence": [{"source_id": "source-one", "content_hash": "c" * 64}]}]},
            "evidence hash mismatch: source-one",
            True,
        ),
        (
            {"claims": [{"claim_id": "claim-one", "evidence": []}]},
            "claim claim-one has no evidence citations",
            False,
        ),
        (
            {"claims": [
                {"claim_id": "claim-one", "evidence": [{"source_id": "source-one", "content_hash": "b" * 64}]},
                {"claim_id": "extra-claim", "evidence": []},
            ]},
            "claim extra-claim has no evidence citations",
            False,
        ),
    ),
)
def test_source_provenance_rejects_ungrounded_or_unsupported_claim_evidence(
    payload: dict, diagnostic: str, severe: bool
) -> None:
    _pack, _scenario, plan = _source_provenance_plan(severe=True)
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output=json.dumps(payload),
        context=EvaluationContext(),
        plan=plan,
        registry=TrustedGraderRegistry(),
        trace_hash=HASH,
    )
    grader_result = result.results[0]
    assert grader_result.passed is False
    assert any(diagnostic in note for note in grader_result.notes)
    assert grader_result.severe_failures == (("unsupported-evidence",) if severe else ())


def test_source_provenance_rejects_malformed_json() -> None:
    _pack, _scenario, plan = _source_provenance_plan()
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output="{not-json",
        context=EvaluationContext(),
        plan=plan,
        registry=TrustedGraderRegistry(),
        trace_hash=HASH,
    )
    assert result.results[0].notes == ("output is not valid JSON",)


def test_source_provenance_compiler_rejects_scenario_pack_mismatch_and_unfrozen_sources() -> None:
    pack, scenario, _plan = _source_provenance_plan()
    mismatched = ScenarioSpec(
        scenario_id=scenario.scenario_id,
        title=scenario.title,
        task_family=scenario.task_family,
        prompt=scenario.prompt,
        evidence_sources=(
            {
                "source_id": "source-one",
                "source_uri": "synthetic://different",
                "content_hash": "c" * 64,
                "classification": "synthetic",
            },
        ),
        deterministic_metrics=scenario.deterministic_metrics,
    )
    with pytest.raises(ValueError, match="does not match the frozen study pack scenario"):
        compile_grader_plan(pack, mismatched, TrustedGraderRegistry())

    bad_grader = declared_grader(
        "source-check",
        implementation="source_provenance",
        config={"claims_pointer": "/claims", "required_sources": {"source-one": "c" * 64}},
    )
    bad_pack, bad_scenario = compiler_pack(
        bad_grader,
        deterministic_metrics=({"metric_id": "sources", "weight": 1.0, "oracle": "source-check"},),
        evidence_sources=(
            {
                "source_id": "source-one",
                "source_uri": "synthetic://declared",
                "content_hash": "b" * 64,
                "classification": "synthetic",
            },
        ),
    )
    with pytest.raises(ValueError, match="do not match frozen ScenarioSpec evidence_sources"):
        compile_grader_plan(bad_pack, bad_scenario, TrustedGraderRegistry())


def test_untrusted_grader_and_low_deterministic_weight_are_rejected() -> None:
    registry = TrustedGraderRegistry()
    with pytest.raises(TypeError):
        registry.install(
            Untrusted(), GraderInstallation(grader_id="evil", version="1", digest=HASH)
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        GraderPlan(
            bindings=(
                GraderBinding(
                    metric_id="judge",
                    weight=0.69,
                    kind="qualitative",
                    installation=GraderInstallation(
                        grader_id="judge", version="1", digest=HASH
                    ),
                ),
            )
        )


def test_state_oracle_wins_over_narrated_success_and_hard_gates() -> None:
    grader = StateOracleGrader("committed", True)
    registry = TrustedGraderRegistry()
    registry.install(grader, installation(grader))
    plan = GraderPlan(
        bindings=(
            GraderBinding(
                metric_id="state",
                weight=1.0,
                kind="deterministic",
                installation=installation(grader),
            ),
        )
    )
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output='{"success": true}',
        context=EvaluationContext(state_refs={"committed": False}),
        plan=plan,
        registry=registry,
        trace_hash=HASH,
    )
    assert result.record.outcome.mission_success == 0.0
    assert result.record.outcome.severe_failures == ("state-oracle-failed",)
    assert not result.hard_gate_passed
    assert result.record.outcome.cost_status == "unknown"


def test_judge_is_not_claim_eligible_without_human_calibration() -> None:
    grader = StateOracleGrader("state", True)
    registry = TrustedGraderRegistry()
    registry.install(grader, installation(grader))
    plan = GraderPlan(
        bindings=(
            GraderBinding(
                metric_id="state",
                weight=0.7,
                kind="deterministic",
                installation=installation(grader),
            ),
            GraderBinding(
                metric_id="judge",
                weight=0.3,
                kind="qualitative",
                installation=GraderInstallation(
                    grader_id="judge", version="1", digest="b" * 64
                ),
            ),
        )
    )
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output="{}",
        context=EvaluationContext(state_refs={"state": True}),
        plan=plan,
        registry=registry,
        trace_hash=HASH,
    )
    assert not result.qualitative_claims_eligible
    assert "no explicit observed result" in result.exclusions[0]


def test_blind_assignment_requires_adjudication_before_completion() -> None:
    assignments = assign_blindly(
        ["item-one"],
        ["ann-a", "ann-b", "ann-c"],
        payload_refs={"item-one": "artifact://blind"},
        seed="study",
    )
    assert assignments == assign_blindly(
        ["item-one"],
        ["ann-c", "ann-a", "ann-b"],
        payload_refs={"item-one": "artifact://blind"},
        seed="study",
    )
    annotations = [
        Annotation("item-one", assignment.annotator_pseudonym, score)
        for assignment, score in zip(assignments, (0.0, 1.0, 1.0))
    ]
    held = complete_annotations(assignments, annotations)
    assert held.receipt is None and held.unresolved_conflicts == ("item-one",)
    completed = complete_annotations(
        assignments,
        annotations,
        adjudications=(
            AdjudicationRecord(
                "item-one",
                "lead-adjudicator",
                1.0,
                "accept",
                "conflict resolved against blind evidence",
                "artifact://adjudication",
            ),
        ),
    )
    assert completed.receipt is None
    assert completed.protocol_complete is True
    assert len(completed.completion_digest) == 64


def test_blind_assignment_assigns_every_listed_annotator_and_keeps_threshold_strict() -> None:
    assignments = assign_blindly(
        ["item-one"],
        ["ann-a", "ann-b", "ann-c", "ann-d"],
        payload_refs={"item-one": "artifact://blind"},
        seed="study",
    )
    assert {assignment.annotator_pseudonym for assignment in assignments} == {"ann-a", "ann-b", "ann-c", "ann-d"}
    boundary = [
        Annotation("item-one", assignment.annotator_pseudonym, score)
        for assignment, score in zip(assignments, (0.0, 0.20, 0.10, 0.10))
    ]
    result = complete_annotations(assignments, boundary)
    assert result.protocol_complete is True
    assert result.summaries[0].annotator_count == 4
    assert result.summaries[0].conflict is False


def test_total_weights_and_qualitative_evidence_binding_are_required() -> None:
    grader = StateOracleGrader("state", True)
    registry = TrustedGraderRegistry()
    registry.install(grader, installation(grader))
    with pytest.raises(ValueError, match="exactly"):
        GraderPlan(
            bindings=(
                GraderBinding(
                    metric_id="state",
                    weight=0.7,
                    kind="deterministic",
                    installation=installation(grader),
                ),
            )
        )
    plan = GraderPlan(
        bindings=(
            GraderBinding(
                metric_id="state",
                weight=0.7,
                kind="deterministic",
                installation=installation(grader),
            ),
            GraderBinding(
                metric_id="judge",
                weight=0.3,
                kind="qualitative",
                installation=GraderInstallation(
                    grader_id="judge", version="2", digest="b" * 64
                ),
            ),
        ),
        human_calibration_receipt={
            "receipt_id": "calibration-one",
            "batch_hash": "c" * 64,
            "protocol_hash": "d" * 64,
            "review_completion_digest": "e" * 64,
            "annotator_count": 3,
            "resolved_conflicts": True,
            "identity_state": "verified",
            "authority_id": "review-authority",
            "attestation_ref": "evidence://review-attestation",
        },
    )
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output="{}",
        context=EvaluationContext(state_refs={"state": True}),
        plan=plan,
        registry=registry,
        trace_hash=HASH,
    )
    assert (
        not result.qualitative_claims_eligible
        and result.record.outcome.model_judged == {}
    )
    admitted = QualitativeResult(
        metric_id="judge",
        score=0.9,
        evaluator_id="judge",
        evaluator_version="2",
        evaluator_digest="b" * 64,
        input_evidence_ref="artifact://input",
        output_evidence_ref="artifact://output",
        calibration_receipt_id="calibration-one",
        calibration_batch_hash="c" * 64,
    )
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"}, output="{}",
        context=EvaluationContext(state_refs={"state": True}),
        plan=plan, registry=registry, trace_hash=HASH,
        qualitative_results=(admitted,),
    )
    assert result.qualitative_claims_eligible
    assert result.record.outcome.model_judged == {"judge": 0.9}
    mismatched = QualitativeResult(
        metric_id="judge",
        score=0.9,
        evaluator_id="judge",
        evaluator_version="wrong",
        evaluator_digest="b" * 64,
        input_evidence_ref="artifact://input",
        output_evidence_ref="artifact://output",
        calibration_receipt_id="calibration-one",
        calibration_batch_hash="c" * 64,
    )
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output="{}",
        context=EvaluationContext(state_refs={"state": True}),
        plan=plan,
        registry=registry,
        trace_hash=HASH,
        qualitative_results=(mismatched,),
    )
    assert (
        not result.qualitative_claims_eligible
        and result.record.outcome.model_judged == {}
    )


def test_declared_deterministic_severe_rule_hard_gates_an_attempt() -> None:
    grader = StateOracleGrader("state", True)
    registry = TrustedGraderRegistry()
    registry.install(grader, installation(grader))
    plan = GraderPlan(
        bindings=(
            GraderBinding(
                metric_id="state",
                weight=1.0,
                kind="deterministic",
                installation=installation(grader),
            ),
        )
    )
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output="{}",
        context=EvaluationContext(
            state_refs={"state": False},
            severe_failure_rules={
                "declared-state-failure": {"metric_id": "state", "when": "failed"}
            },
        ),
        plan=plan,
        registry=registry,
        trace_hash=HASH,
    )
    assert "declared-state-failure" in result.record.outcome.severe_failures
    assert not result.hard_gate_passed


def test_calibration_receipt_does_not_qualify_a_plan_without_judge_metrics() -> None:
    grader = StateOracleGrader("state", True)
    registry = TrustedGraderRegistry()
    registry.install(grader, installation(grader))
    plan = GraderPlan(
        bindings=(
            GraderBinding(
                metric_id="state",
                weight=1.0,
                kind="deterministic",
                installation=installation(grader),
            ),
        ),
        human_calibration_receipt={
            "receipt_id": "unrelated-calibration",
            "batch_hash": "b" * 64,
            "protocol_hash": "c" * 64,
            "review_completion_digest": "d" * 64,
            "annotator_count": 3,
            "resolved_conflicts": True,
            "identity_state": "verified",
            "authority_id": "review-authority",
            "attestation_ref": "evidence://review-attestation",
        },
    )
    result = evaluate_attempt(
        attempt={"episode_id": "episode-one"},
        output="{}",
        context=EvaluationContext(state_refs={"state": True}),
        plan=plan,
        registry=registry,
        trace_hash=HASH,
    )
    assert not plan.qualitative_claims_eligible
    assert not result.qualitative_claims_eligible


def test_unattested_legacy_calibration_receipt_is_rejected() -> None:
    with pytest.raises(ValueError):
        GraderPlan.model_validate({
            "bindings": [{
                "metric_id": "judge", "weight": 1.0, "kind": "deterministic",
                "installation": {"grader_id": "state", "version": "1", "digest": HASH},
            }],
            "human_calibration_receipt": {
                "receipt_id": "self-asserted", "batch_hash": "b" * 64,
                "protocol_hash": "c" * 64, "annotator_count": 3,
                "resolved_conflicts": True,
            },
        })
