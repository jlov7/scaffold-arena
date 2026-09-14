from __future__ import annotations

from datetime import UTC, datetime

import pytest

from adapters_v1 import ArtifactRef, AttemptInput, ResultBundle
from adapters_v1.external import (
    DEEPSEEK_HARNESS_RELEASE,
    PI_RELEASE,
    PRIME_AGENT_RELEASE,
    DeepSeekHarnessAdapter,
    ExternalOciEvidence,
    PiAdapter,
    PrimeAgentAdapter,
    UpstreamRelease,
)
from protocol_v1.canonical import sha256, sha256_bytes
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


def _input() -> AttemptInput:
    attempt = AttemptEnvelope(
        attempt_id="attempt-one", episode_id="episode-one", ordinal=1, provider_model="external", provider="fixture",
        harness_id="harness-one", factor_assignments={}, budget=BudgetSpec(max_attempts=1, max_cost_usd=1, max_latency_seconds=5, max_tokens=10, max_tool_calls=0, max_context_tokens=10),
        provenance=ExecutionProvenance(code_revision="fixture", code_hash=HASH, runtime_image="fixture", runtime_image_hash=HASH, environment_hash=HASH, prompt_hash=HASH, context_hash=HASH, tool_hash=HASH, source_refs=({"source_uri": "fixture://source", "content_hash": HASH},), captured_at=NOW),
        request_hash=HASH, status="queued", queued_at=NOW,
    )
    return AttemptInput.bind(ScenarioSpec(scenario_id="scenario-one", title="Scenario", task_family="fixture", prompt="Synthetic fixture."), attempt)


def _harness(adapter_id: str, digest: str, **updates: object) -> HarnessSpec:
    value: dict[str, object] = {
        "harness_id": "harness-one", "version": "1", "adapter": "cli", "adapter_identity": adapter_id,
        "adapter_digest": digest, "timeout_seconds": 5,
    }
    value.update(updates)
    return HarnessSpec(**value)


class FakeTransport:
    def __init__(self) -> None:
        self.prepared: list[AttemptInput] = []
        self.cancelled = 0
        self.cleaned = 0

    async def healthcheck(self) -> bool:
        return True

    async def prepare(self, input: AttemptInput, *, timeout_seconds: int) -> str:
        assert timeout_seconds == 5
        self.prepared.append(input)
        return "opaque-one"

    async def execute(self, opaque_handle: str) -> ResultBundle:
        assert opaque_handle == "opaque-one"
        output = b"external fixture response"
        return ResultBundle(
            attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
            response_hash=sha256_bytes(output), response_artifact_id="assistant-output",
            artifacts=(ArtifactRef(artifact_id="assistant-output", media_type="text/plain", sha256=sha256_bytes(output), content=output),),
        )

    async def events(self, opaque_handle: str) -> tuple[TraceEvent, ...]:
        assert opaque_handle == "opaque-one"
        return ()

    async def artifacts(self, opaque_handle: str) -> tuple[object, ...]:
        assert opaque_handle == "opaque-one"
        return ()

    async def cancel(self, opaque_handle: str) -> None:
        assert opaque_handle == "opaque-one"
        self.cancelled += 1

    async def cleanup(self, opaque_handle: str) -> None:
        assert opaque_handle == "opaque-one"
        self.cleaned += 1


class FlakyCleanupTransport(FakeTransport):
    async def cancel(self, opaque_handle: str) -> None:
        self.cancelled += 1
        if self.cancelled == 1:
            raise RuntimeError("secret-bearing cancellation detail")

    async def cleanup(self, opaque_handle: str) -> None:
        self.cleaned += 1
        if self.cleaned == 1:
            raise RuntimeError("secret-bearing cleanup detail")


async def _probe(release: UpstreamRelease) -> dict[str, str]:
    return release.identity()


@pytest.mark.asyncio
async def test_pins_health_hash_binding_and_idempotent_cleanup() -> None:
    transport = FakeTransport()
    adapter = PiAdapter(identity_probe=lambda: _probe(PI_RELEASE), transport=transport)
    assert PI_RELEASE.version == "v0.84.2" and PI_RELEASE.commit == "914cf1472e715297caa30db4b9535d534a9eb718"
    assert (await adapter.healthcheck()).healthy
    prepared = await adapter.prepare_attempt(_harness("pi-external", adapter.adapter_digest), _input())
    assert transport.prepared[0].binding_digest == _input().binding_digest
    assert (await adapter.execute_attempt(prepared)).usage is None
    with pytest.raises(ValueError, match="binding"):
        await adapter.execute_attempt(prepared.model_copy(update={"input_digest": HASH}))
    await adapter.cancel_attempt(prepared)
    await adapter.cancel_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    assert (transport.cancelled, transport.cleaned) == (1, 1)


@pytest.mark.asyncio
async def test_mismatched_identity_and_claim_or_isolation_requests_fail_closed() -> None:
    async def wrong_probe() -> dict[str, str]:
        return PI_RELEASE.identity()

    adapter = PrimeAgentAdapter(identity_probe=wrong_probe, transport=FakeTransport())
    assert not (await adapter.healthcheck()).healthy
    with pytest.raises(ValueError, match="unavailable"):
        await adapter.prepare_attempt(_harness("prime-agent-external", adapter.adapter_digest), _input())
    local = PrimeAgentAdapter(identity_probe=lambda: _probe(PRIME_AGENT_RELEASE), transport=FakeTransport())
    eligible = _harness(
        "prime-agent-external", local.adapter_digest, claim_eligibility="live_provider", effective_configuration_hash=sha256({}),
        schema_hashes={"input_hash": HASH, "output_hash": HASH, "trace_hash": HASH, "config_schema_hash": HASH},
    )
    with pytest.raises(ValueError, match="claim eligibility"):
        await local.prepare_attempt(eligible, _input())
    with pytest.raises(ValueError, match="isolation"):
        await local.prepare_attempt(_harness("prime-agent-external", local.adapter_digest, isolation="remote_sandbox"), _input())


@pytest.mark.asyncio
async def test_oci_evidence_is_explicit_and_deepseek_remains_preview_protocol_only() -> None:
    evidence = ExternalOciEvidence(image="registry.example/pi", image_digest="b" * 64, evidence_uri="https://evidence.example/pi", evidence_hash="c" * 64)
    unverified = PiAdapter(identity_probe=lambda: _probe(PI_RELEASE), transport=FakeTransport(), oci_evidence=evidence)
    assert (await unverified.describe_capabilities()).claim_eligibility == "protocol_only"
    assert (await unverified.describe_capabilities()).supported_isolation == ("none", "process")

    async def verify_oci(observed: ExternalOciEvidence) -> bool:
        return observed == evidence

    pi = PiAdapter(
        identity_probe=lambda: _probe(PI_RELEASE), transport=FakeTransport(),
        oci_evidence=evidence, oci_evidence_probe=verify_oci,
    )
    capabilities = await pi.describe_capabilities()
    assert capabilities.supported_isolation == ("remote_sandbox",)
    assert capabilities.claim_eligibility == "live_provider"
    deepseek = DeepSeekHarnessAdapter(
        identity_probe=lambda: _probe(DEEPSEEK_HARNESS_RELEASE), transport=FakeTransport(),
        oci_evidence=evidence, oci_evidence_probe=verify_oci,
    )
    assert (await deepseek.describe_capabilities()).claim_eligibility == "protocol_only"
    preview = _harness(
        "deepseek-harness-external", deepseek.adapter_digest, isolation="remote_sandbox", claim_eligibility="live_provider",
        effective_configuration_hash=sha256({}),
        schema_hashes={"input_hash": HASH, "output_hash": HASH, "trace_hash": HASH, "config_schema_hash": HASH},
    )
    with pytest.raises(ValueError, match="claim eligibility"):
        await deepseek.prepare_attempt(preview, _input())


@pytest.mark.asyncio
async def test_oci_verification_and_cancel_cleanup_failures_retry_instead_of_becoming_silent_success() -> None:
    evidence = ExternalOciEvidence(image="registry.example/pi", image_digest="b" * 64, evidence_uri="https://evidence.example/pi", evidence_hash="c" * 64)

    async def reject_oci(_: ExternalOciEvidence) -> bool:
        return False

    unavailable = PiAdapter(
        identity_probe=lambda: _probe(PI_RELEASE), transport=FakeTransport(),
        oci_evidence=evidence, oci_evidence_probe=reject_oci,
    )
    assert not (await unavailable.healthcheck()).healthy

    transport = FlakyCleanupTransport()
    adapter = PiAdapter(identity_probe=lambda: _probe(PI_RELEASE), transport=transport)
    prepared = await adapter.prepare_attempt(_harness("pi-external", adapter.adapter_digest), _input())
    with pytest.raises(RuntimeError, match="cancellation"):
        await adapter.cancel_attempt(prepared)
    await adapter.cancel_attempt(prepared)
    assert transport.cancelled == 2
    with pytest.raises(RuntimeError, match="cleanup"):
        await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    assert transport.cleaned == 2
