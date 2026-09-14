"""Strict, serialisable contracts for the Scaffold Arena 1.0 protocol."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import canonical_configuration_hash, sha256

ProtocolVersion = Literal["1.0"]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")]


class ProtocolModel(BaseModel):
    """The protocol deliberately rejects unknown and coerced data."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


_EXTENSION_NAMESPACE = re.compile(r"^(?=.{3,253}$)(?:[a-z][a-z0-9-]{0,62}\.)+[a-z][a-z0-9-]{0,62}$")
_MAX_EXTENSION_NAMESPACES = 32
_MAX_EXTENSION_DEPTH = 8
_MAX_EXTENSION_COLLECTION_SIZE = 128
_MAX_EXTENSION_TOTAL_VALUES = 1024
_MAX_EXTENSION_STRING_BYTES = 16 * 1024


class FrozenExtensionMap(dict[str, Any]):
    """JSON mapping whose contents are sealed after protocol validation."""

    def _immutable(self, *_: Any, **__: Any) -> None:
        raise TypeError("extensions are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def _freeze_extension_value(value: Any, *, depth: int, counter: list[int]) -> Any:
    if depth > _MAX_EXTENSION_DEPTH:
        raise ValueError(f"extensions cannot exceed {_MAX_EXTENSION_DEPTH} levels of nesting")
    counter[0] += 1
    if counter[0] > _MAX_EXTENSION_TOTAL_VALUES:
        raise ValueError(f"extensions cannot contain more than {_MAX_EXTENSION_TOTAL_VALUES} values")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("extensions must not contain NaN or Infinity")
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > _MAX_EXTENSION_STRING_BYTES:
            raise ValueError(f"extension strings cannot exceed {_MAX_EXTENSION_STRING_BYTES} UTF-8 bytes")
        return value
    if isinstance(value, list):
        if len(value) > _MAX_EXTENSION_COLLECTION_SIZE:
            raise ValueError(f"extension collections cannot contain more than {_MAX_EXTENSION_COLLECTION_SIZE} entries")
        return tuple(_freeze_extension_value(item, depth=depth + 1, counter=counter) for item in value)
    if isinstance(value, dict):
        if len(value) > _MAX_EXTENSION_COLLECTION_SIZE:
            raise ValueError(f"extension collections cannot contain more than {_MAX_EXTENSION_COLLECTION_SIZE} entries")
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("extension object keys must be strings")
            frozen[key] = _freeze_extension_value(item, depth=depth + 1, counter=counter)
        return FrozenExtensionMap(frozen)
    raise ValueError("extensions must contain JSON values only")


class ExtensibleProtocolModel(ProtocolModel):
    """Strict, namespaced JSON metadata with no protocol-level ontology."""

    extensions: Mapping[str, Any] = Field(
        default_factory=dict,
        validate_default=True,
        description=(
            "Immutable JSON metadata keyed by lowercase reverse-DNS namespaces "
            "(for example, org.genome.compatibility)."
        ),
    )

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if len(value) > _MAX_EXTENSION_NAMESPACES:
            raise ValueError(f"extensions cannot contain more than {_MAX_EXTENSION_NAMESPACES} namespaces")
        frozen: dict[str, Any] = {}
        counter = [0]
        for namespace, payload in value.items():
            if not isinstance(namespace, str) or _EXTENSION_NAMESPACE.fullmatch(namespace) is None:
                raise ValueError("extension keys must be lowercase reverse-DNS namespaces")
            frozen[namespace] = _freeze_extension_value(payload, depth=1, counter=counter)
        return FrozenExtensionMap(frozen)


class DeterministicMetric(ProtocolModel):
    metric_id: Identifier
    weight: Annotated[float, Field(ge=0.0, le=1.0)]
    oracle: str = Field(min_length=1)


BuiltinGraderImplementation = Literal[
    "schema",
    "exact_field",
    "source_provenance",
    "forbidden_token",
    "state_oracle",
    "manipulation_fidelity",
    "context_handoff_delivery",
]
GraderImplementation = BuiltinGraderImplementation | Literal["installed_plugin"]


class GraderSpec(ProtocolModel):
    """A data-only grader declaration owned by a StudyPack."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    grader_id: Identifier
    version: str = Field(min_length=1)
    implementation: GraderImplementation
    kind: Literal["deterministic", "qualitative"]
    config: Mapping[str, Any] = Field(default_factory=dict)
    digest: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description=(
            "Built-ins use the canonical declaration digest. Installed plugins use "
            "the separately supplied trusted artifact or code digest."
        ),
    )
    metric_id: Identifier | None = None
    weight: Annotated[float, Field(gt=0.0, le=1.0)] | None = None

    @staticmethod
    def digest_for(
        *,
        grader_id: str,
        version: str,
        implementation: str,
        kind: str,
        config: Mapping[str, Any],
    ) -> str:
        return sha256(
            {
                "grader_id": grader_id,
                "version": version,
                "implementation": implementation,
                "kind": kind,
                "config": config,
            }
        )

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("grader config must be a JSON mapping")
        return _freeze_grader_value(value)

    @model_validator(mode="after")
    def validate_declaration(self) -> GraderSpec:
        if self.implementation == "installed_plugin":
            if self.config:
                raise ValueError("installed plugin grader configs must be empty references")
        else:
            if self.kind != "deterministic":
                raise ValueError("built-in graders are deterministic")
            _validate_builtin_grader_config(self.implementation, self.config)
            expected_digest = self.digest_for(
                grader_id=self.grader_id,
                version=self.version,
                implementation=self.implementation,
                kind=self.kind,
                config=self.config,
            )
            if self.digest != expected_digest:
                raise ValueError(
                    "built-in grader digest does not bind canonical identity, implementation, and configuration"
                )
        if self.kind == "qualitative":
            if self.metric_id is None or self.weight is None:
                raise ValueError("qualitative graders require metric_id and weight")
        elif self.metric_id is not None or self.weight is not None:
            raise ValueError("deterministic grader weights and metric ids belong to ScenarioSpec")
        return self


_EXECUTABLE_CONFIG_TOKENS = ("code", "exec", "eval", "import", "script", "command", "shell", "module", "path")


def _freeze_grader_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("grader config must not contain NaN or Infinity")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("grader config keys must be strings")
            if any(token in key.casefold() for token in _EXECUTABLE_CONFIG_TOKENS):
                raise ValueError("grader config must not contain executable-looking keys")
            frozen[key] = _freeze_grader_value(item)
        return FrozenExtensionMap(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_grader_value(item) for item in value)
    raise ValueError("grader config must contain JSON values only")


def _require_exact_config_keys(
    implementation: str,
    config: Mapping[str, Any],
    required: set[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = set(config)
    if missing := required - keys:
        raise ValueError(f"{implementation} grader config is missing: {sorted(missing)}")
    if unknown := keys - required - optional:
        raise ValueError(f"{implementation} grader config has unknown keys: {sorted(unknown)}")


def _validate_builtin_grader_config(implementation: BuiltinGraderImplementation, config: Mapping[str, Any]) -> None:
    if implementation == "schema":
        _require_exact_config_keys(implementation, config, {"schema"})
        if not isinstance(config["schema"], Mapping):
            raise ValueError("schema grader config.schema must be a mapping")
    elif implementation == "exact_field":
        _require_exact_config_keys(implementation, config, {"expected"})
        if not isinstance(config["expected"], Mapping):
            raise ValueError("exact_field grader config.expected must be a mapping")
    elif implementation == "source_provenance":
        _require_exact_config_keys(
            implementation,
            config,
            {"claims_pointer", "required_sources"},
            frozenset({"required_claim_sources", "unsupported_evidence_severe_rule_id"}),
        )
        pointer = config["claims_pointer"]
        if not isinstance(pointer, str) or re.fullmatch(r"(?:/(?:[^~/]|~[01])*)+", pointer) is None:
            raise ValueError("source_provenance grader config.claims_pointer must be a non-empty RFC 6901 JSON Pointer")
        required_sources = config["required_sources"]
        if (
            not isinstance(required_sources, Mapping)
            or not required_sources
            or not all(
                isinstance(source_id, str)
                and re.fullmatch(r"[a-z][a-z0-9_-]{1,127}", source_id) is not None
                and isinstance(content_hash, str)
                and re.fullmatch(r"[a-f0-9]{64}", content_hash) is not None
                for source_id, content_hash in required_sources.items()
            )
        ):
            raise ValueError("source_provenance grader config.required_sources must be a non-empty source-id to SHA-256 mapping")
        required_claim_sources = config.get("required_claim_sources", {})
        if (
            not isinstance(required_claim_sources, Mapping)
            or not all(
                isinstance(claim_id, str)
                and re.fullmatch(r"[a-z][a-z0-9_-]{1,127}", claim_id) is not None
                and isinstance(source_ids, tuple)
                and source_ids
                and all(isinstance(source_id, str) and source_id in required_sources for source_id in source_ids)
                for claim_id, source_ids in required_claim_sources.items()
            )
        ):
            raise ValueError("source_provenance grader config.required_claim_sources must map claim ids to non-empty declared source-id lists")
        severe_rule_id = config.get("unsupported_evidence_severe_rule_id")
        if severe_rule_id is not None and (
            not isinstance(severe_rule_id, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]{1,127}", severe_rule_id) is None
        ):
            raise ValueError("source_provenance grader config.unsupported_evidence_severe_rule_id must be an identifier")
    elif implementation == "forbidden_token":
        _require_exact_config_keys(implementation, config, {"forbidden_tokens"}, {"severe_rule_id"})
        if not isinstance(config["forbidden_tokens"], tuple) or not all(isinstance(item, str) and item for item in config["forbidden_tokens"]):
            raise ValueError("forbidden_token grader config.forbidden_tokens must be a non-empty string tuple")
        if "severe_rule_id" in config and not isinstance(config["severe_rule_id"], str):
            raise ValueError("forbidden_token grader config.severe_rule_id must be a string")
    elif implementation == "state_oracle":
        _require_exact_config_keys(implementation, config, {"state_key", "expected"}, {"failure_rule_id"})
        if not isinstance(config["state_key"], str) or not config["state_key"]:
            raise ValueError("state_oracle grader config.state_key must be a non-empty string")
        if "failure_rule_id" in config and not isinstance(config["failure_rule_id"], str):
            raise ValueError("state_oracle grader config.failure_rule_id must be a string")
    elif implementation == "manipulation_fidelity":
        _require_exact_config_keys(implementation, config, {"expected_assignments"}, {"failure_rule_id"})
        assignments = config["expected_assignments"]
        if not isinstance(assignments, Mapping) or not all(
            isinstance(key, str) and isinstance(value, (str, int, bool)) and not isinstance(value, float)
            for key, value in assignments.items()
        ):
            raise ValueError("manipulation_fidelity grader config.expected_assignments must be a scalar mapping")
        if "failure_rule_id" in config and not isinstance(config["failure_rule_id"], str):
            raise ValueError("manipulation_fidelity grader config.failure_rule_id must be a string")
    elif implementation == "context_handoff_delivery":
        _require_exact_config_keys(implementation, config, {"task", "packet", "renderer_digest"}, {"failure_rule_id"})
        if not isinstance(config["task"], str) or not isinstance(config["packet"], Mapping) or not isinstance(config["renderer_digest"], str) or re.fullmatch(r"[a-f0-9]{64}", config["renderer_digest"]) is None:
            raise ValueError("context_handoff_delivery grader requires a task, packet mapping, and renderer digest")
        if "failure_rule_id" in config and (not isinstance(config["failure_rule_id"], str) or re.fullmatch(r"[a-z][a-z0-9_-]{1,127}", config["failure_rule_id"]) is None):
            raise ValueError("context_handoff_delivery grader failure_rule_id must be an identifier")


class StateOracle(ProtocolModel):
    oracle_id: Identifier
    kind: Literal["exact_match", "json_schema", "predicate", "state_snapshot"]
    expected: Any
    description: str = Field(min_length=1)


class FaultMetadata(ProtocolModel):
    fault_id: Identifier
    category: Literal["input", "tool", "context", "state", "policy"]
    description: str = Field(min_length=1)
    expected_recovery: str | None = None


class FaultScheduleEntry(ProtocolModel):
    fault_id: Identifier
    trigger: Literal["start", "request", "tool_call", "state_transition", "response"]
    ordinal: Annotated[int, Field(ge=0)] = 0
    description: str = Field(min_length=1)


class InitialStateRef(ProtocolModel):
    state_id: Identifier
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ToolFixture(ProtocolModel):
    tool_id: Identifier
    fixture_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReferenceSolution(ProtocolModel):
    reference_id: Identifier
    artifact_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    solvability_proof: str = Field(min_length=1)


class EvidenceSource(ProtocolModel):
    source_id: Identifier
    source_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    classification: Literal["synthetic", "public", "private", "restricted"]


class OutputContract(ProtocolModel):
    schema_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    format: Literal["json", "text", "tool_call"]
    description: str = Field(min_length=1)


class SevereFailureRule(ProtocolModel):
    rule_id: Identifier
    condition: str = Field(min_length=1)
    consequence: str = Field(min_length=1)


class ManipulationCheck(ProtocolModel):
    factor_id: Identifier
    expected_value: str | int | bool
    oracle: str = Field(min_length=1)


class TreatmentMutation(ProtocolModel):
    target: str = Field(min_length=1)
    operation: Literal["set", "enable", "disable", "select"]
    level: str | int | bool
    value: str | int | bool | None = None

    @field_validator("target")
    @classmethod
    def declarative_target(cls, value: str) -> str:
        if value.startswith(("/", "~")) or ".." in value or any(token in value.lower() for token in ("import", "exec", "eval", "script", "command")):
            raise ValueError("treatment mutations must be declarative, non-executable targets")
        return value


class IncompatibleLevelCombination(ProtocolModel):
    assignments: dict[Identifier, str | int | bool]
    reason: str = Field(min_length=1)


class ShamTreatment(ProtocolModel):
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    levels: tuple[str | int | bool, ...] = ()


class CapabilityRequirement(ProtocolModel):
    capability: Literal["tools", "state", "checkpoint", "memory", "delegation", "streaming", "usage", "sandboxing"]
    required: bool = True


class ScenarioSpec(ExtensibleProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    scenario_id: Identifier
    title: str = Field(min_length=1)
    task_family: Identifier
    prompt: str = Field(min_length=1)
    source_label: Literal["synthetic", "provided", "mixed"] = "synthetic"
    data_classification: Literal["synthetic", "public", "private", "restricted"] = "synthetic"
    control_role: Literal["candidate", "positive", "negative", "anti_cheat"] = "candidate"
    cluster_id: Identifier | None = None
    variant: Literal["clean", "stress"] = "clean"
    pair_id: Identifier | None = None
    paired_scenario_id: Identifier | None = None
    fault_metadata: FaultMetadata | None = None
    fault_definitions: tuple[FaultMetadata, ...] = ()
    initial_state: InitialStateRef | None = None
    tool_fixtures: tuple[ToolFixture, ...] = ()
    reference_solution: ReferenceSolution | None = None
    evidence_sources: tuple[EvidenceSource, ...] = ()
    output_contract: OutputContract | None = None
    prohibited_behavior: tuple[str, ...] = ()
    severe_failure_rules: tuple[SevereFailureRule, ...] = ()
    allowed_claims: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    fault_schedule: tuple[FaultScheduleEntry, ...] = ()
    final_state_oracle: StateOracle | None = None
    state_oracle: StateOracle | None = None
    deterministic_metrics: tuple[DeterministicMetric, ...] = ()
    manipulation_checks: tuple[ManipulationCheck, ...] = ()
    tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_pairing(self) -> ScenarioSpec:
        declared_faults = {fault.fault_id for fault in self.fault_definitions}
        if self.fault_metadata is not None:
            declared_faults.add(self.fault_metadata.fault_id)
        scheduled_faults = {entry.fault_id for entry in self.fault_schedule}
        schedule_coordinates = [(entry.fault_id, entry.trigger, entry.ordinal) for entry in self.fault_schedule]
        if len(declared_faults) != len(self.fault_definitions) + (self.fault_metadata is not None):
            raise ValueError("fault definition ids must be unique")
        if scheduled_faults - declared_faults:
            raise ValueError("fault schedule references an undeclared fault")
        if len(set(schedule_coordinates)) != len(schedule_coordinates):
            raise ValueError("fault schedule coordinates must be unique")
        if self.variant == "stress" and not declared_faults:
            raise ValueError("stress scenarios require declared fault metadata")
        if self.final_state_oracle is not None and self.state_oracle is not None:
            raise ValueError("use final_state_oracle; state_oracle is a compatibility field")
        if self.paired_scenario_id is not None and self.pair_id is None:
            raise ValueError("paired_scenario_id requires pair_id")
        if self.paired_scenario_id == self.scenario_id:
            raise ValueError("a scenario cannot pair with itself")
        metric_ids = [metric.metric_id for metric in self.deterministic_metrics]
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("deterministic metric ids must be unique")
        if sum(metric.weight for metric in self.deterministic_metrics) > 1.0:
            raise ValueError("deterministic metric weights cannot exceed 1.0")
        evidence_source_ids = [source.source_id for source in self.evidence_sources]
        if len(set(evidence_source_ids)) != len(evidence_source_ids):
            raise ValueError("evidence source ids must be unique")
        return self


class FactorSpec(ExtensibleProtocolModel):
    factor_id: Identifier
    kind: Literal["binary", "categorical", "ordinal"]
    levels: tuple[str | int | bool, ...]
    baseline: str | int | bool | None = None
    description: str = Field(min_length=1)
    treatment_mutations: tuple[TreatmentMutation, ...] = ()
    declarative_config: dict[str, str | int | bool] = Field(default_factory=dict)
    fixed_infrastructure: dict[str, str | int | bool] = Field(default_factory=dict)
    prohibited_co_mutations: tuple[str, ...] = ()
    manipulation_checks: tuple[ManipulationCheck, ...] = ()
    sham_treatment: ShamTreatment | None = None
    no_op_levels: tuple[str | int | bool, ...] = ()
    capability_requirements: tuple[CapabilityRequirement, ...] = ()
    incompatible_with: tuple[Identifier, ...] = ()
    incompatible_level_combinations: tuple[IncompatibleLevelCombination, ...] = ()
    expected_benefit: str | None = None
    expected_tax: str | None = None
    falsifying_result: str | None = None

    @model_validator(mode="after")
    def validate_levels(self) -> FactorSpec:
        if len(self.levels) < 2 or len(set(self.levels)) != len(self.levels):
            raise ValueError("factors require at least two unique levels")
        if self.kind == "binary" and (
            len(self.levels) != 2 or {type(level) for level in self.levels} != {bool} or set(self.levels) != {False, True}
        ):
            raise ValueError("binary factor levels must be false and true")
        if self.kind == "ordinal":
            if not all(isinstance(level, int) and not isinstance(level, bool) for level in self.levels):
                raise ValueError("ordinal factor levels must be integers")
            if tuple(sorted(self.levels)) != self.levels:
                raise ValueError("ordinal factor levels must be ascending")
        if self.baseline is not None and self.baseline not in self.levels:
            raise ValueError("factor baseline must be a declared level")
        mutation_levels = {mutation.level for mutation in self.treatment_mutations}
        if not mutation_levels.issubset(set(self.levels)):
            raise ValueError("treatment mutation level must be a declared factor level")
        no_op_levels = set(self.no_op_levels)
        if self.sham_treatment is not None:
            no_op_levels.update(self.sham_treatment.levels)
        if not no_op_levels.issubset(set(self.levels)):
            raise ValueError("no-op or sham levels must be declared factor levels")
        uncovered_levels = set(self.levels) - {self.baseline_value} - mutation_levels - no_op_levels
        if uncovered_levels:
            raise ValueError("every non-baseline factor level requires a mutation, no-op, or sham declaration")
        if self.factor_id in self.incompatible_with:
            raise ValueError("a factor cannot be incompatible with itself")
        for combination in self.incompatible_level_combinations:
            if self.factor_id not in combination.assignments:
                raise ValueError("incompatible level combinations must include this factor")
        return self

    @field_validator("declarative_config", "fixed_infrastructure")
    @classmethod
    def reject_executable_configuration(cls, value: dict[str, str | int | bool]) -> dict[str, str | int | bool]:
        forbidden = ("code", "exec", "eval", "import", "script", "command", "shell")
        if any(any(token in key.lower() for token in forbidden) for key in value):
            raise ValueError("factor configuration must be declarative, not executable")
        return value

    @property
    def baseline_value(self) -> str | int | bool:
        return self.levels[0] if self.baseline is None else self.baseline


class HarnessSpec(ExtensibleProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    harness_id: Identifier
    version: str = Field(min_length=1)
    adapter: Literal["http", "cli", "recorded", "in_process"]
    adapter_identity: str | None = None
    adapter_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)] = 120
    retries: Annotated[int, Field(ge=0, le=10)] = 0
    allowed_tools: tuple[Identifier, ...] = ()
    configuration: dict[str, Any] = Field(default_factory=dict)
    effective_configuration_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    capabilities: HarnessCapabilities = Field(default_factory=lambda: HarnessCapabilities())
    schema_hashes: HarnessSchemaHashes = Field(default_factory=lambda: HarnessSchemaHashes())
    execution_mode: Literal["local", "container", "remote", "recorded"] = "recorded"
    isolation: Literal["none", "process", "container", "remote_sandbox"] = "none"
    claim_eligibility: Literal["fixture_only", "protocol_only", "live_provider", "externally_validated"] = "fixture_only"

    @model_validator(mode="after")
    def validate_effective_configuration_hash(self) -> HarnessSpec:
        if self.configuration and self.effective_configuration_hash is None:
            raise ValueError("non-empty harness configuration requires effective_configuration_hash")
        if self.effective_configuration_hash is not None and self.effective_configuration_hash != canonical_configuration_hash(self.configuration):
            raise ValueError("effective_configuration_hash does not bind canonical configuration")
        if self.claim_eligibility != "fixture_only":
            if self.adapter_identity is None or self.adapter_digest is None:
                raise ValueError("claim-eligible harnesses require adapter identity and digest")
            if self.effective_configuration_hash is None:
                raise ValueError("claim-eligible harnesses require an effective configuration hash")
            required_hashes = (
                self.schema_hashes.input_hash,
                self.schema_hashes.output_hash,
                self.schema_hashes.trace_hash,
                self.schema_hashes.config_schema_hash,
            )
            if any(value is None for value in required_hashes):
                raise ValueError("claim-eligible harnesses require input, output, trace, and config schema hashes")
        if (
            self.claim_eligibility != "fixture_only"
            and (self.capabilities.tools or self.capabilities.state)
            and (
                self.execution_mode not in {"container", "remote"}
                or self.isolation not in {"container", "remote_sandbox"}
            )
        ):
            raise ValueError("tool-bearing or state-changing claim evidence requires container or remote sandbox isolation")
        return self


class HarnessCapabilities(ProtocolModel):
    tools: bool = False
    state: bool = False
    checkpoint: bool = False
    memory: bool = False
    delegation: bool = False
    streaming: bool = False
    usage: bool = False
    sandboxing: bool = False


class HarnessSchemaHashes(ProtocolModel):
    input_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    output_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    trace_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    config_schema_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CustomTreatment(ProtocolModel):
    treatment_id: Identifier | None = None
    assignments: dict[Identifier, str | int | bool]


class ModelEndpoint(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    endpoint_id: Identifier
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    endpoint_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SamplingSpec(ProtocolModel):
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0
    top_p: Annotated[float, Field(gt=0.0, le=1.0)] = 1.0
    max_tokens: Annotated[int, Field(ge=1)] = 1024


class RandomizationBlock(ProtocolModel):
    block_id: Identifier
    unit: Literal["scenario", "model", "harness", "cluster"]
    values: tuple[Identifier, ...]


class StoppingRule(ProtocolModel):
    rule_id: Identifier
    condition: str = Field(min_length=1)
    action: Literal["stop", "hold", "escalate"]


class BudgetSpec(ProtocolModel):
    max_attempts: Annotated[int, Field(ge=1)]
    max_cost_usd: Annotated[float, Field(ge=0.0)]
    max_latency_seconds: Annotated[float, Field(gt=0.0)]
    max_tokens: Annotated[int, Field(ge=1)]
    max_tool_calls: Annotated[int, Field(ge=0)]
    max_context_tokens: Annotated[int, Field(ge=1, description="Maximum input context consumption, measured in provider-reported tokens.")]


class AggregateBudgetSpec(ProtocolModel):
    max_total_cost_usd: Annotated[float, Field(ge=0.0)]
    max_total_tokens: Annotated[int, Field(ge=1)]
    max_total_tool_calls: Annotated[int, Field(ge=0)]
    max_wall_time_seconds: Annotated[float, Field(gt=0.0)]
    max_attempts: Annotated[int, Field(ge=1)]


class OutcomeInteraction(ProtocolModel):
    interaction_id: Identifier
    factor_ids: tuple[Identifier, ...]
    outcome_id: Identifier


class AdequacyRule(ProtocolModel):
    minimum_completed_attempts: Annotated[int, Field(ge=1)]
    required_balance: bool = True
    rationale: str = Field(min_length=1)


class ExperimentSpec(ExtensibleProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    experiment_id: Identifier
    study_pack_id: Identifier
    study_pack_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    scenario_ids: tuple[Identifier, ...]
    harness_ids: tuple[Identifier, ...]
    questions: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    model_endpoints: tuple[ModelEndpoint, ...] = ()
    sampling: SamplingSpec = Field(default_factory=SamplingSpec)
    repetitions: Annotated[int, Field(ge=1)] = 1
    randomization_blocks: tuple[RandomizationBlock, ...] = ()
    randomization_seed: Annotated[int, Field(ge=0)] = 0
    stopping_rules: tuple[StoppingRule, ...] = ()
    budgets: BudgetSpec | None = None
    aggregate_budget: AggregateBudgetSpec | None = None
    factors: tuple[FactorSpec, ...] = ()
    design: Literal["full", "fractional", "custom"] = "full"
    custom_design: tuple[CustomTreatment, ...] = ()
    deterministic_weight: Annotated[float, Field(ge=0.70, le=1.0)]
    manipulation_checks: tuple[ManipulationCheck, ...] = ()
    primary_outcomes: tuple[Identifier, ...] = ()
    interactions: tuple[OutcomeInteraction, ...] = ()
    multiple_comparison_correction: Literal["none", "bonferroni", "holm", "benjamini_hochberg"] = "none"
    adequacy_rule: AdequacyRule | None = None
    claim_ceiling: str = "protocol evidence only"
    claim_bearing: bool = False
    owner_approval: Literal["pending", "approved", "rejected"] = "pending"
    predecessor_experiment_id: Identifier | None = None
    predecessor_version: str | None = Field(default=None, deprecated=True)
    frozen: bool = False
    freeze_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    frozen_at: datetime | None = None

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "frozen", False):
            raise TypeError("frozen experiments are immutable")
        super().__setattr__(name, value)

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> ExperimentSpec:
        if self.frozen:
            raise TypeError("frozen experiments are immutable")
        return super().model_copy(update=update, deep=deep)

    @model_validator(mode="after")
    def validate_experiment(self) -> ExperimentSpec:
        if not self.scenario_ids or not self.harness_ids:
            raise ValueError("experiments require scenarios and harnesses")
        if self.predecessor_experiment_id == self.experiment_id:
            raise ValueError("an experiment cannot be its own predecessor")
        for ids, label in (
            (self.scenario_ids, "scenario"),
            (self.harness_ids, "harness"),
            (tuple(endpoint.endpoint_id for endpoint in self.model_endpoints), "model endpoint"),
            (tuple(block.block_id for block in self.randomization_blocks), "randomization block"),
            (tuple(rule.rule_id for rule in self.stopping_rules), "stopping rule"),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"{label} ids must be unique")
        factor_ids = [factor.factor_id for factor in self.factors]
        if len(set(factor_ids)) != len(factor_ids):
            raise ValueError("factor ids must be unique")
        unknown = {item for factor in self.factors for item in factor.incompatible_with} - set(factor_ids)
        if unknown:
            raise ValueError(f"factor incompatibility references unknown factors: {sorted(unknown)}")
        all_checks = self.manipulation_checks + tuple(
            check for factor in self.factors for check in factor.manipulation_checks
        )
        check_ids = {check.factor_id for check in all_checks}
        if not check_ids.issubset(set(factor_ids)):
            raise ValueError("manipulation checks must reference declared factors")
        level_by_factor = {factor.factor_id: set(factor.levels) for factor in self.factors}
        for check in all_checks:
            if check.expected_value not in level_by_factor[check.factor_id]:
                raise ValueError("manipulation check expected_value must be a factor level")
        if self.factors and check_ids != set(factor_ids):
            raise ValueError("every varied factor requires a manipulation check")
        for factor in self.factors:
            for combination in factor.incompatible_level_combinations:
                unknown_assignment_factors = set(combination.assignments) - set(factor_ids)
                if unknown_assignment_factors:
                    raise ValueError("incompatible level combination references unknown factor")
                for assigned_factor, value in combination.assignments.items():
                    if value not in level_by_factor[assigned_factor]:
                        raise ValueError("incompatible level combination uses undeclared level")
        if any(set(item.factor_ids) - set(factor_ids) for item in self.interactions):
            raise ValueError("interactions must reference declared factors")
        if self.design == "custom" and not self.custom_design:
            raise ValueError("custom designs require custom_design")
        if self.design != "custom" and self.custom_design:
            raise ValueError("custom_design is only valid for custom designs")
        if self.design == "custom":
            treatment_ids = [row.treatment_id for row in self.custom_design]
            if any(treatment_id is None for treatment_id in treatment_ids):
                raise ValueError("custom design rows require treatment_id")
            if len(set(treatment_ids)) != len(treatment_ids):
                raise ValueError("custom design treatment ids must be unique")
            assignment_keys: set[tuple[tuple[str, str | int | bool], ...]] = set()
            for row in self.custom_design:
                if set(row.assignments) != set(factor_ids):
                    raise ValueError("custom design rows must assign every factor exactly once")
                if any(value not in level_by_factor[factor_id] for factor_id, value in row.assignments.items()):
                    raise ValueError("custom design row uses an undeclared factor level")
                assignment_key = tuple(sorted(row.assignments.items()))
                if assignment_key in assignment_keys:
                    raise ValueError("custom design assignments must be unique")
                assignment_keys.add(assignment_key)
        if self.budgets is not None and self.sampling.max_tokens > self.budgets.max_tokens:
            raise ValueError("sampling max_tokens cannot exceed the attempt token budget")
        if self.frozen and self.claim_bearing:
            if not self.primary_outcomes:
                raise ValueError("claim-bearing frozen experiments require primary outcomes")
            if self.model_endpoints and any(endpoint.endpoint_digest is None for endpoint in self.model_endpoints):
                raise ValueError("claim-bearing frozen experiments require pinned model endpoint digests")
        if self.frozen != (self.freeze_hash is not None and self.frozen_at is not None and self.study_pack_hash is not None):
            raise ValueError("frozen experiments require freeze_hash, frozen_at, and study_pack_hash; unfrozen experiments require neither freeze field")
        return self


class Episode(ProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    episode_id: Identifier
    experiment_id: Identifier
    scenario_id: Identifier
    harness_id: Identifier
    treatment: dict[Identifier, str | int | bool] = Field(default_factory=dict)
    seed: Annotated[int, Field(ge=0)]


class ProvenanceSourceRef(ProtocolModel):
    source_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExecutionProvenance(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    protocol_version: ProtocolVersion = "1.0"
    code_revision: str = Field(min_length=1)
    code_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_image: str = Field(min_length=1)
    runtime_image_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    tool_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_refs: tuple[ProvenanceSourceRef, ...] = Field(min_length=1)
    captured_at: datetime

    @field_validator("code_revision", "runtime_image")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provenance identity fields cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_capture(self) -> ExecutionProvenance:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        source_pairs = [(source.source_uri, source.content_hash) for source in self.source_refs]
        if len(set(source_pairs)) != len(source_pairs):
            raise ValueError("provenance source URI/hash pairs must be unique")
        return self


class AttemptEnvelope(ProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    attempt_id: Identifier
    episode_id: Identifier
    ordinal: Annotated[int, Field(ge=1)]
    provider_model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    endpoint_id: Identifier | None = None
    pinned_endpoint_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_provider_version: str | None = None
    observed_endpoint_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    harness_id: Identifier
    factor_assignments: dict[Identifier, str | int | bool]
    budget: BudgetSpec
    provenance: ExecutionProvenance
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    status: Literal["queued", "started", "completed", "failed", "timed_out", "cancelled", "incomplete"]
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> AttemptEnvelope:
        terminal = {"completed", "failed", "timed_out", "cancelled", "incomplete"}
        if (self.endpoint_id is None) != (self.pinned_endpoint_digest is None):
            raise ValueError("endpoint_id and pinned_endpoint_digest must appear together")
        if (self.observed_endpoint_digest is not None or self.observed_provider_version is not None) and self.endpoint_id is None:
            raise ValueError("endpoint observations require a pinned endpoint binding")
        if self.status == "queued" and (self.started_at is not None or self.completed_at is not None):
            raise ValueError("queued attempts cannot have start or completion timestamps")
        if self.status == "queued" and (
            self.observed_endpoint_digest is not None or self.observed_provider_version is not None
        ):
            raise ValueError("queued attempts cannot contain endpoint observations")
        if self.status == "started" and (self.started_at is None or self.completed_at is not None):
            raise ValueError("started attempts require started_at and no completed_at")
        if self.status in terminal and (self.started_at is None or self.completed_at is None):
            raise ValueError("terminal attempts require started_at and completed_at")
        if self.started_at is not None and self.started_at < self.queued_at:
            raise ValueError("started_at cannot precede queued_at")
        if self.completed_at is not None and self.started_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        return self

    @property
    def runtime_hash(self) -> str:
        return self.provenance.runtime_image_hash

    @property
    def code_hash(self) -> str:
        return self.provenance.code_hash

    @property
    def prompt_hash(self) -> str:
        return self.provenance.prompt_hash

    @property
    def context_hash(self) -> str:
        return self.provenance.context_hash

    @property
    def tool_hash(self) -> str:
        return self.provenance.tool_hash


class TraceEvent(ProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    trace_id: Identifier
    episode_id: Identifier
    attempt_id: Identifier
    sequence: Annotated[int, Field(ge=0)]
    actor: Literal["harness", "model", "tool", "evaluator", "system"]
    event_type: Literal["request", "response", "tool_call", "tool_result", "state", "error"]
    timestamp: datetime
    monotonic_time: Annotated[float, Field(ge=0.0)]
    source_time: datetime | None = None
    state_ref: InitialStateRef | None = None
    redaction: Literal["none", "partial", "full"] = "none"
    payload: dict[str, Any]
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class OutcomeVector(ProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    episode_id: Identifier
    mission_success: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    severe_failures: tuple[Identifier, ...] = ()
    consistency: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    cost_status: Literal["within_budget", "over_budget", "unknown"] = "unknown"
    cost_usd: Annotated[float, Field(ge=0.0)] | None = None
    latency_seconds: Annotated[float, Field(ge=0.0)] | None = None
    tool_calls: Annotated[int, Field(ge=0)] = 0
    auditability: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    deterministic: dict[Identifier, Annotated[float, Field(ge=0.0, le=1.0)]]
    model_judged: dict[Identifier, Annotated[float, Field(ge=0.0, le=1.0)]] = Field(default_factory=dict)
    human: dict[Identifier, Annotated[float, Field(ge=0.0, le=1.0)]] = Field(default_factory=dict)


class EvaluationRecord(ProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    evaluation_id: Identifier
    episode_id: Identifier
    outcome: OutcomeVector
    deterministic_weight: Annotated[float, Field(ge=0.70, le=1.0)]
    evaluator_version: str = Field(min_length=1)
    trace_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class LegacyHumanAnnotation(ProtocolModel):
    """Deprecated frozen-study artifact shape; not an active API contract."""
    annotation_id: Identifier
    episode_id: Identifier
    dimension: Identifier
    score: Annotated[float, Field(ge=0.0, le=1.0)]
    annotator_pseudonym: str = Field(min_length=1)


class LegacyHumanAnnotationBatch(ProtocolModel):
    """Deprecated frozen-study artifact shape; not an active API contract."""
    protocol_version: ProtocolVersion = "1.0"
    batch_id: Identifier
    protocol_id: str = Field(min_length=1)
    annotations: tuple[LegacyHumanAnnotation, ...]
    created_at: datetime


class LegacyEvidenceReceipt(ProtocolModel):
    """Deprecated protocol artifact shape; use evidence_v1.EvidenceReceipt for APIs."""
    protocol_version: ProtocolVersion = "1.0"
    receipt_id: Identifier
    artifact_type: Literal["study_pack", "trace", "evaluation", "report", "annotation"]
    artifact_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluator_hashes: tuple[Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")], ...]
    source_uri: str = Field(min_length=1)
    created_at: datetime
    claim_ceiling: str = Field(min_length=1)
    limitations: tuple[str, ...]
    integrity_not_truth: Literal[True] = True


class LegacyReproductionReceipt(ProtocolModel):
    """Deprecated protocol artifact shape; use evidence_v1.ReproductionReceipt for APIs."""
    protocol_version: ProtocolVersion = "1.0"
    receipt_id: Identifier
    experiment_id: Identifier
    experiment_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    study_pack_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluator_hashes: tuple[Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")], ...]
    command: tuple[str, ...]
    environment: dict[str, str]
    created_at: datetime
    limitations: tuple[str, ...]
    integrity_not_truth: Literal[True] = True


class DecisionBrief(ProtocolModel):
    """Offline-only protocol artifact; `/api/v1/decision-briefs` uses Analysis v1 contracts."""

    protocol_version: ProtocolVersion = "1.0"
    brief_id: Identifier
    experiment_id: Identifier
    verdict: Literal["advance", "hold", "reject"]
    outcome_summary: OutcomeVector
    evidence_receipt_ids: tuple[Identifier, ...]
    claim_ceiling: str = Field(min_length=1)
    next_action: str = Field(min_length=1)


class PackAuthor(ProtocolModel):
    name: str = Field(min_length=1)
    affiliation: str | None = None
    orcid: str | None = None


class CompatibilityRange(ProtocolModel):
    protocol_min: str = Field(min_length=1)
    protocol_max: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_current_protocol(self) -> CompatibilityRange:
        def parse(value: str) -> tuple[int, ...]:
            parts = value.split(".")
            if not parts or any(not part.isdigit() for part in parts):
                raise ValueError("compatibility versions must be dot-separated numeric protocol versions")
            return tuple(int(part) for part in parts)

        minimum = parse(self.protocol_min)
        maximum = parse(self.protocol_max)
        width = max(len(minimum), len(maximum), 2)
        minimum += (0,) * (width - len(minimum))
        maximum += (0,) * (width - len(maximum))
        current = (1, 0) + (0,) * (width - 2)
        if minimum > maximum:
            raise ValueError("protocol_min cannot exceed protocol_max")
        if not minimum <= current <= maximum:
            raise ValueError("compatibility range must include protocol 1.0")
        return self


class PreregistrationReference(ProtocolModel):
    reference_uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReadinessIssue(ProtocolModel):
    code: Identifier
    scope: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ProtocolReadinessReport(ProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    verdict: Literal["PASS", "HOLD"]
    task_family_deterministic_weights: dict[Identifier, Annotated[float, Field(ge=0.0, le=1.0)]]
    issues: tuple[ReadinessIssue, ...]


class StudyPack(ExtensibleProtocolModel):
    protocol_version: ProtocolVersion = "1.0"
    study_pack_id: Identifier
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    license_spdx: str = Field(min_length=1)
    authors: tuple[PackAuthor, ...] = Field(min_length=1)
    compatibility: CompatibilityRange
    allowed_claims: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    preregistration: PreregistrationReference
    scenarios: tuple[ScenarioSpec, ...]
    graders: tuple[GraderSpec, ...] = ()
    harnesses: tuple[HarnessSpec, ...]
    experiments: tuple[ExperimentSpec, ...]
    description: str | None = None

    @field_validator("scenarios", "harnesses", "experiments")
    @classmethod
    def non_empty(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        if not values:
            raise ValueError("study packs require at least one entry")
        return values

    @model_validator(mode="after")
    def validate_references(self) -> StudyPack:
        scenario_ids = {scenario.scenario_id for scenario in self.scenarios}
        harness_ids = {harness.harness_id for harness in self.harnesses}
        grader_ids = {grader.grader_id for grader in self.graders}
        if len(scenario_ids) != len(self.scenarios) or len(harness_ids) != len(self.harnesses):
            raise ValueError("scenario and harness ids must be unique")
        if len(grader_ids) != len(self.graders):
            raise ValueError("grader ids must be unique")
        by_id = {scenario.scenario_id: scenario for scenario in self.scenarios}
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(set(experiment_ids)) != len(experiment_ids):
            raise ValueError("experiment ids must be unique")
        for scenario in self.scenarios:
            if scenario.paired_scenario_id and scenario.paired_scenario_id not in scenario_ids:
                raise ValueError("paired scenario must be present in the study pack")
            if scenario.paired_scenario_id:
                peer = by_id[scenario.paired_scenario_id]
                if peer.paired_scenario_id != scenario.scenario_id or peer.pair_id != scenario.pair_id or peer.variant == scenario.variant:
                    raise ValueError("scenario pairs must be clean/stress peers with a shared pair_id")
        for experiment in self.experiments:
            if experiment.study_pack_id != self.study_pack_id:
                raise ValueError("experiment study_pack_id must match its pack")
            if not set(experiment.scenario_ids).issubset(scenario_ids):
                raise ValueError("experiment references an unknown scenario")
            if not set(experiment.harness_ids).issubset(harness_ids):
                raise ValueError("experiment references an unknown harness")
            experiment_factors = {factor.factor_id: factor for factor in experiment.factors}
            for scenario_id in experiment.scenario_ids:
                if not {check.factor_id for check in by_id[scenario_id].manipulation_checks}.issubset(experiment_factors):
                    raise ValueError("scenario manipulation checks must reference experiment factors")
            for factor in experiment.factors:
                for requirement in factor.capability_requirements:
                    if requirement.required and any(
                        not getattr(next(item for item in self.harnesses if item.harness_id == harness_id).capabilities, requirement.capability)
                        for harness_id in experiment.harness_ids
                    ):
                        raise ValueError("experiment harness lacks a required factor capability")
        return self


def assess_study_pack_readiness(study_pack: StudyPack, *, claim_bearing: bool = True) -> ProtocolReadinessReport:
    """Return a fail-closed readiness report without preventing exploratory specs."""
    issues: list[ReadinessIssue] = []
    weights: dict[str, float] = {}
    graders = {grader.grader_id: grader for grader in study_pack.graders}
    task_families = sorted({scenario.task_family for scenario in study_pack.scenarios})
    for task_family in task_families:
        scenarios = tuple(scenario for scenario in study_pack.scenarios if scenario.task_family == task_family)
        contribution = min((sum(metric.weight for metric in scenario.deterministic_metrics) for scenario in scenarios), default=0.0)
        weights[task_family] = min(contribution, 1.0)
        if contribution < 0.70:
            issues.append(ReadinessIssue(code="deterministic-weight", scope=task_family, message="Deterministic contribution is below 0.70."))
        roles = {scenario.control_role for scenario in scenarios}
        for required_role in ("positive", "negative", "anti_cheat"):
            if required_role not in roles:
                issues.append(
                    ReadinessIssue(
                        code=f"missing-{required_role.replace('_', '-')}",
                        scope=task_family,
                        message=f"Task family lacks a {required_role} control scenario.",
                    )
                )
        if claim_bearing:
            for scenario in scenarios:
                for metric in scenario.deterministic_metrics:
                    grader = graders.get(metric.oracle)
                    if grader is None:
                        issues.append(
                            ReadinessIssue(
                                code="unknown-grader",
                                scope=scenario.scenario_id,
                                message=f"Deterministic metric {metric.metric_id} references undeclared grader {metric.oracle}.",
                            )
                        )
                    elif grader.kind != "deterministic":
                        issues.append(
                            ReadinessIssue(
                                code="grader-kind",
                                scope=scenario.scenario_id,
                                message=f"Deterministic metric {metric.metric_id} references qualitative grader {metric.oracle}.",
                            )
                        )
                missing = []
                if scenario.reference_solution is None:
                    missing.append("reference solution")
                if scenario.output_contract is None:
                    missing.append("output contract")
                if scenario.final_state_oracle is None and scenario.state_oracle is None:
                    missing.append("state oracle")
                if missing:
                    issues.append(
                        ReadinessIssue(
                            code="scenario-reference-gap",
                            scope=scenario.scenario_id,
                            message=f"Missing {', '.join(missing)}.",
                        )
                    )
    return ProtocolReadinessReport(
        verdict="HOLD" if issues else "PASS",
        task_family_deterministic_weights=weights,
        issues=tuple(issues),
    )
