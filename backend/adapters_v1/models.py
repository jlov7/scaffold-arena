"""Dependency-free contracts for trusted Harness adapters.

These models deliberately live outside ``protocol_v1``: they describe an
implementation boundary, while protocol models remain the evidence format.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import (
    AttemptEnvelope,
    HarnessCapabilities,
    ProtocolModel,
    ScenarioSpec,
    TraceEvent,
)

TerminalOutcome = Literal["completed", "failed", "timed_out", "cancelled", "incomplete"]
FailureClassification = Literal[
    "transient_adapter",
    "transient_provider",
    "permanent_adapter",
    "permanent_provider",
    "permanent_protocol",
]


class AttemptInput(ProtocolModel):
    """A hash-bound scenario snapshot; adapters must revalidate its canonical form at their boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    scenario: ScenarioSpec
    attempt: AttemptEnvelope
    scenario_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def verify_binding(self) -> AttemptInput:
        scenario_digest = sha256(self.scenario.model_dump(mode="json"))
        if self.scenario_digest != scenario_digest:
            raise ValueError("scenario_digest does not match canonical scenario")
        binding_digest = sha256({
            "scenario_id": self.scenario.scenario_id,
            "scenario_digest": self.scenario_digest,
            "attempt": self.attempt.model_dump(mode="json"),
        })
        if self.binding_digest != binding_digest:
            raise ValueError("binding_digest does not match scenario and attempt")
        return self

    @classmethod
    def bind(cls, scenario: ScenarioSpec, attempt: AttemptEnvelope) -> AttemptInput:
        scenario = ScenarioSpec.model_validate_json(canonical_json(scenario.model_dump(mode="json")))
        attempt = AttemptEnvelope.model_validate_json(canonical_json(attempt.model_dump(mode="json")))
        scenario_json = scenario.model_dump(mode="json")
        scenario_digest = sha256(scenario_json)
        return cls(
            scenario=scenario,
            attempt=attempt,
            scenario_digest=scenario_digest,
            binding_digest=sha256({
                "scenario_id": scenario.scenario_id,
                "scenario_digest": scenario_digest,
                "attempt": attempt.model_dump(mode="json"),
            }),
        )


class AdapterCapabilities(ProtocolModel):
    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    adapter_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    adapter_kind: Literal["http", "cli", "recorded", "in_process"]
    capabilities: HarnessCapabilities = Field(default_factory=HarnessCapabilities)
    supported_isolation: tuple[Literal["none", "process", "container", "remote_sandbox"], ...]
    claim_eligibility: Literal["fixture_only", "protocol_only", "live_provider", "externally_validated"]
    supports_cancellation: bool = False
    supports_artifacts: bool = False
    config_schema_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class AdapterHealth(ProtocolModel):
    healthy: bool
    checked_at: datetime
    detail: str = Field(min_length=1)


class PreparedAttempt(ProtocolModel):
    attempt_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    prepared_at: datetime
    timeout_seconds: int = Field(ge=1, le=3600)
    opaque_handle: str = Field(min_length=1)
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ArtifactRef(ProtocolModel):
    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    media_type: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    uri: str | None = Field(default=None, min_length=1)
    content: bytes | None = None

    @model_validator(mode="after")
    def verify_inline_content(self) -> ArtifactRef:
        if self.content is not None and sha256_bytes(self.content) != self.sha256:
            raise ValueError("artifact content does not match declared sha256")
        return self


class ProviderUsage(ProtocolModel):
    """Immutable provider-observed usage; omitted fields are unknown, never zero.

    Operator attestations are retained separately and never satisfy an observed
    provider-identity requirement.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    evidence_source: Literal["provider_reported", "fixture_recorded"]
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    context_tokens: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    service_tier: str | None = Field(default=None, min_length=1)
    billing_profile: str | None = Field(default=None, min_length=1)
    tool_billing_usd: float | None = Field(default=None, ge=0.0)
    actual_cost_usd: float | None = Field(default=None, ge=0.0)
    provider_usage_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_provider_version: str | None = Field(default=None, min_length=1)
    observed_endpoint_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    operator_attested_runtime_revision: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_token_consistency(self) -> ProviderUsage:
        if (
            self.total_tokens is not None
            and (self.input_tokens is not None or self.output_tokens is not None)
            and (self.input_tokens is None or self.output_tokens is None or self.total_tokens != self.input_tokens + self.output_tokens)
        ):
            raise ValueError("total_tokens must equal input_tokens plus output_tokens when both are reported")
        return self

    @property
    def complete_evidence(self) -> bool:
        return all(value is not None for value in (
            self.input_tokens, self.output_tokens, self.total_tokens, self.context_tokens,
            self.tool_calls, self.provider_usage_digest, self.observed_provider_version,
            self.observed_endpoint_digest,
        ))

    @property
    def complete_usage(self) -> bool:
        return all(value is not None for value in (
            self.input_tokens, self.output_tokens, self.total_tokens,
            self.context_tokens, self.tool_calls,
        ))


class ResultBundle(ProtocolModel):
    attempt_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    terminal_outcome: TerminalOutcome
    completed_at: datetime
    response_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    response_artifact_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    usage: ProviderUsage | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    detail: str | None = None
    failure_classification: FailureClassification | None = None

    @model_validator(mode="after")
    def bind_response_artifact(self) -> ResultBundle:
        validate_response_artifact_contract(self)
        if self.terminal_outcome == "completed":
            if self.failure_classification is not None:
                raise ValueError("completed result must not declare failure_classification")
        elif self.terminal_outcome == "cancelled":
            if self.failure_classification is not None:
                raise ValueError("cancelled result must not declare failure_classification")
        elif self.failure_classification is None:
            raise ValueError("failed, timed_out, and incomplete results require failure_classification")
        return self


def validate_response_artifact_contract(result: ResultBundle) -> ResultBundle:
    """Require completed results, and validate any declared canonical-output binding."""
    required = result.terminal_outcome == "completed"
    if required and (result.response_hash is None or result.response_artifact_id is None):
        raise ValueError("completed result requires response_hash and response_artifact_id")
    if result.response_artifact_id is None:
        return result
    if result.response_hash is None:
        raise ValueError("response_artifact_id requires response_hash")
    matches = [artifact for artifact in result.artifacts if artifact.artifact_id == result.response_artifact_id]
    if len(matches) != 1:
        raise ValueError("response_artifact_id must identify exactly one artifact")
    artifact = matches[0]
    if artifact.sha256 != result.response_hash:
        raise ValueError("response artifact sha256 does not match response_hash")
    if artifact.content is None and artifact.uri is None:
        raise ValueError("response artifact must provide inline content or a durable URI")
    return result

class CertificationCase(ProtocolModel):
    case: Literal[
        "capability", "input_binding", "lifecycle", "trace", "usage", "artifact", "isolation", "cancellation", "cleanup",
    ]
    passed: bool
    detail: str = Field(min_length=1)


class CertificationReport(ProtocolModel):
    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    adapter_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    certified_at: datetime
    passed: bool
    cases: tuple[CertificationCase, ...]

    @model_validator(mode="after")
    def bind_complete_case_set_and_verdict(self) -> CertificationReport:
        expected = {
            "capability", "input_binding", "lifecycle", "trace", "usage",
            "artifact", "isolation", "cancellation", "cleanup",
        }
        observed = [case.case for case in self.cases]
        if len(observed) != len(expected) or set(observed) != expected:
            raise ValueError("certification requires exactly one result for every case")
        if self.passed != all(case.passed for case in self.cases):
            raise ValueError("certification verdict must equal the conjunction of case results")
        return self


def validate_result_for_attempt(result: ResultBundle, attempt: AttemptEnvelope) -> ResultBundle:
    validate_response_artifact_contract(result)
    if result.attempt_id != attempt.attempt_id:
        raise ValueError("result attempt_id does not match prepared attempt")
    if attempt.response_hash is not None and result.response_hash != attempt.response_hash:
        raise ValueError("result response_hash does not match attempt envelope")
    return result


def validate_events_for_attempt(events: tuple[TraceEvent, ...], attempt: AttemptEnvelope) -> tuple[TraceEvent, ...]:
    previous = -1
    for event in events:
        if event.attempt_id != attempt.attempt_id or event.episode_id != attempt.episode_id:
            raise ValueError("trace event does not belong to attempt")
        if event.sequence <= previous:
            raise ValueError("trace event sequences must be strictly increasing")
        previous = event.sequence
    return events
