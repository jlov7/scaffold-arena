from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from adapters_v1 import ArtifactRef, CertificationReport, RecordedAdapter, ResultBundle
from adapters_v1.certification import certify_adapter
from adapters_v1.models import AttemptInput, CertificationCase
from protocol_v1.canonical import sha256_bytes
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    HarnessSpec,
    ScenarioSpec,
    TraceEvent,
)

HASH = "a" * 64
NOW = datetime.now(UTC)


def bound_input() -> AttemptInput:
    attempt = AttemptEnvelope(
        attempt_id="attempt-one", episode_id="episode-one", ordinal=1, provider_model="recorded", provider="fixture", harness_id="harness-one", factor_assignments={},
        budget=BudgetSpec(max_attempts=1, max_cost_usd=1.0, max_latency_seconds=5.0, max_tokens=10, max_tool_calls=0, max_context_tokens=10),
        provenance=ExecutionProvenance(code_revision="fixture", code_hash=HASH, runtime_image="fixture", runtime_image_hash=HASH, environment_hash=HASH, prompt_hash=HASH, context_hash=HASH, tool_hash=HASH, source_refs=({"source_uri": "fixture://source", "content_hash": HASH},), captured_at=NOW),
        request_hash=HASH, status="queued", queued_at=NOW,
    )
    return AttemptInput.bind(ScenarioSpec(scenario_id="scenario-one", title="Scenario", task_family="fixture", prompt="Synthetic fixture prompt."), attempt)


def harness() -> HarnessSpec:
    return HarnessSpec(harness_id="harness-one", version="1", adapter="recorded", adapter_identity="recorded-one", adapter_digest=HASH, timeout_seconds=5)


def completed_result() -> ResultBundle:
    output = b"fixture response"
    return ResultBundle(
        attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
        response_hash=sha256_bytes(output), response_artifact_id="assistant-output",
        artifacts=(ArtifactRef(artifact_id="assistant-output", media_type="text/plain", sha256=sha256_bytes(output), content=output),),
    )


@pytest.mark.asyncio
async def test_certification_preserves_fixture_boundary_and_rejects_mutation_probes() -> None:
    event = TraceEvent(trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0, actor="harness", event_type="request", timestamp=NOW, monotonic_time=0, payload={}, payload_hash=HASH)
    adapter = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": completed_result()}, events={"attempt-one": (event,)})
    report = await certify_adapter(adapter, harness(), bound_input())
    assert report.passed
    assert {case.case for case in report.cases} == {"capability", "input_binding", "lifecycle", "trace", "usage", "artifact", "isolation", "cancellation", "cleanup"}


def test_certification_report_refuses_incomplete_cases_or_self_asserted_verdict() -> None:
    cases = (
        CertificationCase(case="capability", passed=True, detail="fixture"),
        CertificationCase(case="input_binding", passed=True, detail="fixture"),
        CertificationCase(case="lifecycle", passed=True, detail="fixture"),
        CertificationCase(case="trace", passed=True, detail="fixture"),
        CertificationCase(case="usage", passed=True, detail="fixture"),
        CertificationCase(case="artifact", passed=True, detail="fixture"),
        CertificationCase(case="isolation", passed=True, detail="fixture"),
        CertificationCase(case="cancellation", passed=True, detail="fixture"),
        CertificationCase(case="cleanup", passed=False, detail="fixture"),
    )
    with pytest.raises(ValidationError, match="verdict"):
        CertificationReport(adapter_id="recorded-one", adapter_digest=HASH, certified_at=NOW, passed=True, cases=cases)
    with pytest.raises(ValidationError, match="exactly one"):
        CertificationReport(adapter_id="recorded-one", adapter_digest=HASH, certified_at=NOW, passed=False, cases=cases[:-1])


@pytest.mark.asyncio
async def test_certification_rejects_nonmonotonic_trace_and_does_not_upgrade_it() -> None:
    event = TraceEvent(trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=1, actor="model", event_type="response", timestamp=NOW, monotonic_time=0, payload={}, payload_hash=HASH)
    second = event.model_copy(update={"sequence": 0})
    adapter = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": completed_result()}, events={"attempt-one": (event, second)})
    report = await certify_adapter(adapter, harness(), bound_input())
    assert not report.passed
    assert any(case.case == "trace" and not case.passed for case in report.cases)


@pytest.mark.asyncio
async def test_certification_rejects_zero_event_trace_false_sandbox_and_artifact_mismatch() -> None:
    empty = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": completed_result()})
    empty_report = await certify_adapter(empty, harness(), bound_input())
    assert any(case.case == "trace" and not case.passed for case in empty_report.cases)

    event = TraceEvent(trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0, actor="harness", event_type="request", timestamp=NOW, monotonic_time=0, payload={}, payload_hash=HASH)
    unsafe = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": completed_result()}, events={"attempt-one": (event,)})
    unsafe._capabilities = unsafe._capabilities.model_copy(update={"claim_eligibility": "live_provider", "capabilities": unsafe._capabilities.capabilities.model_copy(update={"state": True})})
    unsafe_report = await certify_adapter(unsafe, harness(), bound_input())
    assert any(case.case == "isolation" and not case.passed for case in unsafe_report.cases)

    secret = b"Authorization: Bearer private-fixture-secret"
    mismatched = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": completed_result()}, events={"attempt-one": (event,)}, artifacts={"attempt-one": (ArtifactRef(artifact_id="bad-artifact", media_type="text/plain", sha256=sha256_bytes(secret), content=secret),)})
    mismatch_report = await certify_adapter(mismatched, harness(), bound_input())
    assert any(case.case == "artifact" and not case.passed for case in mismatch_report.cases)


class _UnboundRecordedAdapter(RecordedAdapter):
    async def execute_attempt(self, prepared: object) -> ResultBundle:
        return ResultBundle.model_construct(attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW, response_hash=None, response_artifact_id=None, artifacts=())


class _SecretFailureRecordedAdapter(RecordedAdapter):
    async def execute_attempt(self, prepared: object) -> ResultBundle:
        raise ValueError("Authorization: Bearer private-fixture-secret")


class _ContractBypassRecordedAdapter(RecordedAdapter):
    def __init__(self, *, forged: ResultBundle, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._forged = forged

    async def execute_attempt(self, prepared: object) -> ResultBundle:
        return self._forged


@pytest.mark.asyncio
async def test_certification_rejects_hash_bypass_and_redacts_secret_exceptions() -> None:
    event = TraceEvent(trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0, actor="harness", event_type="request", timestamp=NOW, monotonic_time=0, payload={}, payload_hash=HASH)
    unbound = _UnboundRecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": completed_result()}, events={"attempt-one": (event,)})
    report = await certify_adapter(unbound, harness(), bound_input())
    assert any(case.case == "input_binding" and not case.passed for case in report.cases)

    secret = _SecretFailureRecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": completed_result()}, events={"attempt-one": (event,)})
    secret_report = await certify_adapter(secret, harness(), bound_input())
    details = " ".join(case.detail for case in secret_report.cases)
    assert "private-fixture-secret" not in details
    assert "adapter_error:ValueError" in details


@pytest.mark.asyncio
async def test_certification_rejects_missing_duplicate_and_mismatched_response_artifacts() -> None:
    event = TraceEvent(trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0, actor="harness", event_type="request", timestamp=NOW, monotonic_time=0, payload={}, payload_hash=HASH)
    valid = completed_result()
    artifact = valid.artifacts[0]
    forged = (
        ResultBundle.model_construct(attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW, response_hash=None, response_artifact_id=None, artifacts=()),
        ResultBundle.model_construct(attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW, response_hash=artifact.sha256, response_artifact_id=artifact.artifact_id, artifacts=(artifact, artifact)),
        ResultBundle.model_construct(attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW, response_hash=HASH, response_artifact_id=artifact.artifact_id, artifacts=(artifact,)),
    )
    for value in forged:
        adapter = _ContractBypassRecordedAdapter(
            adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": valid},
            events={"attempt-one": (event,)}, forged=value,
        )
        report = await certify_adapter(adapter, harness(), bound_input())
        assert any(case.case == "artifact" and not case.passed for case in report.cases)
