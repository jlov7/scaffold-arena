from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from adapters_v1 import AttemptInput
from adapters_v1.lm_studio import (
    LMStudioAdapter,
    lm_studio_endpoint_digest,
    validate_lm_studio_endpoint,
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
MODEL = "google/gemma-4-4b-it"
INSTANCE = "gemma-instance-1"
ENDPOINT = "http://127.0.0.1:1234/api/v1"


def _input(*, prompt: str = "Return a short synthetic response.") -> AttemptInput:
    now = datetime.now(UTC)
    scenario = ScenarioSpec(
        scenario_id="lm-studio-probe",
        title="LM Studio probe",
        task_family="transport",
        prompt=prompt,
        source_label="synthetic",
    )
    attempt = AttemptEnvelope(
        attempt_id="lm-studio-attempt",
        episode_id="lm-studio-episode",
        ordinal=1,
        provider_model=MODEL,
        provider="lm_studio",
        endpoint_id="lm-studio-local",
        pinned_endpoint_digest=lm_studio_endpoint_digest(ENDPOINT),
        harness_id="lm-studio-harness",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=1,
            max_cost_usd=0.0,
            max_latency_seconds=30.0,
            max_tokens=64,
            max_tool_calls=0,
            max_context_tokens=2048,
        ),
        provenance={
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
        },
        request_hash=HASH,
        status="queued",
        queued_at=now,
    )
    return AttemptInput.bind(scenario, attempt)


def _harness(adapter_digest: str, config_schema_hash: str) -> HarnessSpec:
    return HarnessSpec(
        harness_id="lm-studio-harness",
        version="1",
        adapter="http",
        adapter_identity="lm-studio-local",
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


def _models(*, instance: str = INSTANCE, context: int = 4096) -> dict:
    return {
        "models": [
            {
                "type": "llm",
                "publisher": "google",
                "key": MODEL,
                "display_name": "Gemma",
                "architecture": "gemma",
                "quantization": {"name": "Q4_K_M", "bits_per_weight": 4},
                "size_bytes": 2_000_000_000,
                "params_string": "4B",
                "loaded_instances": [
                    {"id": instance, "config": {"context_length": context}}
                ],
                "max_context_length": 8192,
                "format": "gguf",
            }
        ],
    }


def _transport(
    *,
    response: dict | None = None,
    post_instance: str | None = None,
    oversized_path: str | None = None,
) -> tuple[httpx.MockTransport, list[tuple[str, dict | None]]]:
    calls: list[tuple[str, dict | None]] = []
    model_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        if request.url.path == oversized_path:
            return httpx.Response(200, content=b"{" + b" " * (1_048_577))
        payload = None if not request.content else json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == "/api/v1/models":
            model_calls += 1
            return httpx.Response(
                200,
                json=_models(
                    instance=post_instance
                    if model_calls > 1 and post_instance
                    else INSTANCE
                ),
            )
        assert request.url.path == "/api/v1/chat"
        return httpx.Response(
            200,
            json=response
            or {
                "model_instance_id": INSTANCE,
                "output": [{"type": "message", "content": "ok"}],
                "stats": {
                    "input_tokens": 12,
                    "total_output_tokens": 3,
                    "reasoning_output_tokens": 0,
                },
            },
        )

    return httpx.MockTransport(handler), calls


def _adapter(transport: httpx.MockTransport) -> tuple[LMStudioAdapter, str, str]:
    adapter_digest = sha256({"adapter": "lm-studio-test"})
    config_schema_hash = sha256({"schema": "lm-studio-local-v1"})
    return (
        LMStudioAdapter(
        adapter_id="lm-studio-local",
        adapter_digest=adapter_digest,
        endpoint=ENDPOINT,
        runtime_revision="71bd99c",
        model_artifact_digest="b" * 64,
        client=httpx.AsyncClient(transport=transport),
            config_schema_hash=config_schema_hash,
        ),
        adapter_digest,
        config_schema_hash,
    )


def test_endpoint_is_literal_loopback_api_v1_only() -> None:
    assert validate_lm_studio_endpoint(ENDPOINT) == ENDPOINT
    with pytest.raises(ValueError):
        validate_lm_studio_endpoint("http://localhost:1234/api/v1")
    with pytest.raises(ValueError):
        validate_lm_studio_endpoint("http://127.0.0.1:1234/v1")
    with pytest.raises(ValueError):
        validate_lm_studio_endpoint("http://127.0.0.1:1234/api/v1?token=x")


def test_healthcheck_reads_models_without_starting_a_runtime() -> None:
    transport, _ = _transport()
    adapter, _, _ = _adapter(transport)
    assert asyncio.run(adapter.healthcheck()).healthy is True


def test_native_lm_studio_response_holds_without_observed_runtime_version() -> None:
    transport, calls = _transport()
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "incomplete"
    assert result.detail is not None and result.detail.startswith("HOLD:")
    assert result.usage is not None and not result.usage.complete_evidence
    assert result.usage.input_tokens == 12 and result.usage.output_tokens == 3
    assert result.usage.observed_provider_version is None
    assert result.usage.operator_attested_runtime_revision == "71bd99c"
    assert result.applied_controls is not None
    assert result.applied_controls.by_id["seed"].status == "unsupported"
    assert result.applied_controls.by_id["max_context_tokens"].status == "bound"
    request = next(payload for path, payload in calls if path == "/api/v1/chat")
    assert request == {
        "model": MODEL,
        "input": "Return a short synthetic response.",
        "stream": False,
        "store": False,
        "reasoning": "off",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": 64,
    }
    identity = next(item for item in result.artifacts if item.artifact_id == "runtime-identity")
    assert b"operator_owned_native_api_version_unavailable" in (identity.content or b"")
    assert b"operator_owned_native_api_digest_unavailable" in (identity.content or b"")


def test_oversized_prompt_holds_before_chat_request() -> None:
    transport, calls = _transport()
    adapter, digest, schema = _adapter(transport)
    oversized_prompt = "x" * (2048 * 16 + 1)

    async def run():
        prepared = await adapter.prepare_attempt(
            _harness(digest, schema), _input(prompt=oversized_prompt)
        )
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "incomplete"
    assert result.detail is not None and "context byte cap" in result.detail
    assert not any(path == "/api/v1/chat" for path, _ in calls)


def test_operator_attestations_are_required_and_bounded() -> None:
    transport, _ = _transport()
    with pytest.raises(ValueError, match="runtime_revision"):
        LMStudioAdapter(
            adapter_id="lm-studio-local",
            adapter_digest=sha256({"adapter": "lm-studio-test"}),
            endpoint=ENDPOINT,
            runtime_revision="",
            model_artifact_digest="b" * 64,
            client=httpx.AsyncClient(transport=transport),
        )
    with pytest.raises(ValueError, match="model_artifact_digest"):
        LMStudioAdapter(
            adapter_id="lm-studio-local",
            adapter_digest=sha256({"adapter": "lm-studio-test"}),
            endpoint=ENDPOINT,
            runtime_revision="71bd99c",
            model_artifact_digest="not-a-digest",
            client=httpx.AsyncClient(transport=transport),
        )


@pytest.mark.parametrize(
    "response",
    [
        {
            "model_instance_id": INSTANCE,
            "output": [{"type": "reasoning", "content": "private"}],
            "stats": {
                "input_tokens": 1,
                "total_output_tokens": 1,
                "reasoning_output_tokens": 1,
            },
        },
        {
            "model_instance_id": INSTANCE,
            "output": [{"type": "tool_call", "tool": "browser"}],
            "stats": {
                "input_tokens": 1,
                "total_output_tokens": 1,
                "reasoning_output_tokens": 0,
            },
        },
        {
            "model_instance_id": "other-instance",
            "output": [{"type": "message", "content": "ok"}],
            "stats": {
                "input_tokens": 1,
                "total_output_tokens": 1,
                "reasoning_output_tokens": 0,
            },
        },
    ],
)
def test_reasoning_tools_or_instance_mismatch_are_typed_holds(response: dict) -> None:
    transport, _ = _transport(response=response)
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    result = asyncio.run(run())
    assert result.terminal_outcome == "incomplete"
    assert result.detail is not None and result.detail.startswith("HOLD:")


def test_runtime_identity_drift_and_oversized_models_response_hold() -> None:
    transport, _ = _transport(post_instance="gemma-instance-2")
    adapter, digest, schema = _adapter(transport)

    async def run():
        prepared = await adapter.prepare_attempt(_harness(digest, schema), _input())
        return await adapter.execute_attempt(prepared)

    assert asyncio.run(run()).terminal_outcome == "incomplete"

    oversized, _ = _transport(oversized_path="/api/v1/models")
    adapter, digest, schema = _adapter(oversized)
    with pytest.raises(ValueError, match="response exceeds"):
        asyncio.run(adapter.prepare_attempt(_harness(digest, schema), _input()))
