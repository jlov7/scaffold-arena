from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from adapters_v1 import (
    AppliedControls,
    AttemptExecutionControls,
    AttemptInput,
    ControlApplication,
)
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    ScenarioSpec,
)

HASH = "a" * 64
NOW = datetime.now(UTC)


def _attempt() -> AttemptEnvelope:
    return AttemptEnvelope(
        attempt_id="attempt-one",
        episode_id="episode-one",
        ordinal=1,
        provider_model="model-one",
        provider="provider-one",
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=2,
            max_cost_usd=1.0,
            max_latency_seconds=30.0,
            max_tokens=2048,
            max_tool_calls=4,
            max_context_tokens=8192,
        ),
        provenance=ExecutionProvenance(
            code_revision="abc123",
            code_hash=HASH,
            runtime_image="runtime@sha256:abc",
            runtime_image_hash=HASH,
            environment_hash=HASH,
            prompt_hash=HASH,
            context_hash=HASH,
            tool_hash=HASH,
            source_refs=(
                {"source_uri": "synthetic://source", "content_hash": HASH},
            ),
            captured_at=NOW,
        ),
        request_hash=HASH,
        status="queued",
        queued_at=NOW,
    )


def _scenario() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario-one",
        title="Scenario",
        task_family="fixture",
        prompt="Synthetic fixture prompt.",
    )


def _controls(*, temperature: float = 0.2) -> AttemptExecutionControls:
    return AttemptExecutionControls(
        temperature=temperature,
        top_p=0.9,
        max_output_tokens=512,
        seed=123,
        timeout_seconds=20.0,
        max_tool_calls=4,
        max_context_tokens=8192,
        max_attempts=2,
        source="frozen_experiment",
    )


def test_attempt_input_binding_includes_every_execution_control() -> None:
    first = AttemptInput.bind(_scenario(), _attempt(), execution_controls=_controls())
    second = AttemptInput.bind(
        _scenario(),
        _attempt(),
        execution_controls=_controls(temperature=0.3),
    )

    assert first.execution_controls.temperature == 0.2
    assert first.execution_controls.seed == 123
    assert first.binding_digest != second.binding_digest


def test_legacy_bind_call_uses_an_explicit_compatibility_control_set() -> None:
    bound = AttemptInput.bind(_scenario(), _attempt())

    assert bound.execution_controls.source == "compatibility_default"
    assert bound.execution_controls.max_output_tokens == _attempt().budget.max_tokens
    assert bound.execution_controls.max_tool_calls == _attempt().budget.max_tool_calls
    assert bound.execution_controls.max_context_tokens == _attempt().budget.max_context_tokens
    assert bound.execution_controls.max_attempts == _attempt().budget.max_attempts


def test_attempt_input_rejects_controls_that_escape_the_attempt_budget() -> None:
    with pytest.raises(ValidationError, match="max_output_tokens"):
        AttemptInput.bind(
            _scenario(),
            _attempt(),
            execution_controls=_controls().model_copy(
                update={"max_output_tokens": _attempt().budget.max_tokens + 1}
            ),
        )


def test_applied_control_receipt_is_unique_and_content_addressed() -> None:
    receipt = AppliedControls.bind(
        (
            ControlApplication(
                control_id="temperature",
                status="applied",
                requested_value=0.2,
                observed_value=0.2,
            ),
            ControlApplication(
                control_id="seed",
                status="applied",
                requested_value=123,
                observed_value=123,
            ),
        ),
        provider_request_id="request-one",
    )

    assert receipt.by_id["temperature"].status == "applied"
    assert len(receipt.receipt_digest) == 64

    with pytest.raises(ValidationError, match="receipt_digest"):
        AppliedControls(
            controls=receipt.controls,
            provider_request_id=receipt.provider_request_id,
            receipt_digest="b" * 64,
        )

    with pytest.raises(ValidationError, match="unique"):
        AppliedControls.bind(
            (
                receipt.controls[0],
                receipt.controls[0],
            )
        )


def test_unknown_control_identifier_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ControlApplication(
            control_id="unknown-control",
            status="unsupported",
            requested_value=True,
            detail="not a registered core control",
        )
