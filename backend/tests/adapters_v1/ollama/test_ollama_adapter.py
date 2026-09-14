from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from adapters_v1 import AttemptInput
from adapters_v1.ollama import (
    OllamaAdapter,
    ollama_endpoint_digest,
    validate_ollama_endpoint,
)
from protocol_v1.canonical import canonical_configuration_hash, sha256
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    HarnessSchemaHashes,
    HarnessSpec,
    ScenarioSpec,
)

HASH = "a" * 64
MODEL = "qwen3.5:4b"
MODEL_DIGEST = "2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
ENDPOINT = "http://127.0.0.1:11434/api"


def _input(*, model: str = MODEL) -> AttemptInput:
    now = datetime.now(UTC)
    scenario = ScenarioSpec(
        scenario_id="ollama-probe",
        title="Ollama probe",
        task_family="transport",
        prompt="Return a short synthetic response.",
        source_label="synthetic",
    )
    budget = BudgetSpec(
        max_attempts=1,
        max_cost_usd=0.0,
        max_latency_seconds=30.0,
        max_tokens=64,
        max_tool_calls=0,
        max_context_tokens=2048,
    )
    provenance = {
        "code_revision": "test",
        "code_hash": HASH,
        "runtime_image": "test",
        "runtime_image_hash": HASH,
        "environment_hash": HASH,
        "prompt_hash": HASH,
        "context_hash": HASH,
        "tool_hash": HASH,
        "source_refs": ({"source_uri": "synthetic://test", "content_hash": HASH},),
        "captured_at": now,
    }
    attempt = AttemptEnvelope(
        attempt_id="ollama-attempt",
        episode_id="ollama-episode",
        ordinal=1,
        provider_model=model,
        provider="ollama",
        endpoint_id="ollama-local",
        pinned_endpoint_digest=ollama_endpoint_digest(ENDPOINT),
        harness_id="ollama-harness",
        factor_assignments={},
        budget=budget,
        provenance=provenance,
        request_hash=HASH,
        status="queued",
        queued_at=now,
    )
    return AttemptInput.bind(scenario, attempt)


def _harness(adapter_digest: str, config_schema_hash: str) -> HarnessSpec:
    return HarnessSpec(
        harness_id="ollama-harness",
        version="1",
        adapter="http",
        adapter_identity="ollama-local",
        adapter_digest=adapter_digest,
        timeout_seconds=30,
        configuration={},
        effective_configuration_hash=canonical_configuration_hash({}),
        schema_hashes=HarnessSchemaHashes(
            input_hash=HASH,
            output_hash=HASH,
            trace_hash=HASH,
            config_schema_hash=config_schema_hash,
        ),
        execution_mode="local",
        isolation="none",
        claim_eligibility="live_provider",
    )


def _transport(
    *,
    response: dict | None = None,
    tags_digest: str = MODEL_DIGEST,
    post_tags_digest: str | None = None,
    post_version: str | None = None,
    oversized_path: str | None = None,
):
    calls: list[tuple[str, dict | None]] = []
    counts = {"tags": 0, "version": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == oversized_path:
            return httpx.Response(200, content=b"{" + b" " * (1_048_577))
        payload = (
            None if not request.content else __import__("json").loads(request.content)
        )
        calls.append((request.url.path, payload))
        if request.url.path == "/api/version":
            counts["version"] += 1
            version = post_version if counts["version"] > 1 and post_version else "0.12.6"
            return httpx.Response(200, json={"version": version})
        if request.url.path == "/api/tags":
            counts["tags"] += 1
            digest = (
                post_tags_digest
                if counts["tags"] > 1 and post_tags_digest is not None
                else tags_digest
            )
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": MODEL,
                            "model": MODEL,
                            "digest": digest,
                            "details": {"context_length": 4096},
                        }
                    ]
                },
            )
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            json=response
            or {
                "model": MODEL,
                "created_at": "2026-08-19T00:00:00Z",
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 3,
            },
        )

    return httpx.MockTransport(handler), calls


def _adapter(transport: httpx.MockTransport) -> tuple[OllamaAdapter, str, str]:
    adapter_digest = sha256({"adapter": "ollama-test"})
    config_schema_hash = sha256({"schema": "ollama-local-v1"})
    return (
        OllamaAdapter(
            adapter_id="ollama-local",
            adapter_digest=adapter_digest,
            endpoint=ENDPOINT,
            client=httpx.AsyncClient(transport=transport),
            config_schema_hash=config_schema_hash,
        ),
        adapter_digest,
        config_schema_hash,
    )


def test_endpoint_is_literal_loopback_api_base_only() -> None:
    assert validate_ollama_endpoint(ENDPOINT) == ENDPOINT
    with pytest.raises(ValueError):
        validate_ollama_endpoint("http://localhost:11434/api")
    with pytest.raises(ValueError):
        validate_ollama_endpoint("http://127.0.0.1:11434/api/tags")
    with pytest.raises(ValueError):
        validate_ollama_endpoint("http://127.0.0.1:11434/api?token=x")


def test_healthcheck_verifies_the_running_endpoint_without_claiming_cancellation() -> None:
    transport, _ = _transport()
    adapter, _, _ = _adapter(transport)
    assert asyncio.run(adapter.healthcheck()).healthy is True
    assert asyncio.run(adapter.describe_capabilities()).supports_cancellation is False
    assert asyncio.run(adapter.describe_capabilities()).capabilities.usage is True

    async def unavailable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    offline, _, _ = _adapter(httpx.MockTransport(unavailable))
    assert asyncio.run(offline.healthcheck()).healthy is False


def test_native_ollama_response_binds_identity_controls_and_complete_usage() -> None:
    transport, calls = _transport()
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "completed"
    assert result.usage is not None and result.usage.complete_evidence
    assert result.usage.input_tokens == 12 and result.usage.output_tokens == 3
    assert result.usage.context_tokens == 12 and result.usage.tool_calls == 0
    assert result.applied_controls is not None
    request = next(payload for path, payload in calls if path == "/api/chat")
    assert request["stream"] is False
    assert request["think"] is False
    assert request["options"] == {
        "temperature": 0.0,
        "top_p": 1.0,
        "num_predict": 64,
        "seed": 0,
        "num_ctx": 2048,
    }
    assert any(item.artifact_id == "runtime-identity" for item in result.artifacts)


def test_thinking_is_never_persisted_in_artifacts_or_events() -> None:
    response = {
        "model": MODEL,
        "message": {
            "role": "assistant",
            "content": "ok",
            "thinking": "private chain of thought",
            "reasoning": "private reasoning",
            "analysis": "private analysis",
            "thoughts": "private thoughts",
            "chain_of_thought": "private chain",
            "unknown_nested": {"private": "must not persist"},
        },
        "thinking": "private top-level thought",
        "analysis": "private top-level analysis",
        "unknown_top_level": {"private": "must not persist"},
        "done": True,
        "prompt_eval_count": 12,
        "eval_count": 3,
    }
    transport, _ = _transport(response=response)
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        result = await adapter.execute_attempt(prepared)
        events = [event.model_dump(mode="json") async for event in adapter.stream_events(prepared)]
        return result, events

    result, events = asyncio.run(run())
    assert result.terminal_outcome == "completed"
    persisted = b"".join(
        artifact.content or b"" for artifact in result.artifacts
    ) + __import__("json").dumps(events).encode()
    for marker in (b"thinking", b"reasoning", b"analysis", b"thoughts", b"chain_of_thought", b"unknown_nested", b"unknown_top_level"):
        assert marker not in persisted.lower()
    summary = next(item for item in result.artifacts if item.artifact_id == "provider-response-summary")
    assert b"raw_response_sha256" in (summary.content or b"")


def test_cleanup_removes_all_attempt_content_and_is_idempotent() -> None:
    transport, _ = _transport()
    adapter, digest, schema = _adapter(transport)

    async def run() -> None:
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        result = await adapter.execute_attempt(prepared)
        assert result.terminal_outcome == "completed"
        assert await adapter.collect_artifacts(prepared)
        await adapter.cleanup_attempt(prepared)
        await adapter.cleanup_attempt(prepared)
        with pytest.raises(ValueError, match="not owned"):
            await adapter.collect_artifacts(prepared)

    asyncio.run(run())
    assert not adapter._attempts
    assert not adapter._events
    assert not adapter._results
    assert not adapter._artifacts
    assert not adapter._ready
    assert not adapter._cancelled


@pytest.mark.parametrize("oversized_path", ["/api/version", "/api/tags"])
def test_oversized_runtime_identity_response_fails_before_parsing(oversized_path: str) -> None:
    transport, _ = _transport(oversized_path=oversized_path)
    adapter, digest, schema = _adapter(transport)

    with pytest.raises(ValueError, match="response exceeds"):
        asyncio.run(adapter.prepare_attempt(_harness(digest, schema), _input()))


def test_oversized_chat_response_fails_closed() -> None:
    transport, _ = _transport(oversized_path="/api/chat")
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "incomplete"
    assert "response exceeds" in (result.detail or "")


@pytest.mark.parametrize(
    "response",
    [
        {
            "model": MODEL,
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
            "prompt_eval_count": 1,
        },
        {
            "model": "other:model",
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
            "prompt_eval_count": 1,
            "eval_count": 1,
        },
        {
            "model": MODEL,
            "message": {
                "role": "assistant",
                "content": "ok",
                "tool_calls": [{"function": {}}],
            },
            "done": True,
            "prompt_eval_count": 1,
            "eval_count": 1,
        },
    ],
)
def test_missing_or_spoofed_native_evidence_fails_closed(response: dict) -> None:
    transport, _ = _transport(response=response)
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "incomplete"
    assert result.failure_classification == "permanent_protocol"


def test_model_digest_drift_after_request_fails_closed() -> None:
    transport, _ = _transport(post_tags_digest="b" * 64)
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "incomplete"
    assert "runtime identity" in (result.detail or "")


def test_runtime_version_drift_after_request_fails_closed() -> None:
    transport, _ = _transport(post_version="0.32.15")
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "incomplete"
    assert "runtime identity" in (result.detail or "")
