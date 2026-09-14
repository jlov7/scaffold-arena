"""Strict, serialisable contracts for the bounded P/V/R/M factor runtime.

This module deliberately composes protocol declarations only.  It does not
execute a model, replace Arena evaluation, or create persistence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from protocol_v1.models import HarnessCapabilities, ProtocolModel

FactorId = Literal["planning", "verification", "recovery", "memory"]
MechanismMode = Literal["active", "sham"]
PlanStepState = Literal["pending", "in_progress", "completed", "failed"]
CheckStatus = Literal["passed", "failed"]
FailureClass = Literal["transient", "undeclared", "permanent", "safety"]


class FrozenFactorModel(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CapabilityProfile(FrozenFactorModel):
    """A declared profile used only to decide whether a recipe may compile."""

    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    adapter_kind: Literal["recorded", "native"]
    capabilities: HarnessCapabilities


class TreatmentBudget(FrozenFactorModel):
    """A matched treatment envelope, not a measurement of consumed resources."""

    compute_units: int = Field(ge=1, le=1_000_000)
    context_bytes: int = Field(ge=0, le=100_000_000)


class EvidencePointer(FrozenFactorModel):
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompiledMechanism(FrozenFactorModel):
    factor_id: FactorId
    selected_level: bool
    mode: MechanismMode
    configuration: dict[str, str | int | bool]
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    treatment_budget: TreatmentBudget
    required_capabilities: tuple[str, ...]
    fidelity_oracles: tuple[str, ...]


class CompiledRecipe(FrozenFactorModel):
    recipe_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    assignment: dict[FactorId, bool]
    mechanisms: tuple[CompiledMechanism, ...]
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_id: str
    execution_claim: Literal["not_executed"] = "not_executed"


class PlanStep(FrozenFactorModel):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    description: str = Field(min_length=1)
    state: PlanStepState = "pending"
    terminal_evidence: EvidencePointer | None = None

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> PlanStep:
        if self.state in {"completed", "failed"} and self.terminal_evidence is None:
            raise ValueError("terminal plan steps require terminal evidence")
        if self.state not in {"completed", "failed"} and self.terminal_evidence is not None:
            raise ValueError("only terminal plan steps may carry terminal evidence")
        return self


class PlanArtifact(FrozenFactorModel):
    episode_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    plan_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    steps: tuple[PlanStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_step_ids(self) -> PlanArtifact:
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step ids must be unique and immutable")
        return self


class VerificationCheck(FrozenFactorModel):
    check_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    status: CheckStatus
    detail: str = Field(min_length=1)
    evidence: tuple[EvidencePointer, ...] = Field(min_length=1)


class FinalizationCandidate(FrozenFactorModel):
    episode_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    response_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class RepairAttempt(FrozenFactorModel):
    repair_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    episode_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    original_candidate_response_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    checks: tuple[VerificationCheck, ...] = Field(min_length=1)
    evidence: tuple[EvidencePointer, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def bind_changed_response(self) -> RepairAttempt:
        if self.response_hash == self.original_candidate_response_hash:
            raise ValueError("repair response_hash must differ from the original candidate")
        return self


class VerificationArtifact(FrozenFactorModel):
    episode_id: str
    candidate_response_hash: str
    final_response_hash: str | None
    checks: tuple[VerificationCheck, ...]
    repair_evidence: tuple[EvidencePointer, ...] = ()
    repairs_used: int = Field(ge=0, le=1)
    finalization_allowed: bool
    scope: Literal["agent_pre_finalization"] = "agent_pre_finalization"
    independent_arena_evaluation: Literal[False] = False
    failure_reason: str | None = None


class FailureEvent(FrozenFactorModel):
    episode_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    attempt_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    failure_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    failure_class: FailureClass
    detail: str = Field(min_length=1)


class CheckpointArtifact(FrozenFactorModel):
    checkpoint_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    episode_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    attempt_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    sequence: int = Field(ge=0)
    state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance: EvidencePointer

    @model_validator(mode="after")
    def bind_provenance_hash(self) -> CheckpointArtifact:
        if self.provenance.content_hash != self.state_hash:
            raise ValueError("checkpoint provenance content_hash must bind state_hash")
        return self


class RecoveryPolicy(FrozenFactorModel):
    max_retries: int = Field(ge=0, le=10)
    declared_transient_failures: tuple[str, ...] = ()

    @field_validator("declared_transient_failures")
    @classmethod
    def declared_failures_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("declared transient failures must be unique")
        return values


class RecoveryDecision(FrozenFactorModel):
    allowed: bool
    reason: str
    retry_number: int | None = Field(default=None, ge=1)
    idempotency_key: str
    checkpoint_id: str | None = None


class MemoryItem(FrozenFactorModel):
    item_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    episode_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    content: str = Field(min_length=1)
    source_pointers: tuple[EvidencePointer, ...] = Field(min_length=1)
    lineage: tuple[str, ...] = ()


class EpisodeMemory(FrozenFactorModel):
    episode_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    max_items: int = Field(ge=1, le=10_000)
    max_bytes: int = Field(ge=1, le=100_000_000)
    items: tuple[MemoryItem, ...] = ()
    total_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_contents(self) -> EpisodeMemory:
        if any(item.episode_id != self.episode_id for item in self.items):
            raise ValueError("episode memory cannot contain cross-episode items")
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("memory item ids must be unique")
        computed = sum(len(item.content.encode("utf-8")) for item in self.items)
        if computed != self.total_bytes:
            raise ValueError("memory total_bytes must match UTF-8 content")
        if len(self.items) > self.max_items or self.total_bytes > self.max_bytes:
            raise ValueError("episode memory exceeds its declared bounds")
        return self


class ManipulationFidelity(FrozenFactorModel):
    factor_id: FactorId
    expected_level: bool
    observed_level: bool
    mode: MechanismMode
    compute_context_matched: bool
    delivered: bool
    evidence: tuple[EvidencePointer, ...] = Field(min_length=1)
    claim: Literal["treatment_delivery_only"] = "treatment_delivery_only"
