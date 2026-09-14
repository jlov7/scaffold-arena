from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from adapters_v1 import (
    AttemptInput,
    LMStudioAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
)
from config.settings import Settings
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    HarnessSpec,
    ScenarioSpec,
)
from services_v1 import (
    ProtocolRuntimeConfigurationError,
    build_adapter_registry_from_config,
    initialize_protocol_registry,
    register_current_scaffold_components,
)

HASH = "a" * 64


@pytest.mark.asyncio
async def test_api_runtime_initializes_native_adapter_without_constructing_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "adapter-runtime.json"
    config.write_text(json.dumps({
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{"kind": "native_current_scaffold", "adapter_id": "native-one", "adapter_digest": HASH, "scaffold_id": "bare"}],
    }))
    import core.provider

    monkeypatch.setattr(core.provider, "get_provider", lambda _model_id: pytest.fail("API startup must not instantiate a provider"))
    runtime = await initialize_protocol_registry(Settings(
        protocol_v1_database_url=f"sqlite:///{tmp_path / 'arena.db'}",
        protocol_v1_artifact_root=str(tmp_path / "artifacts"),
        protocol_v1_adapter_runtime_config=str(config),
    ))
    try:
        assert runtime.adapter_registry is not None
        assert runtime.adapter_registry.get("native-one", HASH)
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_explicit_runtime_factory_installs_only_literal_loopback_adapter() -> None:
    config = {
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{
            "kind": "openai_compatible_local",
            "adapter_id": "local-one",
            "adapter_digest": HASH,
            "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
        }],
    }
    registry = await build_adapter_registry_from_config(config)
    adapter = registry.get("local-one", HASH)
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert registry.capabilities("local-one", HASH).claim_eligibility == "protocol_only"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_explicit_runtime_factory_installs_native_ollama_adapter() -> None:
    config = {
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{
            "kind": "ollama_local", "adapter_id": "ollama-one", "adapter_digest": HASH,
            "endpoint": "http://127.0.0.1:11434/api",
        }],
    }
    registry = await build_adapter_registry_from_config(config)
    adapter = registry.get("ollama-one", HASH)
    assert isinstance(adapter, OllamaAdapter)
    assert registry.capabilities("ollama-one", HASH).claim_eligibility == "live_provider"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_explicit_runtime_factory_installs_native_lm_studio_adapter() -> None:
    config = {
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{
            "kind": "lm_studio_local", "adapter_id": "lm-studio-one", "adapter_digest": HASH,
            "endpoint": "http://127.0.0.1:1234/api/v1", "runtime_revision": "71bd99c", "model_artifact_digest": "b" * 64,
        }],
    }
    registry = await build_adapter_registry_from_config(config)
    adapter = registry.get("lm-studio-one", HASH)
    assert isinstance(adapter, LMStudioAdapter)
    assert registry.capabilities("lm-studio-one", HASH).claim_eligibility == "live_provider"
    await adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [
    {"kind": "lm_studio_local", "adapter_id": "lm-studio-one", "adapter_digest": HASH, "endpoint": "http://127.0.0.1:1234/api/v1"},
    {"kind": "lm_studio_local", "adapter_id": "lm-studio-one", "adapter_digest": HASH, "endpoint": "http://127.0.0.1:1234/api/v1", "runtime_revision": "", "model_artifact_digest": "b" * 64},
    {"kind": "lm_studio_local", "adapter_id": "lm-studio-one", "adapter_digest": HASH, "endpoint": "http://127.0.0.1:1234/api/v1", "runtime_revision": "71bd99c"},
    {"kind": "lm_studio_local", "adapter_id": "lm-studio-one", "adapter_digest": HASH, "endpoint": "http://127.0.0.1:1234/api/v1", "runtime_revision": "71bd99c", "model_artifact_digest": "not-a-digest"},
])
async def test_lm_studio_runtime_config_requires_operator_attestations(entry: dict[str, str]) -> None:
    with pytest.raises((ProtocolRuntimeConfigurationError, ValueError), match="runtime_revision|model_artifact_digest|keys"):
        await build_adapter_registry_from_config({"format": "scaffold-arena-adapter-runtime-v1", "adapters": [entry]})


@pytest.mark.asyncio
async def test_runtime_factory_rejects_remote_endpoint_and_uninjected_native_runtime() -> None:
    remote = {
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{
            "kind": "openai_compatible_local",
            "adapter_id": "local-one",
            "adapter_digest": HASH,
            "endpoint": "https://example.test/v1/chat/completions",
        }],
    }
    with pytest.raises(ValueError, match="loopback"):
        await build_adapter_registry_from_config(remote)

    native = {
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{
            "kind": "native_current_scaffold",
            "adapter_id": "native-one",
            "adapter_digest": HASH,
            "runtime_ref": "current",
        }],
    }
    with pytest.raises(ProtocolRuntimeConfigurationError, match="explicitly injected"):
        await build_adapter_registry_from_config(native)


@pytest.mark.asyncio
async def test_shipped_native_runtime_defers_provider_and_binds_the_frozen_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class ProbeScaffold:
        id = "bare"

        async def run(self, *, task, provider, options, **_kwargs):
            observed["task_input"] = task.get_input_text()
            observed["schema"] = task.get_schema()
            observed["gold"] = task.get_gold()
            observed["provider"] = provider
            observed["options"] = options
            yield "usage", {"input_tokens": 2, "output_tokens": 3}
            yield "final_output", {"output": "fixture answer"}

    register_current_scaffold_components()
    import core.provider
    import core.registry

    monkeypatch.setitem(core.registry._scaffolds, "bare", ProbeScaffold())
    provider = object()
    calls: list[str] = []
    monkeypatch.setattr(core.provider, "get_provider", lambda model_id: calls.append(model_id) or provider)
    config = {
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{
            "kind": "native_current_scaffold",
            "adapter_id": "native-one",
            "adapter_digest": HASH,
            "scaffold_id": "bare",
        }],
    }
    registry = await build_adapter_registry_from_config(config)
    adapter = registry.get("native-one", HASH)
    assert calls == []
    assert (await adapter.healthcheck()).healthy
    assert calls == []

    now = datetime.now(UTC)
    scenario = ScenarioSpec(
        scenario_id="scenario-one", title="Synthetic", task_family="fixture", prompt="Synthetic prompt.",
        source_label="synthetic", output_contract={"schema_hash": HASH, "format": "json", "description": "Return fixture JSON."},
        reference_solution={"reference_id": "reference-one", "artifact_hash": HASH, "solvability_proof": "fixture proof"},
    )
    attempt = AttemptEnvelope(
        attempt_id="attempt-one", episode_id="episode-one", ordinal=1, provider_model="gpt-4.1", provider="openai",
        harness_id="harness-one", factor_assignments={},
        budget=BudgetSpec(max_attempts=1, max_cost_usd=1, max_latency_seconds=3, max_tokens=7, max_tool_calls=0, max_context_tokens=10),
        provenance=ExecutionProvenance(code_revision="fixture", code_hash=HASH, runtime_image="fixture", runtime_image_hash=HASH, environment_hash=HASH, prompt_hash=HASH, context_hash=HASH, tool_hash=HASH, source_refs=({"source_uri": "fixture://source", "content_hash": HASH},), captured_at=now),
        request_hash=HASH, status="queued", queued_at=now,
    )
    prepared = await adapter.prepare_attempt(HarnessSpec(harness_id="harness-one", version="1", adapter="in_process", adapter_identity="native-one", adapter_digest=HASH, timeout_seconds=3), AttemptInput.bind(scenario, attempt))
    assert calls == []
    assert (await adapter.execute_attempt(prepared)).terminal_outcome == "incomplete"
    assert calls == ["gpt-4.1"]
    assert "SOURCE LABEL: SYNTHETIC" in observed["task_input"]
    assert observed["schema"]["type"] == "object"
    assert observed["gold"]["artifact_hash"] == HASH
    assert observed["provider"] is provider
    assert observed["options"].max_output_tokens == 7
    assert observed["options"].timeout_s == 3
