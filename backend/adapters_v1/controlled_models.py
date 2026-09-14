"""Additive adapter models that preserve protocol-v1 wire compatibility."""

from __future__ import annotations

from pydantic import ConfigDict, model_validator

from protocol_v1.canonical import canonical_json, sha256
from protocol_v1.models import AttemptEnvelope, ScenarioSpec

from .controls import (
    AppliedControls,
    AttemptExecutionControls,
    execution_controls_for,
    scenario_with_execution_controls,
)
from .models import AttemptInput as _AttemptInput
from .models import ResultBundle as _ResultBundle


class AttemptInput(_AttemptInput):
    """A protocol-v1 AttemptInput with a typed, hash-bound control overlay."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @property
    def execution_controls(self) -> AttemptExecutionControls:
        return execution_controls_for(self)

    @model_validator(mode="after")
    def validate_control_budget_binding(self) -> AttemptInput:
        controls = self.execution_controls
        budget = self.attempt.budget
        for requested, maximum, label in (
            (controls.max_output_tokens, budget.max_tokens, "max_output_tokens"),
            (controls.timeout_seconds, budget.max_latency_seconds, "timeout_seconds"),
            (controls.max_tool_calls, budget.max_tool_calls, "max_tool_calls"),
            (controls.max_context_tokens, budget.max_context_tokens, "max_context_tokens"),
            (controls.max_attempts, budget.max_attempts, "max_attempts"),
        ):
            if requested > maximum:
                raise ValueError(
                    f"execution control {label} exceeds the immutable attempt budget"
                )
        return self

    @classmethod
    def bind(
        cls,
        scenario: ScenarioSpec,
        attempt: AttemptEnvelope,
        *,
        execution_controls: AttemptExecutionControls | None = None,
    ) -> AttemptInput:
        scenario = ScenarioSpec.model_validate_json(
            canonical_json(scenario.model_dump(mode="json"))
        )
        attempt = AttemptEnvelope.model_validate_json(
            canonical_json(attempt.model_dump(mode="json"))
        )
        if execution_controls is not None:
            execution_controls = AttemptExecutionControls.model_validate_json(
                canonical_json(execution_controls.model_dump(mode="json"))
            )
            scenario = scenario_with_execution_controls(scenario, execution_controls)
        scenario_json = scenario.model_dump(mode="json")
        scenario_digest = sha256(scenario_json)
        return cls(
            scenario=scenario,
            attempt=attempt,
            scenario_digest=scenario_digest,
            binding_digest=sha256(
                {
                    "scenario_id": scenario.scenario_id,
                    "scenario_digest": scenario_digest,
                    "attempt": attempt.model_dump(mode="json"),
                }
            ),
        )


class ResultBundle(_ResultBundle):
    """Adapter result with an optional content-addressed control receipt."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    applied_controls: AppliedControls | None = None
