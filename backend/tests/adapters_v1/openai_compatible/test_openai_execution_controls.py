from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from adapters_v1 import AttemptExecutionControls, AttemptInput
from adapters_v1.openai_compatible import OpenAICompatibleAdapter, endpoint_digest
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


def _input() -> AttemptInput:
    attempt = AttemptEnvelope(
        attempt_id="attempt-one",
        episode_id="episode-one",
        ordinal=1,
        provider_model="local-model",
        provider="local",
        endpoint_id="local-endpoint",
        pinned_endpoint_digest=endpoint_digest(ENDPOINT),
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=2,
            max_cost_usd=1.0,
            max_latency_seconds=17.0,
            max_tokens=1024,
            max_tool_calls=3,
            max_context_tokens=4096,
        ),
        provenance=ExecutionProvenance(
            code_revision="fixture",
            code_hash=HASH,
            runtime_image="fixture",
            runtime_image_hash=HASH,
            environment_hash=HASH,
            prompt_hash=HASH,
            context_hash=HASH,
            tool_hash=HASH,
            source_refs=(
                {"source_uri": "fixture://source", "content_hash": HASH},
            ),
            captured_at=NOW,
        ),
        request_hash=HASH,
        status="queued",
        queued_at=NOW,
    )
    controls = AttemptExecutionControls(
        temperature=0.25,
        top_p=0.88,
        max_output_tokens=321,
        seed=2468,
        timeout_seconds=13.0,
        max_tool_calls=3,
        max_context_tokens=4096,
        max_attempts=2,
        source="frozen_experiment",
    )
    return AttemptInput.bind(
        ScenarioSpec(
            scenario_id="scenario-one",
            title="Scenario",
            task_family="fixture",
            prompt="Synthetic fixture prompt.",
        ),
        attempt,
        execution_controls=controls,
    )


def _harness() -> HarnessSpec:
    return HarnessSpec(
        harness_id="harness-one",
        version="1",
        adapter="http",
        adapter_identity="local-one",
        adapter_digest=HASH,
        timeout_seconds=13,
    )


@pytest.mark.asyncio
async def test_local_adapter_applies_frozen_generation_controls_and_attests_them() -> None:
    captured: list[dict[str, object]] = []
    pin = endpoint_digest(ENDPOINT)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "answer"}}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                    "context_tokens": 3,
                    "tool_calls": 0,
                },
            },
            headers={
                "x-scaffold-provider-version": "local-1",
                "x-scaffold-endpoint-digest": pin,
                "x-request-id": "provider-request-one",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(
        adapter_id="local-one",
        adapter_digest=HASH,
        endpoint=ENDPOINT,
        headers={"Authorization": "Bearer secret-value"},
        client=client,
    )

    prepared = await adapter.prepare_attempt(_harness(), _input())
    result = await adapter.execute_attempt(prepared)

    assert captured == [
        {
            "model": "local-model",
            "messages": [
                {"role": "user", "content": "Synthetic fixture prompt."},
            ],
            "stream": False,
            "temperature": 0.25,
            "top_p": 0.88,
            "max_tokens": 321,
            "seed": 2468,
        }
    ]
    assert result.applied_controls is not None
    assert result.applied_controls.provider_request_id == "provider-request-one"
    assert result.applied_controls.by_id["temperature"].status == "applied"
    assert result.applied_controls.by_id["seed"].observed_value == 2468
    assert result.applied_controls.by_id["timeout_seconds"].status == "bound"
    assert "secret-value" not in result.applied_controls.model_dump_json()

    await adapter.cleanup_attempt(prepared)
    await client.aclose()
