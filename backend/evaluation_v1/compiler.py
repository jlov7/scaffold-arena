"""Compile declarative StudyPack grader declarations without loading pack code."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from protocol_v1 import GraderSpec, ScenarioSpec, StudyPack

from .graders import (
    DeterministicGrader,
    ExactFieldGrader,
    ContextHandoffDeliveryGrader,
    ForbiddenTokenGrader,
    ManipulationFidelityGrader,
    SchemaGrader,
    SourceProvenanceGrader,
    StateOracleGrader,
    TrustedGraderRegistry,
)
from .models import (
    GraderBinding,
    GraderInstallation,
    GraderPlan,
    HumanCalibrationReceipt,
)


def _installation(spec: GraderSpec) -> GraderInstallation:
    return GraderInstallation(
        grader_id=spec.grader_id,
        version=spec.version,
        digest=spec.digest,
    )


def _builtin_grader(
    spec: GraderSpec, metric_id: str, scenario: ScenarioSpec
) -> DeterministicGrader:
    config = spec.config
    if spec.implementation == "schema":
        grader: DeterministicGrader = SchemaGrader(config["schema"], metric_id)
    elif spec.implementation == "exact_field":
        grader = ExactFieldGrader(config["expected"], metric_id)
    elif spec.implementation == "source_provenance":
        frozen_sources = {
            source.source_id: source.content_hash for source in scenario.evidence_sources
        }
        required_sources = config["required_sources"]
        mismatches = [
            source_id
            for source_id, content_hash in required_sources.items()
            if frozen_sources.get(source_id) != content_hash
        ]
        if mismatches:
            raise ValueError(
                "source_provenance grader required_sources do not match frozen ScenarioSpec evidence_sources: "
                f"{sorted(mismatches)}"
            )
        grader = SourceProvenanceGrader(
            config["claims_pointer"],
            frozen_sources,
            required_sources,
            config.get("required_claim_sources", {}),
            metric_id,
            config.get("unsupported_evidence_severe_rule_id"),
        )
    elif spec.implementation == "forbidden_token":
        grader = ForbiddenTokenGrader(
            config["forbidden_tokens"], metric_id, config.get("severe_rule_id")
        )
    elif spec.implementation == "state_oracle":
        grader = StateOracleGrader(
            config["state_key"],
            config["expected"],
            metric_id,
            config.get("failure_rule_id", "state-oracle-failed"),
        )
    elif spec.implementation == "manipulation_fidelity":
        grader = ManipulationFidelityGrader(
            config["expected_assignments"],
            metric_id,
            config.get("failure_rule_id", "manipulation-fidelity-failed"),
        )
    elif spec.implementation == "context_handoff_delivery":
        grader = ContextHandoffDeliveryGrader(
            task=config["task"], packet=config["packet"], renderer_digest=config["renderer_digest"],
            metric_id=metric_id, failure_rule_id=config.get("failure_rule_id", "context-policy-delivery-mismatch"),
        )
    else:  # GraderSpec validation makes this unreachable without dynamic dispatch.
        raise ValueError(f"unsupported built-in grader implementation: {spec.implementation}")
    grader.grader_id = spec.grader_id
    grader.version = spec.version
    grader.digest = spec.digest
    return grader


def _resolve_scenario(study_pack: StudyPack, scenario: ScenarioSpec | str) -> ScenarioSpec:
    scenario_id = scenario if isinstance(scenario, str) else scenario.scenario_id
    for candidate in study_pack.scenarios:
        if candidate.scenario_id == scenario_id:
            if isinstance(scenario, ScenarioSpec) and candidate != scenario:
                raise ValueError("provided ScenarioSpec does not match the frozen study pack scenario")
            return candidate
    raise LookupError(f"scenario is not declared by study pack: {scenario_id}")


def compile_grader_plan(
    study_pack: StudyPack,
    scenario: ScenarioSpec | str,
    installed_registry: TrustedGraderRegistry,
    human_calibration: HumanCalibrationReceipt | Mapping[str, Any] | None = None,
) -> GraderPlan:
    """Create a fail-closed plan from declarations, without mutating a registry.

    Built-ins are instantiated from validated JSON only and retained on the returned
    plan. Installed plugins are looked up by their exact local id, version, and
    independently supplied artifact or code digest; pack data never names an import
    path, module, or executable.
    """
    selected = _resolve_scenario(study_pack, scenario)
    specs = {spec.grader_id: spec for spec in study_pack.graders}
    bindings: list[GraderBinding] = []
    builtins: dict[tuple[str, str, str], DeterministicGrader] = {}

    for metric in selected.deterministic_metrics:
        # Context delivery is an independently reconstructed severe-failure
        # check.  It must run for every attempt, but does not alter the frozen
        # 70/15/15 outcome weights.  No other metric may silently opt out of
        # scoring.
        if metric.weight <= 0.0 and specs.get(metric.oracle, None) is None:
            raise ValueError(f"deterministic metric {metric.metric_id} must have positive weight")
        spec = specs.get(metric.oracle)
        if spec is None:
            raise LookupError(f"deterministic metric {metric.metric_id} references undeclared grader {metric.oracle}")
        if metric.weight <= 0.0 and spec.implementation != "context_handoff_delivery":
            raise ValueError(f"deterministic metric {metric.metric_id} must have positive weight")
        if spec.kind != "deterministic":
            raise ValueError(f"deterministic metric {metric.metric_id} references non-deterministic grader {metric.oracle}")
        installation = _installation(spec)
        if spec.implementation == "installed_plugin":
            if not isinstance(installed_registry.resolve(installation), DeterministicGrader):
                raise TypeError(
                    f"deterministic metric {metric.metric_id} does not resolve to a deterministic trusted grader"
                )
        else:
            builtins[(installation.grader_id, installation.version, installation.digest)] = _builtin_grader(
                spec, metric.metric_id, selected
            )
        bindings.append(
            GraderBinding(
                metric_id=metric.metric_id,
                weight=metric.weight,
                kind="deterministic",
                installation=installation,
            )
        )

    for spec in study_pack.graders:
        if spec.kind != "qualitative":
            continue
        installation = _installation(spec)
        # Qualitative evidence is observed externally, but the declared evaluator
        # identity must still already exist in the trusted local registry.
        installed_registry.resolve(installation)
        bindings.append(
            GraderBinding(
                metric_id=spec.metric_id,  # validated by GraderSpec
                weight=spec.weight,  # validated by GraderSpec
                kind="qualitative",
                installation=installation,
            )
        )

    plan = GraderPlan(
        bindings=tuple(bindings), human_calibration_receipt=human_calibration
    )
    return plan.with_builtin_graders(builtins)
