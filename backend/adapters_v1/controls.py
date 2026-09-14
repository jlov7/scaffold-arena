"""Canonical requested and observed execution-control contracts.

Protocol v1 remains the evidence format.  These models live at the trusted
adapter boundary and are carried through the existing namespaced extension
surface so legacy protocol artifacts remain byte-compatible.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeAlias

from pydantic import ConfigDict, Field, model_validator

from protocol_v1.canonical import canonical_json, sha256
from protocol_v1.models import (
    AttemptEnvelope,
    ExperimentSpec,
    HarnessSpec,
    ProtocolModel,
    ScenarioSpec,
)

CONTROL_EXTENSION_NAMESPACE = "org.scaffold-arena.execution-controls"

CoreControlId: TypeAlias = Literal[
    "temperature",
    "top_p",
    "max_output_tokens",
    "seed",
    "timeout_seconds",
    "max_tool_calls",
    "max_context_tokens",
    "max_attempts",
]
ControlStatus: TypeAlias = Literal[
    "applied",
    "bound",
    "unsupported",
    "approximated",
    "provider_defaulted",
]
ControlValue: TypeAlias = str | int | float | bool | None

CORE_CONTROL_IDS: tuple[CoreControlId, ...] = (
    "temperature",
    "top_p",
    "max_output_tokens",
    "seed",
    "timeout_seconds",
    "max_tool_calls",
    "max_context_tokens",
    "max_attempts",
)


class AttemptExecutionControls(ProtocolModel):
    """The exact generation and runtime limits requested for one attempt."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    temperature: float = Field(ge=0.0, le=2.0)
    top_p: float = Field(gt=0.0, le=1.0)
    max_output_tokens: int = Field(ge=1)
    seed: int = Field(ge=0, le=2**31 - 1)
    timeout_seconds: float = Field(gt=0.0, le=3600.0)
    max_tool_calls: int = Field(ge=0)
    max_context_tokens: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    source: Literal["frozen_experiment", "compatibility_default"]

    @classmethod
    def compatibility(cls, attempt: AttemptEnvelope) -> AttemptExecutionControls:
        """Expose legacy behavior as an explicit, conservative control set."""

        return cls(
            temperature=0.0,
            top_p=1.0,
            max_output_tokens=attempt.budget.max_tokens,
            seed=0,
            timeout_seconds=attempt.budget.max_latency_seconds,
            max_tool_calls=attempt.budget.max_tool_calls,
            max_context_tokens=attempt.budget.max_context_tokens,
            max_attempts=attempt.budget.max_attempts,
            source="compatibility_default",
        )

    @classmethod
    def from_experiment(
        cls,
        spec: ExperimentSpec,
        *,
        seed: int,
        harness: HarnessSpec,
    ) -> AttemptExecutionControls:
        """Compile one frozen declaration into the adapter's executable input."""

        if spec.budgets is None:
            raise ValueError("executable controls require declared attempt budgets")
        budget = spec.budgets
        return cls(
            temperature=spec.sampling.temperature,
            top_p=spec.sampling.top_p,
            max_output_tokens=spec.sampling.max_tokens,
            seed=seed,
            timeout_seconds=min(
                float(harness.timeout_seconds),
                float(budget.max_latency_seconds),
            ),
            max_tool_calls=budget.max_tool_calls,
            max_context_tokens=budget.max_context_tokens,
            max_attempts=budget.max_attempts,
            source="frozen_experiment",
        )

    @property
    def digest(self) -> str:
        return sha256(self.model_dump(mode="json"))

    def control_values(self) -> dict[CoreControlId, ControlValue]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "seed": self.seed,
            "timeout_seconds": self.timeout_seconds,
            "max_tool_calls": self.max_tool_calls,
            "max_context_tokens": self.max_context_tokens,
            "max_attempts": self.max_attempts,
        }


class ControlApplication(ProtocolModel):
    """One adapter observation about one requested execution control."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    control_id: CoreControlId
    status: ControlStatus
    requested_value: ControlValue
    observed_value: ControlValue = None
    detail: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_observation(self) -> ControlApplication:
        if self.status in {"applied", "bound"} and self.observed_value is None:
            raise ValueError("applied or bound controls require an observed value")
        if (
            self.status in {"unsupported", "approximated", "provider_defaulted"}
            and self.detail is None
        ):
            raise ValueError("non-exact control applications require a detail")
        return self


class AppliedControls(ProtocolModel):
    """Content-addressed receipt for the controls observed by one adapter."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    controls: tuple[ControlApplication, ...] = Field(min_length=1)
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=512)
    receipt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @staticmethod
    def digest_for(
        controls: tuple[ControlApplication, ...],
        provider_request_id: str | None,
    ) -> str:
        return sha256(
            {
                "controls": [item.model_dump(mode="json") for item in controls],
                "provider_request_id": provider_request_id,
            }
        )

    @classmethod
    def bind(
        cls,
        controls: tuple[ControlApplication, ...],
        *,
        provider_request_id: str | None = None,
    ) -> AppliedControls:
        canonical = tuple(
            ControlApplication.model_validate_json(
                canonical_json(item.model_dump(mode="json"))
            )
            for item in controls
        )
        return cls(
            controls=canonical,
            provider_request_id=provider_request_id,
            receipt_digest=cls.digest_for(canonical, provider_request_id),
        )

    @model_validator(mode="after")
    def validate_receipt(self) -> AppliedControls:
        control_ids = [item.control_id for item in self.controls]
        if len(control_ids) != len(set(control_ids)):
            raise ValueError("control application identifiers must be unique")
        expected = self.digest_for(self.controls, self.provider_request_id)
        if self.receipt_digest != expected:
            raise ValueError("receipt_digest does not bind the applied controls")
        return self

    @property
    def by_id(self) -> dict[CoreControlId, ControlApplication]:
        return {item.control_id: item for item in self.controls}


def execution_controls_for(
    scenario_or_input: ScenarioSpec | Any,
    attempt: AttemptEnvelope | None = None,
) -> AttemptExecutionControls:
    """Recover controls from a scenario snapshot or an AttemptInput-like object."""

    if attempt is None:
        scenario = scenario_or_input.scenario
        attempt = scenario_or_input.attempt
    else:
        scenario = scenario_or_input
    if not isinstance(scenario, ScenarioSpec) or not isinstance(attempt, AttemptEnvelope):
        raise TypeError("execution controls require a ScenarioSpec and AttemptEnvelope")
    raw = scenario.extensions.get(CONTROL_EXTENSION_NAMESPACE)
    if raw is None:
        return AttemptExecutionControls.compatibility(attempt)
    if not isinstance(raw, Mapping):
        raise ValueError("execution-control extension must be a JSON object")
    return AttemptExecutionControls.model_validate(dict(raw))


def scenario_with_execution_controls(
    scenario: ScenarioSpec,
    controls: AttemptExecutionControls,
) -> ScenarioSpec:
    """Return a canonical scenario snapshot carrying the immutable control overlay."""

    existing = scenario.extensions.get(CONTROL_EXTENSION_NAMESPACE)
    control_payload = controls.model_dump(mode="json")
    if existing is not None and dict(existing) != control_payload:
        raise ValueError("scenario already binds a different execution-control set")
    extensions = dict(scenario.extensions)
    extensions[CONTROL_EXTENSION_NAMESPACE] = control_payload
    updated = scenario.model_copy(update={"extensions": extensions})
    return ScenarioSpec.model_validate_json(
        canonical_json(updated.model_dump(mode="json"))
    )


def scenario_without_execution_controls(scenario: ScenarioSpec) -> ScenarioSpec:
    """Recover the frozen StudyPack scenario identity beneath the runtime overlay."""

    if CONTROL_EXTENSION_NAMESPACE not in scenario.extensions:
        return ScenarioSpec.model_validate_json(
            canonical_json(scenario.model_dump(mode="json"))
        )
    extensions = dict(scenario.extensions)
    extensions.pop(CONTROL_EXTENSION_NAMESPACE, None)
    updated = scenario.model_copy(update={"extensions": extensions})
    return ScenarioSpec.model_validate_json(
        canonical_json(updated.model_dump(mode="json"))
    )
