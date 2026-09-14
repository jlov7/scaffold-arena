from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from adapters_v1.models import AttemptInput
from adapters_v1.openai_compatible import (
    OpenAICompatibleAdapter,
    endpoint_digest,
    validate_local_endpoint,
)
from protocol_v1.canonical import sha256_bytes
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    HarnessSpec,
    ScenarioSpec,
)

HASH = "a" * 64
NOW = datetime.now(UTC)
ENDPOINT = "http://127.0.0.1:11434/v1/chat/completions"


def bound_input() -> AttemptInput:
    attempt = AttemptEnvelope(
        attempt_id="attempt-one", episode_id="episode-one", ordinal=1, provider_model="local-model", provider="local",
        endpoint_id="local-endpoint", pinned_endpoint_digest=endpoint_digest(ENDPOINT), harness_id="harness-one", factor_assignments={},
        budget=BudgetSpec(max_attempts=1, max_cost_usd=1.0, max_latency_seconds=5.0, max_tokens=100, max_tool_calls=0, max_context_tokens=100),
        provenance=ExecutionProvenance(code_revision="fixture", code_hash=HASH, runtime_image="fixture", runtime_image_hash=HASH, environment_hash=HASH, prompt_hash=HASH, context_hash=HASH, tool_hash=HASH, source_refs=({"source_uri": "fixture://source", "content_hash": HASH},), captured_at=NOW),
        request_hash=HASH, status="queued", queued_at=NOW,
    )
    return AttemptInput.bind(ScenarioSpec(scenario_id="scenario-one", title="Scenario", task_family="fixture", prompt="Synthetic fixture prompt."), attempt)


def harness() -> HarnessSpec:
    return HarnessSpec(harness_id="harness-one", version="1", adapter="http", adapter_identity="local-one", adapter_digest=HASH, timeout_seconds=5)


def response_body(*, complete: bool = True) -> dict[str, object]:
    usage: dict[str, object] = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    if complete:
        usage.update({"context_tokens": 3, "tool_calls": 0})
    return {"choices": [{"message": {"content": "answer"}}], "usage": usage}


@pytest.mark.asyncio
async def test_local_adapter_requires_pinned_endpoint_complete_usage_and_secret_safe_events() -> None:
    pin = endpoint_digest(ENDPOINT)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=response_body(), headers={"x-scaffold-provider-version": "local-1", "x-scaffold-endpoint-digest": pin, "x-request-id": "req-1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(adapter_id="local-one", adapter_digest=HASH, endpoint=ENDPOINT, headers={"Authorization": "Bearer secret-value"}, client=client)
    prepared = await adapter.prepare_attempt(harness(), bound_input())
    drain = asyncio.create_task(_drain(adapter, prepared))
    assert not drain.done()
    result = await adapter.execute_attempt(prepared)
    assert result.terminal_outcome == "completed"
    assert result.usage is not None and result.usage.complete_evidence
    assert result.usage.actual_cost_usd is None
    assert seen[0].headers["authorization"] == "Bearer secret-value"
    events = await asyncio.wait_for(drain, timeout=1)
    assert [event.sequence for event in events] == [0, 1]
    assert "secret-value" not in str([event.payload for event in events])
    artifacts = await adapter.collect_artifacts(prepared)
    assert {artifact.artifact_id for artifact in artifacts} == {"assistant-output", "provider-response", "provider-usage"}
    assert result.response_artifact_id == "assistant-output"
    assert result.response_hash == sha256_bytes(b"answer")
    assert any(artifact.artifact_id == "assistant-output" and artifact.sha256 == result.response_hash and artifact.content == b"answer" for artifact in artifacts)
    assert any(artifact.artifact_id == "provider-response" and artifact.sha256 != result.response_hash for artifact in artifacts)
    await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_usage_is_incomplete_not_zero_and_endpoint_pin_is_immutable() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_body(complete=False), headers={"x-scaffold-provider-version": "local-1", "x-scaffold-endpoint-digest": endpoint_digest(ENDPOINT)})))
    adapter = OpenAICompatibleAdapter(adapter_id="local-one", adapter_digest=HASH, endpoint=ENDPOINT, client=client)
    prepared = await adapter.prepare_attempt(harness(), bound_input())
    result = await adapter.execute_attempt(prepared)
    assert result.terminal_outcome == "incomplete"
    assert result.usage is not None
    assert result.usage.context_tokens is None
    assert result.usage.tool_calls is None
    assert result.response_artifact_id == "assistant-output"
    assert result.response_hash == sha256_bytes(b"answer")
    assert any(
        artifact.artifact_id == "assistant-output"
        and artifact.sha256 == result.response_hash
        and artifact.content == b"answer"
        for artifact in await adapter.collect_artifacts(prepared)
    )
    wrong = bound_input().attempt.model_copy(update={"pinned_endpoint_digest": "b" * 64})
    with pytest.raises(ValueError, match="endpoint digest"):
        await adapter.prepare_attempt(harness(), AttemptInput.bind(bound_input().scenario, wrong))
    await client.aclose()


@pytest.mark.asyncio
async def test_cancel_before_execution_releases_a_drain_without_calling_provider() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(adapter_id="local-one", adapter_digest=HASH, endpoint=ENDPOINT, client=client)
    prepared = await adapter.prepare_attempt(harness(), bound_input())
    await adapter.cancel_attempt(prepared)
    await adapter.cancel_attempt(prepared)
    result = await adapter.execute_attempt(prepared)
    events = [event async for event in adapter.stream_events(prepared)]
    assert result.terminal_outcome == "cancelled"
    assert calls == 0
    assert events[-1].payload == {"status": "cancelled_before_request"}
    await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    await client.aclose()


@pytest.mark.asyncio
async def test_default_local_adapter_rejects_remote_sandbox_and_live_claims() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    adapter = OpenAICompatibleAdapter(adapter_id="local-one", adapter_digest=HASH, endpoint=ENDPOINT, client=client)
    with pytest.raises(ValueError, match="isolation"):
        await adapter.prepare_attempt(harness().model_copy(update={"execution_mode": "remote", "isolation": "remote_sandbox"}), bound_input())
    with pytest.raises(ValueError, match="claim eligibility"):
        await adapter.prepare_attempt(harness().model_copy(update={"claim_eligibility": "live_provider"}), bound_input())
    await client.aclose()


@pytest.mark.asyncio
async def test_owned_client_disables_environment_proxy_routing() -> None:
    adapter = OpenAICompatibleAdapter(adapter_id="local-one", adapter_digest=HASH, endpoint=ENDPOINT)
    assert adapter._client._trust_env is False
    await adapter.aclose()


def test_local_endpoint_policy_has_no_dns_or_ssrf_escape() -> None:
    assert validate_local_endpoint(ENDPOINT) == ENDPOINT
    for endpoint in ("http://localhost:11434/v1/chat/completions", "http://10.0.0.1/v1/chat/completions", "https://example.test/v1/chat/completions", "http://127.0.0.1:11434/v1/models", "http://user@127.0.0.1/v1/chat/completions"):
        with pytest.raises(ValueError):
            validate_local_endpoint(endpoint)


async def _drain(adapter: OpenAICompatibleAdapter, prepared: object) -> list[object]:
    return [event async for event in adapter.stream_events(prepared)]  # type: ignore[arg-type]
