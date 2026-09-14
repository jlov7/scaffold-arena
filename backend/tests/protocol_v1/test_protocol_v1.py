from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from protocol_v1 import (
    AggregateBudgetSpec,
    AttemptEnvelope,
    ExecutionProvenance,
    ExperimentSpec,
    FactorSpec,
    GraderSpec,
    HarnessSpec,
    OutcomeVector,
    ScenarioSpec,
    StudyPack,
    TraceEvent,
    assess_study_pack_readiness,
    canonical_configuration_hash,
    canonical_json,
    canonical_manifest,
    expand_design,
    fractional_design_metadata,
    freeze_experiment,
    load_study_pack,
    manifest_hash,
    sha256,
    verify_manifest,
)
from protocol_v1.models import DecisionBrief, LegacyEvidenceReceipt


def factor(factor_id: str, kind: str = "binary", levels=(False, True), **kwargs):
    if kind == "binary" and "manipulation_checks" not in kwargs:
        kwargs["manipulation_checks"] = ({"factor_id": factor_id, "expected_value": True, "oracle": "check"},)
    if "treatment_mutations" not in kwargs:
        kwargs["treatment_mutations"] = tuple(
            {"target": f"factors.{factor_id}", "operation": "set", "level": level, "value": level}
            for level in levels[1:]
        )
    return FactorSpec(factor_id=factor_id, kind=kind, levels=levels, description="test factor", **kwargs)


def experiment(**kwargs) -> ExperimentSpec:
    values = {
        "experiment_id": "experiment-one",
        "study_pack_id": "pack-one",
        "scenario_ids": ("scenario-one",),
        "harness_ids": ("harness-one",),
        "deterministic_weight": 0.7,
    }
    values.update(kwargs)
    return ExperimentSpec(**values)


def scenario(scenario_id="scenario-one", **kwargs) -> ScenarioSpec:
    values = {"scenario_id": scenario_id, "title": "Scenario", "task_family": "extraction", "prompt": "Synthetic test prompt."}
    values.update(kwargs)
    return ScenarioSpec(**values)


def pack(**kwargs) -> StudyPack:
    values = {
        "study_pack_id": "pack-one",
        "version": "1.0.0",
        "title": "Pack",
        "license_spdx": "MIT",
        "authors": ({"name": "Protocol Test"},),
        "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ("Synthetic test only.",),
        "limitations": ("No live evidence.",),
        "preregistration": {"reference_uri": "synthetic://preregistration", "content_hash": "a" * 64},
        "scenarios": (scenario(),),
        "harnesses": (HarnessSpec(harness_id="harness-one", version="1", adapter="recorded"),),
        "experiments": (experiment(),),
    }
    values.update(kwargs)
    return StudyPack(**values)


def write_pack(root: Path, payload: dict) -> None:
    root.mkdir()
    (root / "study-pack.json").write_text(json.dumps(payload), encoding="utf-8")


def execution_provenance(now: datetime) -> dict:
    return {
        "code_revision": "abc123",
        "code_hash": "a" * 64,
        "runtime_image": "fixture-runtime@sha256:abc",
        "runtime_image_hash": "b" * 64,
        "environment_hash": "c" * 64,
        "prompt_hash": "d" * 64,
        "context_hash": "e" * 64,
        "tool_hash": "f" * 64,
        "source_refs": ({"source_uri": "synthetic://fixture", "content_hash": "1" * 64},),
        "captured_at": now,
    }


def attempt_budget() -> dict:
    return {
        "max_attempts": 1,
        "max_cost_usd": 1.0,
        "max_latency_seconds": 10.0,
        "max_tokens": 1024,
        "max_tool_calls": 2,
        "max_context_tokens": 4096,
    }


def attempt(now: datetime, **kwargs) -> AttemptEnvelope:
    values = {
        "attempt_id": "attempt-one",
        "episode_id": "episode-one",
        "ordinal": 1,
        "provider_model": "fixture",
        "provider": "recorded",
        "harness_id": "harness-one",
        "factor_assignments": {},
        "budget": attempt_budget(),
        "provenance": execution_provenance(now),
        "request_hash": "2" * 64,
        "status": "queued",
        "queued_at": now,
    }
    values.update(kwargs)
    return AttemptEnvelope(**values)


def test_happy_path_pack_and_protocol_version():
    assert pack().protocol_version == "1.0"


def grader_spec(
    grader_id: str = "state-check",
    *,
    implementation: str = "state_oracle",
    kind: str = "deterministic",
    config: dict | None = None,
    metric_id: str | None = None,
    weight: float | None = None,
    digest: str | None = None,
) -> GraderSpec:
    config = {"state_key": "committed", "expected": True} if config is None else config
    try:
        canonical_digest = GraderSpec.digest_for(
            grader_id=grader_id,
            version="1",
            implementation=implementation,
            kind=kind,
            config=config,
        )
    except (TypeError, ValueError):
        canonical_digest = "a" * 64
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


def test_grader_specs_are_content_addressed_and_strictly_declarative():
    first = grader_spec(config={"state_key": "committed", "expected": True})
    second = grader_spec(config={"state_key": "committed", "expected": False})
    assert first.digest != second.digest
    with pytest.raises(ValidationError, match="unknown keys"):
        grader_spec(config={"state_key": "committed", "expected": True, "extra": True})
    with pytest.raises(ValidationError, match="executable-looking"):
        grader_spec(config={"state_key": "committed", "expected": True, "module_path": "payload"})
    with pytest.raises(ValidationError, match="NaN or Infinity"):
        grader_spec(config={"state_key": "committed", "expected": float("nan")})
    with pytest.raises(ValidationError, match="JSON values"):
        grader_spec(config={"state_key": "committed", "expected": {"set": {"bad"}}})


def test_installed_plugin_grader_uses_a_supplied_artifact_digest() -> None:
    metadata_digest = GraderSpec.digest_for(
        grader_id="installed-judge",
        version="1",
        implementation="installed_plugin",
        kind="qualitative",
        config={},
    )
    artifact_digest = "b" * 64
    plugin = grader_spec(
        "installed-judge",
        implementation="installed_plugin",
        kind="qualitative",
        config={},
        metric_id="judge",
        weight=0.3,
        digest=artifact_digest,
    )
    assert plugin.digest == artifact_digest
    assert plugin.digest != metadata_digest
    with pytest.raises(ValidationError, match="empty references"):
        grader_spec(
            "installed-judge",
            implementation="installed_plugin",
            kind="qualitative",
            config={"package": "untrusted"},
            metric_id="judge",
            weight=0.3,
            digest=artifact_digest,
        )


def test_builtin_grader_digest_remains_canonical() -> None:
    with pytest.raises(ValidationError, match="built-in grader digest"):
        grader_spec(digest="b" * 64)


def test_claim_readiness_holds_for_unknown_or_miskind_grader_references():
    declared = grader_spec(
        grader_id="human-judge",
        implementation="installed_plugin",
        kind="qualitative",
        config={},
        metric_id="human-score",
        weight=0.3,
    )
    scenario_with_unknown = scenario(
        deterministic_metrics=({"metric_id": "state", "weight": 0.7, "oracle": "missing"},),
    )
    report = assess_study_pack_readiness(pack(scenarios=(scenario_with_unknown,), graders=(declared,)))
    assert report.verdict == "HOLD"
    assert any(issue.code == "unknown-grader" for issue in report.issues)
    scenario_with_judge = scenario(
        deterministic_metrics=({"metric_id": "state", "weight": 0.7, "oracle": "human-judge"},),
    )
    report = assess_study_pack_readiness(pack(scenarios=(scenario_with_judge,), graders=(declared,)))
    assert any(issue.code == "grader-kind" for issue in report.issues)


def test_contracts_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        scenario(unexpected=True)


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": [2, 1], "a": 3}) == canonical_json({"a": 3, "b": [2, 1]})


@pytest.mark.parametrize(
    ("kind", "levels"),
    [("binary", (False, True)), ("categorical", ("brief", "detailed")), ("ordinal", (1, 2, 3))],
)
def test_factor_kinds(kind, levels):
    assert factor("factor-one", kind, levels).levels == levels


def test_invalid_binary_and_ordinal_rejected():
    with pytest.raises(ValidationError):
        factor("factor-one", "binary", (0, 1))
    with pytest.raises(ValidationError):
        factor("factor-one", "ordinal", (2, 1))


def test_clean_stress_pair_requires_fault_and_reciprocity():
    with pytest.raises(ValidationError):
        scenario("stress-one", variant="stress")
    clean = scenario("clean-one", pair_id="pair-one", paired_scenario_id="stress-one")
    stress = scenario("stress-one", variant="stress", pair_id="pair-one", paired_scenario_id="clean-one", fault_metadata={"fault_id": "noise", "category": "context", "description": "noise"})
    assert pack(scenarios=(clean, stress), experiments=(experiment(scenario_ids=("clean-one", "stress-one")),))


def test_scenario_pair_must_be_reciprocal():
    clean = scenario("clean-one", pair_id="pair-one", paired_scenario_id="stress-one")
    stress = scenario("stress-one", variant="stress", pair_id="pair-one", fault_metadata={"fault_id": "noise", "category": "context", "description": "noise"})
    with pytest.raises(ValidationError, match="clean/stress peers"):
        pack(scenarios=(clean, stress), experiments=(experiment(scenario_ids=("clean-one", "stress-one")),))


def test_deterministic_weight_must_be_seventy_percent():
    with pytest.raises(ValidationError):
        experiment(deterministic_weight=0.69)


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_protocol_rejects_non_finite_numbers_across_numeric_contracts(non_finite):
    with pytest.raises(ValidationError, match="finite number"):
        experiment(deterministic_weight=non_finite)
    with pytest.raises(ValidationError, match="finite number"):
        experiment(sampling={"temperature": non_finite, "top_p": 1.0, "max_tokens": 1024})
    with pytest.raises(ValidationError, match="finite number"):
        experiment(sampling={"temperature": 0.0, "top_p": non_finite, "max_tokens": 1024})
    attempt_limit = attempt_budget()
    attempt_limit["max_cost_usd"] = non_finite
    with pytest.raises(ValidationError, match="finite number"):
        experiment(budgets=attempt_limit)
    attempt_limit = attempt_budget()
    attempt_limit["max_latency_seconds"] = non_finite
    with pytest.raises(ValidationError, match="finite number"):
        experiment(budgets=attempt_limit)
    with pytest.raises(ValidationError, match="finite number"):
        AggregateBudgetSpec(
            max_total_cost_usd=non_finite,
            max_total_tokens=1,
            max_total_tool_calls=0,
            max_wall_time_seconds=1.0,
            max_attempts=1,
        )
    with pytest.raises(ValidationError, match="finite number"):
        OutcomeVector(episode_id="episode-one", deterministic={"mission-success": 1.0}, cost_usd=non_finite)
    with pytest.raises(ValidationError, match="finite number"):
        OutcomeVector(episode_id="episode-one", deterministic={"mission-success": 1.0}, latency_seconds=non_finite)


def test_protocol_accepts_finite_numbers_and_numeric_schema_generation():
    spec = experiment(
        deterministic_weight=0.75,
        sampling={"temperature": 0.5, "top_p": 0.9, "max_tokens": 512},
        budgets=attempt_budget(),
    )
    outcome = OutcomeVector(
        episode_id="episode-one",
        deterministic={"mission-success": 0.8},
        cost_usd=0.0,
        latency_seconds=0.125,
    )
    assert spec.deterministic_weight == 0.75
    assert outcome.latency_seconds == 0.125
    weight_schema = ExperimentSpec.model_json_schema()["properties"]["deterministic_weight"]
    assert weight_schema["minimum"] == 0.7
    assert weight_schema["maximum"] == 1.0
    assert weight_schema["type"] == "number"


def test_factor_incompatibility_references_must_exist():
    with pytest.raises(ValidationError):
        experiment(factors=(factor("one", incompatible_with=("missing",)),))


def test_manipulation_checks_validate_factor_and_level():
    with pytest.raises(ValidationError):
        experiment(factors=(factor("one"),), manipulation_checks=({"factor_id": "one", "expected_value": "bad", "oracle": "check"},))


def test_full_design_expands_all_arms():
    arms = expand_design(experiment(factors=(factor("one"), factor("two"))))
    assert len(arms) == 4


def test_fractional_design_is_stable_and_reduced():
    spec = experiment(design="fractional", factors=(factor("one"), factor("two"), factor("three")))
    assert expand_design(spec) == expand_design(spec)
    assert len(expand_design(spec)) == 4


def test_four_factor_half_fraction_is_unique_and_balanced():
    spec = experiment(design="fractional", factors=tuple(factor(name) for name in ("one", "two", "three", "four")))
    arms = expand_design(spec)
    assert len(arms) == len({tuple(arm.items()) for arm in arms}) == 8
    assert all(sum(arm[name] for arm in arms) == 4 for name in ("one", "two", "three", "four"))
    assert fractional_design_metadata(spec) == {
        "family": "regular_two_level_half_fraction", "generator": "I=ABCD", "resolution": 4, "runs": 8,
    }


def test_fractional_rejects_non_binary_factors():
    spec = experiment(
        design="fractional",
        factors=(factor("one"), factor("levels", "categorical", ("a", "b"), manipulation_checks=({"factor_id": "levels", "expected_value": "a", "oracle": "check"},))),
    )
    with pytest.raises(ValueError, match="binary"):
        expand_design(spec)


def test_custom_design_requires_complete_valid_assignments():
    spec = experiment(
        design="custom",
        factors=(factor("one"),),
        custom_design=({"treatment_id": "treatment-one", "assignments": {"one": True}},),
    )
    assert expand_design(spec) == ({"one": True},)
    with pytest.raises(ValueError):
        experiment(
            design="custom",
            factors=(factor("one"),),
            custom_design=({"treatment_id": "treatment-one", "assignments": {}},),
        )


def test_incompatible_factors_exclude_combined_active_arm():
    arms = expand_design(experiment(factors=(factor("one", incompatible_with=("two",)), factor("two"))))
    assert {"one": True, "two": True} not in arms


def test_manifest_is_stable_and_detects_tampering(tmp_path):
    root = tmp_path / "pack"
    write_pack(root, pack().model_dump(mode="json"))
    digest = manifest_hash(canonical_manifest(root))
    assert verify_manifest(root, digest)
    (root / "notes.txt").write_text("tampered", encoding="utf-8")
    assert not verify_manifest(root, digest)


def test_malicious_symlink_and_source_are_rejected(tmp_path):
    root = tmp_path / "pack"
    write_pack(root, pack().model_dump(mode="json"))
    (root / "escape.json").symlink_to(tmp_path / "outside.json")
    with pytest.raises(ValueError, match="symlink"):
        load_study_pack(root)

    source_root = tmp_path / "source-pack"
    write_pack(source_root, pack().model_dump(mode="json"))
    (source_root / "payload.py").write_text("raise RuntimeError('executed')", encoding="utf-8")
    with pytest.raises(ValueError, match="executable"):
        load_study_pack(source_root)


def test_executable_treatment_target_is_rejected():
    with pytest.raises(ValidationError, match="non-executable"):
        factor("one", treatment_mutations=({"target": "exec:payload", "operation": "set", "level": True},))
    with pytest.raises(ValidationError, match="not executable"):
        factor("one", declarative_config={"shell_command": "nope"})


def test_every_varied_factor_needs_a_manipulation_check():
    raw = factor("one").model_dump()
    raw["manipulation_checks"] = ()
    with pytest.raises(ValidationError, match="manipulation check"):
        experiment(factors=(FactorSpec(**raw),))


def test_pack_rejects_unknown_scenario_and_harness_references():
    with pytest.raises(ValidationError, match="unknown scenario"):
        pack(experiments=(experiment(scenario_ids=("missing",)),))
    with pytest.raises(ValidationError, match="unknown harness"):
        pack(experiments=(experiment(harness_ids=("missing",)),))


def test_incompatible_level_combination_rejects_unknown_factor():
    broken = factor(
        "one",
        incompatible_level_combinations=({"assignments": {"one": True, "missing": True}, "reason": "invalid"},),
    )
    with pytest.raises(ValidationError, match="unknown factor"):
        experiment(factors=(broken,))


def test_nested_unknown_capability_is_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HarnessSpec(harness_id="harness-one", version="1", adapter="recorded", capabilities={"tools": True, "teleport": True})


def test_effective_harness_configuration_is_canonically_bound():
    configuration = {"fixture_mode": "strict", "retries": 0}
    with pytest.raises(ValidationError, match="requires effective_configuration_hash"):
        HarnessSpec(harness_id="harness-one", version="1", adapter="recorded", configuration=configuration)
    with pytest.raises(ValidationError, match="does not bind"):
        HarnessSpec(
            harness_id="harness-one", version="1", adapter="recorded", configuration=configuration,
            effective_configuration_hash="a" * 64,
        )
    harness = HarnessSpec(
        harness_id="harness-one", version="1", adapter="recorded", configuration=configuration,
        effective_configuration_hash=canonical_configuration_hash(configuration),
        schema_hashes={"config_schema_hash": "b" * 64},
    )
    assert harness.effective_configuration_hash != harness.schema_hashes.config_schema_hash


def test_claim_eligible_harness_is_evidence_bound_and_isolated():
    config_hash = canonical_configuration_hash({})
    with pytest.raises(ValidationError, match="adapter identity"):
        HarnessSpec(harness_id="live-harness", version="1", adapter="http", claim_eligibility="live_provider")
    common = {
        "harness_id": "live-harness",
        "version": "1",
        "adapter": "http",
        "adapter_identity": "internal.http-adapter",
        "adapter_digest": "a" * 64,
        "effective_configuration_hash": config_hash,
        "schema_hashes": {
            "input_hash": "a" * 64,
            "output_hash": "b" * 64,
            "trace_hash": "c" * 64,
            "config_schema_hash": "d" * 64,
        },
        "claim_eligibility": "live_provider",
        "capabilities": {"tools": True},
    }
    with pytest.raises(ValidationError, match="sandbox isolation"):
        HarnessSpec(**common)
    harness = HarnessSpec(**common, execution_mode="container", isolation="container")
    assert harness.claim_eligibility == "live_provider"


def test_execution_contracts_include_status_timing_and_integrity_boundary():
    now = datetime.now(UTC)
    envelope = attempt(now)
    assert envelope.status == "queued"
    assert envelope.runtime_hash == "b" * 64
    trace = TraceEvent(
        trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0, actor="system",
        event_type="state", timestamp=now, monotonic_time=0.0, payload={}, payload_hash="a" * 64,
    )
    assert trace.redaction == "none"
    with pytest.raises(ValidationError):
        LegacyEvidenceReceipt(
            receipt_id="receipt-one", artifact_type="trace", artifact_hash="a" * 64, source_uri="file://trace", created_at=now,
            claim_ceiling="Integrity only", manifest_hash="a" * 64, environment_hash="a" * 64, evaluator_hashes=("a" * 64,), limitations=("No truth claim.",), integrity_not_truth=False,
        )


def test_legacy_evidence_contract_is_not_a_protocol_public_export():
    import protocol_v1

    assert not hasattr(protocol_v1, "EvidenceReceipt")
    assert not hasattr(protocol_v1, "ReproductionReceipt")
    assert not hasattr(protocol_v1, "HumanAnnotationBatch")


def test_protocol_decision_brief_is_explicitly_offline_only():
    assert "offline-only" in DecisionBrief.__doc__.casefold()
    assert "/api/v1/decision-briefs" in DecisionBrief.__doc__


def test_attempt_lifecycle_timestamps_are_truthful():
    queued_at = datetime.now(UTC)
    started_at = queued_at + timedelta(seconds=1)
    completed_at = started_at + timedelta(seconds=1)
    assert attempt(queued_at).started_at is None
    assert attempt(queued_at, status="started", started_at=started_at).completed_at is None
    assert attempt(
        queued_at,
        status="completed",
        started_at=started_at,
        completed_at=completed_at,
        response_hash="3" * 64,
    ).status == "completed"
    with pytest.raises(ValidationError, match="queued attempts"):
        attempt(queued_at, started_at=started_at)
    with pytest.raises(ValidationError, match="terminal attempts"):
        attempt(queued_at, status="failed", started_at=started_at)
    with pytest.raises(ValidationError, match="cannot precede"):
        attempt(queued_at, status="completed", started_at=started_at, completed_at=queued_at)


def test_attempt_separates_pinned_endpoint_from_runtime_observations():
    queued_at = datetime.now(UTC)
    started_at = queued_at + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="must appear together"):
        attempt(queued_at, endpoint_id="model-one")
    with pytest.raises(ValidationError, match="must appear together"):
        attempt(queued_at, pinned_endpoint_digest="a" * 64)
    queued = attempt(queued_at, endpoint_id="model-one", pinned_endpoint_digest="a" * 64)
    assert queued.pinned_endpoint_digest == "a" * 64
    with pytest.raises(ValidationError, match="cannot contain endpoint observations"):
        attempt(
            queued_at,
            endpoint_id="model-one",
            pinned_endpoint_digest="a" * 64,
            observed_endpoint_digest="b" * 64,
        )
    started = attempt(
        queued_at,
        status="started",
        started_at=started_at,
        endpoint_id="model-one",
        pinned_endpoint_digest="a" * 64,
        observed_endpoint_digest="b" * 64,
        observed_provider_version="2026-08-14",
    )
    assert started.observed_endpoint_digest != started.pinned_endpoint_digest


def test_execution_provenance_is_strict_and_immutable():
    provenance = ExecutionProvenance(**execution_provenance(datetime.now(UTC)))
    with pytest.raises(ValidationError):
        ExecutionProvenance(**execution_provenance(datetime.now(UTC)), anonymous_hash="a" * 64)
    with pytest.raises(ValidationError, match="frozen"):
        provenance.code_revision = "changed"


def test_execution_provenance_requires_distinct_sources_and_aware_capture():
    now = datetime.now(UTC)
    payload = execution_provenance(now)
    payload["source_refs"] = ()
    with pytest.raises(ValidationError):
        ExecutionProvenance(**payload)
    payload = execution_provenance(now)
    payload["source_refs"] = payload["source_refs"] * 2
    with pytest.raises(ValidationError, match="must be unique"):
        ExecutionProvenance(**payload)
    payload = execution_provenance(now.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="timezone-aware"):
        ExecutionProvenance(**payload)
    for field_name in ("code_revision", "runtime_image"):
        payload = execution_provenance(now)
        payload[field_name] = "   "
        with pytest.raises(ValidationError, match="cannot be blank"):
            ExecutionProvenance(**payload)


def test_attempt_schema_fields_are_unique_and_match_model_fields():
    model_fields = tuple(AttemptEnvelope.model_fields)
    schema_properties = tuple(AttemptEnvelope.model_json_schema()["properties"])
    assert len(model_fields) == len(set(model_fields))
    assert len(schema_properties) == len(set(schema_properties))
    assert set(model_fields) == set(schema_properties)
    assert model_fields.count("provider_model") == schema_properties.count("provider_model") == 1


def test_budget_completeness_and_sampling_bound():
    aggregate = AggregateBudgetSpec(
        max_total_cost_usd=5.0,
        max_total_tokens=4096,
        max_total_tool_calls=10,
        max_wall_time_seconds=60.0,
        max_attempts=4,
    )
    assert aggregate.max_total_cost_usd == 5.0
    with pytest.raises(ValidationError, match="attempt token budget"):
        experiment(budgets=attempt_budget(), sampling={"max_tokens": 2048})
    with pytest.raises(ValidationError):
        AggregateBudgetSpec(
            max_total_cost_usd=-1.0,
            max_total_tokens=1,
            max_total_tool_calls=0,
            max_wall_time_seconds=1.0,
            max_attempts=1,
        )


def test_factor_capability_requirement_is_checked_against_all_harnesses():
    required = factor("one", capability_requirements=({"capability": "tools"},))
    with pytest.raises(ValidationError, match="lacks a required"):
        pack(experiments=(experiment(factors=(required,)),))


def test_frozen_experiment_is_hash_bound_and_cannot_be_refrozen():
    with pytest.raises(ValueError, match="owner_approval"):
        freeze_experiment(experiment(), "a" * 64)
    frozen = freeze_experiment(experiment(owner_approval="approved"), "a" * 64)
    assert frozen.frozen and frozen.freeze_hash and frozen.study_pack_hash == "a" * 64
    with pytest.raises(TypeError, match="immutable"):
        frozen.deterministic_weight = 0.8
    with pytest.raises(ValueError, match="immutable"):
        freeze_experiment(frozen, "a" * 64)


def test_experiment_predecessor_uses_explicit_experiment_id_and_keeps_legacy_version_unmapped():
    spec = experiment(predecessor_experiment_id="experiment-zero", predecessor_version="1.2.3")
    dumped = spec.model_dump(mode="json")
    assert dumped["predecessor_experiment_id"] == "experiment-zero"
    assert dumped["predecessor_version"] == "1.2.3"
    legacy_only = experiment(predecessor_version="1.2.3")
    assert legacy_only.model_dump(mode="json")["predecessor_experiment_id"] is None
    with pytest.raises(ValidationError, match="own predecessor"):
        experiment(predecessor_experiment_id="experiment-one")


def test_namespaced_extensions_round_trip_are_immutable_and_hash_bound():
    genome = {
        "org.genome.compatibility": {
            "assembly": "GRCh38",
            "coordinate_system": "one_based_inclusive",
            "accepted_contigs": ["chr1", "chrX"],
        }
    }
    extended_pack = pack(
        extensions={"org.genome.study": {"reference_release": "2026.1"}},
        scenarios=(scenario(extensions=genome),),
        harnesses=(HarnessSpec(harness_id="harness-one", version="1", adapter="recorded", extensions={"org.genome.harness": {"input_format": "vcf"}}),),
        experiments=(experiment(extensions={"org.genome.analysis": {"cohort": "synthetic"}}),),
    )
    extended_factor = factor("one", extensions={"org.genome.factor": {"variant_class": "snv"}})
    assert extended_factor.extensions["org.genome.factor"]["variant_class"] == "snv"
    reloaded = StudyPack.model_validate_json(extended_pack.model_dump_json())
    assert reloaded.extensions == extended_pack.extensions
    assert reloaded.scenarios[0].extensions == extended_pack.scenarios[0].extensions
    with pytest.raises(TypeError, match="immutable"):
        extended_pack.extensions["org.genome.new"] = {}
    with pytest.raises(TypeError, match="immutable"):
        extended_pack.scenarios[0].extensions["org.genome.compatibility"]["assembly"] = "GRCh37"
    assert sha256(extended_pack.model_dump(mode="json")) != sha256(pack().model_dump(mode="json"))
    frozen_base = freeze_experiment(experiment(owner_approval="approved"), "a" * 64)
    frozen_extended = freeze_experiment(experiment(owner_approval="approved", extensions={"org.genome.analysis": {"cohort": "synthetic"}}), "a" * 64)
    assert frozen_base.freeze_hash != frozen_extended.freeze_hash


def test_freeze_round_trips_list_valued_extensions_through_json_without_weakening_input_validation():
    approved = experiment(
        owner_approval="approved",
        extensions={
            "org.scaffold-arena.analysis-v1": {
                "registered_factors": [
                    {"factor_id": "planning", "levels": ["off", "on"]},
                ],
                "primary_main_effects": [],
            },
        },
    )
    frozen = freeze_experiment(approved, "a" * 64)
    assert frozen.extensions["org.scaffold-arena.analysis-v1"]["registered_factors"][0]["factor_id"] == "planning"
    assert frozen.freeze_hash


def deeply_nested_extension(depth: int) -> dict[str, object] | bool:
    value: dict[str, object] | bool = True
    for _ in range(depth):
        value = {"nested": value}
    return value


@pytest.mark.parametrize(
    ("extensions", "message"),
    [
        ({"genome": {}}, "reverse-DNS"),
        ({"Org.genome.compatibility": {}}, "reverse-DNS"),
        ({"org.genome.compatibility": deeply_nested_extension(9)}, "nesting"),
        ({"org.genome.compatibility": "x" * (16 * 1024 + 1)}, "UTF-8 bytes"),
        ({"org.genome.compatibility": list(range(129))}, "collections"),
        ({"org.genome.compatibility": float("nan")}, "NaN or Infinity"),
        ({"org.genome.compatibility": float("inf")}, "NaN or Infinity"),
        ({"org.genome.compatibility": Path("/tmp/not-json")}, "JSON values only"),
    ],
)
def test_extensions_reject_invalid_namespaces_and_non_json_or_unbounded_values(extensions, message):
    with pytest.raises(ValidationError, match=message):
        scenario(extensions=extensions)


def test_freeze_hash_is_stable_and_claim_endpoints_are_pinned():
    approved = experiment(
        owner_approval="approved",
        claim_bearing=True,
        primary_outcomes=("mission-success",),
        model_endpoints=({"endpoint_id": "model-one", "provider": "provider", "model": "model"},),
    )
    with pytest.raises(ValidationError, match="endpoint digests"):
        freeze_experiment(approved, "a" * 64)
    pinned = experiment(
        owner_approval="approved",
        claim_bearing=True,
        primary_outcomes=("mission-success",),
        model_endpoints=({"endpoint_id": "model-one", "provider": "provider", "model": "model", "endpoint_digest": "b" * 64},),
    )
    first = freeze_experiment(pinned, "a" * 64)
    second = freeze_experiment(pinned, "a" * 64)
    assert first.freeze_hash == second.freeze_hash
    with pytest.raises(ValidationError, match="frozen"):
        first.model_endpoints[0].model = "drifted"


def test_experiment_duplicate_ids_and_custom_rows_are_rejected():
    with pytest.raises(ValidationError, match="scenario ids"):
        experiment(scenario_ids=("scenario-one", "scenario-one"))
    with pytest.raises(ValidationError, match="harness ids"):
        experiment(harness_ids=("harness-one", "harness-one"))
    with pytest.raises(ValidationError, match="model endpoint ids"):
        experiment(model_endpoints=(
            {"endpoint_id": "model-one", "provider": "p", "model": "m"},
            {"endpoint_id": "model-one", "provider": "p", "model": "m2"},
        ))
    with pytest.raises(ValidationError, match="randomization block ids"):
        experiment(randomization_blocks=(
            {"block_id": "block-one", "unit": "scenario", "values": ("scenario-one",)},
            {"block_id": "block-one", "unit": "scenario", "values": ("scenario-one",)},
        ))
    with pytest.raises(ValidationError, match="stopping rule ids"):
        experiment(stopping_rules=(
            {"rule_id": "stop-one", "condition": "failure", "action": "stop"},
            {"rule_id": "stop-one", "condition": "cost", "action": "hold"},
        ))
    with pytest.raises(ValidationError, match="assignments must be unique"):
        experiment(
            design="custom",
            factors=(factor("one"),),
            custom_design=(
                {"treatment_id": "treatment-one", "assignments": {"one": True}},
                {"treatment_id": "treatment-two", "assignments": {"one": True}},
            ),
        )


def test_duplicate_experiment_ids_are_rejected():
    with pytest.raises(ValidationError, match="experiment ids must be unique"):
        pack(experiments=(experiment(), experiment()))


def test_nonbaseline_levels_need_causal_mutation_or_explicit_noop():
    with pytest.raises(ValidationError, match="every non-baseline"):
        FactorSpec(factor_id="one", kind="binary", levels=(False, True), description="test factor")
    sham = FactorSpec(
        factor_id="one", kind="binary", levels=(False, True), description="test factor",
        sham_treatment={"label": "sham", "description": "No material change.", "levels": (True,)},
    )
    assert sham.sham_treatment is not None


def test_fault_schedule_references_declared_faults():
    with pytest.raises(ValidationError, match="undeclared fault"):
        scenario(
            "stress-one",
            variant="stress",
            fault_definitions=({"fault_id": "declared", "category": "context", "description": "declared"},),
            fault_schedule=({"fault_id": "missing", "trigger": "start", "description": "missing"},),
        )


def test_fault_schedule_coordinates_are_unique_but_distinct_points_are_allowed():
    fault = {"fault_id": "noise", "category": "context", "description": "noise"}
    first = {"fault_id": "noise", "trigger": "request", "ordinal": 1, "description": "first"}
    with pytest.raises(ValidationError, match="coordinates must be unique"):
        scenario("stress-one", variant="stress", fault_metadata=fault, fault_schedule=(first, first))
    second = {"fault_id": "noise", "trigger": "request", "ordinal": 2, "description": "second"}
    assert scenario("stress-one", variant="stress", fault_metadata=fault, fault_schedule=(first, second))


def test_deterministic_metrics_are_unique_and_never_overallocated():
    metric = {"metric_id": "exactness", "weight": 0.6, "oracle": "exact"}
    with pytest.raises(ValidationError, match="metric ids must be unique"):
        scenario(deterministic_metrics=(metric, metric))
    with pytest.raises(ValidationError, match="cannot exceed 1.0"):
        scenario(
            deterministic_metrics=(
                metric,
                {"metric_id": "completeness", "weight": 0.5, "oracle": "complete"},
            )
        )


def test_readiness_holds_for_missing_controls_and_reference_evidence():
    report = assess_study_pack_readiness(pack())
    assert report.verdict == "HOLD"
    assert report.task_family_deterministic_weights["extraction"] == 0.0
    assert {issue.code for issue in report.issues}.issuperset(
        {"deterministic-weight", "missing-positive", "missing-negative", "missing-anti-cheat", "scenario-reference-gap"}
    )


def test_protocol_v01_is_not_silently_coerced():
    payload = scenario().model_dump(mode="json")
    payload["protocol_version"] = "0.1"
    with pytest.raises(ValidationError):
        ScenarioSpec.model_validate(payload)


def test_compatibility_range_is_ordered_and_contains_protocol_v1():
    with pytest.raises(ValidationError, match="cannot exceed"):
        pack(compatibility={"protocol_min": "1.1", "protocol_max": "1.0"})
    with pytest.raises(ValidationError, match="must include protocol 1.0"):
        pack(compatibility={"protocol_min": "0.8", "protocol_max": "0.9"})
    with pytest.raises(ValidationError, match="dot-separated numeric"):
        pack(compatibility={"protocol_min": "1.0", "protocol_max": "1.x"})


def test_all_v1_json_schemas_are_valid_and_legacy_is_separate():
    root = Path(__file__).parents[3]
    schemas = tuple((root / "specs" / "v1").glob("*.schema.json"))
    assert schemas
    for schema_path in schemas:
        Draft202012Validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))
    legacy = json.loads((root / "specs" / "scenario.schema.json").read_text(encoding="utf-8"))
    assert legacy["properties"]["schema_version"]["pattern"] == "^0\\.1$"
