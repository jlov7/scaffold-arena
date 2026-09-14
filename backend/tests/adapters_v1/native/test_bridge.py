from __future__ import annotations

from datetime import UTC, datetime

import pytest

from adapters_v1.models import AttemptInput
from adapters_v1.native import NativeScaffoldAdapter, ScaffoldRuntime, UsageEvidence
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    HarnessCapabilities,
    HarnessSpec,
    ScenarioSpec,
)

HASH = "a" * 64
NOW = datetime.now(UTC)


class FixtureScaffold:
    id = "bare"

    async def run(self, **kwargs: object):
        yield "scaffold_phase", {"phase": "generating"}
        yield "scaffold_delta", {"delta": "answer"}
        yield "usage", {"input_tokens": 3, "output_tokens": 2}
        yield "final_output", {"output": "answer"}


def bound_input() -> AttemptInput:
    attempt = AttemptEnvelope(
        attempt_id="attempt-one", episode_id="episode-one", ordinal=1, provider_model="local-model", provider="local", endpoint_id="local-endpoint", pinned_endpoint_digest=HASH, harness_id="harness-one", factor_assignments={},
        budget=BudgetSpec(max_attempts=1, max_cost_usd=1.0, max_latency_seconds=5.0, max_tokens=100, max_tool_calls=0, max_context_tokens=100),
        provenance=ExecutionProvenance(code_revision="fixture", code_hash=HASH, runtime_image="fixture", runtime_image_hash=HASH, environment_hash=HASH, prompt_hash=HASH, context_hash=HASH, tool_hash=HASH, source_refs=({"source_uri": "fixture://source", "content_hash": HASH},), captured_at=NOW),
        request_hash=HASH, status="queued", queued_at=NOW,
    )
    return AttemptInput.bind(ScenarioSpec(scenario_id="scenario-one", title="Scenario", task_family="fixture", prompt="Synthetic fixture prompt."), attempt)


def harness() -> HarnessSpec:
    return HarnessSpec(harness_id="harness-one", version="1", adapter="in_process", adapter_identity="native-one", adapter_digest=HASH, timeout_seconds=5)


@pytest.mark.asyncio
async def test_native_bridge_runs_explicit_scaffold_and_holds_without_provider_evidence() -> None:
    adapter = NativeScaffoldAdapter(adapter_id="native-one", adapter_digest=HASH, runtime_factory=lambda h, i: ScaffoldRuntime(scaffold=FixtureScaffold(), task=object(), provider=object(), options=object(), run_id="run-one"))
    prepared = await adapter.prepare_attempt(harness(), bound_input())
    result = await adapter.execute_attempt(prepared)
    assert result.terminal_outcome == "incomplete"
    assert result.usage is not None
    assert result.usage.context_tokens is None
    assert result.response_artifact_id == "native-output"
    assert result.response_hash is not None
    assert any(
        item.artifact_id == "native-output"
        and item.sha256 == result.response_hash
        and item.content == b"answer"
        for item in await adapter.collect_artifacts(prepared)
    )
    events = [event async for event in adapter.stream_events(prepared)]
    assert [event.sequence for event in events] == list(range(len(events)))


@pytest.mark.asyncio
async def test_native_bridge_completed_requires_all_endpoint_and_usage_evidence() -> None:
    adapter = NativeScaffoldAdapter(adapter_id="native-one", adapter_digest=HASH, runtime_factory=lambda h, i: ScaffoldRuntime(scaffold=FixtureScaffold(), task=object(), provider=object(), options=object(), run_id="run-one", usage_evidence=UsageEvidence(provider_version="local-1", endpoint_digest=HASH, context_tokens=3, tool_calls=0)), capabilities=HarnessCapabilities(memory=True))
    assert (await adapter.describe_capabilities()).capabilities.memory
    prepared = await adapter.prepare_attempt(harness(), bound_input())
    result = await adapter.execute_attempt(prepared)
    assert result.terminal_outcome == "completed"
    assert result.usage is not None and result.usage.complete_evidence
    assert result.response_artifact_id == "native-output"
    artifacts = await adapter.collect_artifacts(prepared)
    assert any(item.sha256 == result.response_hash and item.content == b"answer" for item in artifacts)
    await adapter.cancel_attempt(prepared)
    await adapter.cancel_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
