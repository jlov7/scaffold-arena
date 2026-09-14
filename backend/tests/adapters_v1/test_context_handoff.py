from __future__ import annotations

import asyncio

import httpx
import pytest

from adapters_v1.context_handoff import ContextHandoffOllamaAdapter, ContextPacket
from adapters_v1.context_handoff.adapter import CONTEXT_HANDOFF_ADAPTER_DIGEST, CONTEXT_HANDOFF_CONFIG_SCHEMA_HASH
from adapters_v1.context_handoff.models import EXPECTED_MODEL_DIGEST
from adapters_v1.context_handoff.render import RENDERER_DIGEST, render_context
from protocol_v1.canonical import canonical_configuration_hash, sha256
from protocol_v1.models import AttemptEnvelope, BudgetSpec, HarnessSchemaHashes, HarnessSpec, ScenarioSpec
from execution_v1.pricing import CentralPriceResolver


ENDPOINT = "http://127.0.0.1:11434/api"


def packet() -> ContextPacket:
    return ContextPacket.model_validate({"baseline": "Current answer is hold.", "segments": (
        {"segment_id": "help", "source_id": "packet-help", "text": "Use provenance receipt.", "content_hash": sha256({"segment_id": "help", "source_id": "packet-help", "text": "Use provenance receipt."})},
        {"segment_id": "noise", "source_id": "packet-noise", "text": "STALE: answer pass.", "content_hash": sha256({"segment_id": "noise", "source_id": "packet-noise", "text": "STALE: answer pass."})},
    ), "curated_segment_ids": ("help",)})


def test_renderer_is_pure_and_policy_receipt_is_complete() -> None:
    rendered, receipt = render_context(task="Return JSON.", packet=packet(), policy="curated")
    assert "Use provenance receipt." in rendered and "STALE" not in rendered
    assert receipt.renderer_digest == RENDERER_DIGEST
    assert receipt.included_segment_ids == ("help",)
    assert receipt.excluded_segment_ids == ("noise",)
    with pytest.raises(ValueError):
        ContextPacket.model_validate({**packet().model_dump(mode="json"), "curated_segment_ids": ("missing",)})


def _input():
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    scenario = ScenarioSpec(scenario_id="context-case", title="Context", task_family="synthetic", prompt="Return JSON.", source_label="synthetic", extensions={"org.scaffold-arena.context-handoff-v1": {"packet": packet().model_dump(mode="json"), "runtime": {"model": "qwen3.5:4b", "model_digest": EXPECTED_MODEL_DIGEST, "ollama_version": "0.34.0"}}})
    attempt = AttemptEnvelope(attempt_id="context-attempt", episode_id="context-episode", ordinal=1, provider="ollama", provider_model="qwen3.5:4b", endpoint_id="local", pinned_endpoint_digest=sha256({"ollama_local_endpoint": ENDPOINT}), harness_id="context-harness", factor_assignments={"context_policy": "curated"}, budget=BudgetSpec(max_attempts=1, max_cost_usd=0, max_latency_seconds=180, max_tokens=256, max_tool_calls=0, max_context_tokens=4096), provenance={"code_revision":"x","code_hash":"a"*64,"runtime_image":"x","runtime_image_hash":"a"*64,"environment_hash":"a"*64,"prompt_hash":"a"*64,"context_hash":"a"*64,"tool_hash":"a"*64,"source_refs":({"source_uri":"synthetic://case","content_hash":"a"*64},),"captured_at":now}, request_hash="a"*64, status="queued", queued_at=now)
    from adapters_v1 import AttemptInput
    return AttemptInput.bind(scenario, attempt)


def _harness() -> HarnessSpec:
    return HarnessSpec(harness_id="context-harness", version="1", adapter="http", adapter_identity="context-handoff-ollama", adapter_digest=CONTEXT_HANDOFF_ADAPTER_DIGEST, timeout_seconds=180, configuration={}, effective_configuration_hash=canonical_configuration_hash({}), schema_hashes=HarnessSchemaHashes(input_hash="a"*64, output_hash="a"*64, trace_hash="a"*64, config_schema_hash=CONTEXT_HANDOFF_CONFIG_SCHEMA_HASH), execution_mode="local", isolation="none", claim_eligibility="live_provider")


def _transport(*, digest: str = EXPECTED_MODEL_DIGEST, version: str = "0.34.0"):
    async def handler(request: httpx.Request):
        if request.url.path == "/api/version": return httpx.Response(200, json={"version": version})
        if request.url.path == "/api/tags": return httpx.Response(200, json={"models":[{"name":"qwen3.5:4b","model":"qwen3.5:4b","digest":digest,"details":{"context_length":262144}}]})
        return httpx.Response(200, json={"model":"qwen3.5:4b","message":{"role":"assistant","content":"{\"answer\":\"hold\",\"evidence\":\"receipt\"}"},"done":True,"prompt_eval_count":12,"eval_count":3})
    return httpx.MockTransport(handler)


def test_adapter_binds_own_digest_and_checks_expected_runtime_identity() -> None:
    adapter = ContextHandoffOllamaAdapter(endpoint=ENDPOINT, client=httpx.AsyncClient(transport=_transport()))
    async def run():
        prepared = await adapter.prepare_attempt(_harness(), _input())
        return await adapter.execute_attempt(prepared), prepared
    result, prepared = asyncio.run(run())
    assert result.terminal_outcome == "completed"
    assert result.usage is not None and result.usage.cached_input_tokens is None
    assert result.usage.billing_profile == "local_zero_paid_context_handoff"
    assert CentralPriceResolver().resolve(provider="ollama", model_id="qwen3.5:4b", usage=result.usage).cost_usd == 0.0
    assert {item.artifact_id for item in result.artifacts} >= {"context-renderer-receipt", "rendered-context-prompt"}
    assert any(event.event_type == "state" for event in asyncio.run(_events(adapter, prepared)))


async def _events(adapter, prepared):
    return [event async for event in adapter.stream_events(prepared)]


def test_adapter_holds_on_expected_digest_or_runtime_mismatch() -> None:
    for kwargs in ({"digest": "b" * 64}, {"version": "0.33.0"}):
        adapter = ContextHandoffOllamaAdapter(endpoint=ENDPOINT, client=httpx.AsyncClient(transport=_transport(**kwargs)))
        async def run():
            return await adapter.prepare_attempt(_harness(), _input())
        with pytest.raises(ValueError):
            asyncio.run(run())
