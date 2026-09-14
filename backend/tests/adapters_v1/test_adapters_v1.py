from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from adapters_v1 import (
    AdapterRegistry,
    ArtifactRef,
    AttemptInput,
    CommandJsonlAdapter,
    HttpRpcAdapter,
    ProviderUsage,
    RecordedAdapter,
    ResultBundle,
    certify_adapter,
    command_jsonl,
    validate_rpc_endpoint,
)
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
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


def attempt() -> AttemptEnvelope:
    return AttemptEnvelope(
        attempt_id="attempt-one", episode_id="episode-one", ordinal=1, provider_model="recorded", provider="test",
        harness_id="harness-one", factor_assignments={}, budget=BudgetSpec(max_attempts=1, max_cost_usd=1.0, max_latency_seconds=5.0, max_tokens=10, max_tool_calls=0, max_context_tokens=10),
        provenance=provenance(), request_hash=HASH, status="queued", queued_at=NOW,
    )


def scenario(scenario_id: str = "scenario-one", **updates: object) -> ScenarioSpec:
    values: dict[str, object] = {
        "scenario_id": scenario_id, "title": "Scenario", "task_family": "fixture",
        "prompt": "Synthetic fixture prompt.",
    }
    values.update(updates)
    return ScenarioSpec(**values)


def input(attempt_value: AttemptEnvelope | None = None, scenario_value: ScenarioSpec | None = None) -> AttemptInput:
    return AttemptInput.bind(scenario_value or scenario(), attempt_value or attempt())


def provenance() -> ExecutionProvenance:
    return ExecutionProvenance(
        code_revision="fixture", code_hash=HASH, runtime_image="fixture", runtime_image_hash=HASH,
        environment_hash=HASH, prompt_hash=HASH, context_hash=HASH, tool_hash=HASH,
        source_refs=({"source_uri": "fixture://source", "content_hash": HASH},), captured_at=NOW,
    )


def harness(kind: str, adapter_id: str, digest: str, **kwargs: object) -> HarnessSpec:
    values = {"harness_id": "harness-one", "version": "1", "adapter": kind, "adapter_identity": adapter_id, "adapter_digest": digest, "timeout_seconds": 5}
    values.update(kwargs)
    if values.get("configuration") and "effective_configuration_hash" not in values:
        values["effective_configuration_hash"] = sha256(values["configuration"])
    return HarnessSpec(**values)


def result() -> ResultBundle:
    output = b"fixture response"
    return ResultBundle(
        attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
        response_hash=sha256_bytes(output), response_artifact_id="assistant-output",
        usage=ProviderUsage(evidence_source="fixture_recorded", total_tokens=1),
        artifacts=(ArtifactRef(artifact_id="assistant-output", media_type="text/plain", sha256=sha256_bytes(output), content=output),),
    )


class ProcessDouble:
    def __init__(self) -> None:
        self.pid = 123
        self.returncode: int | None = None
        self.terminated = 0
        self.killed = 0
        self.waits = 0

    def terminate(self) -> None:
        self.terminated += 1

    def kill(self) -> None:
        self.killed += 1

    async def wait(self) -> int:
        self.waits += 1
        self.returncode = 0
        return 0


class ResettingStdin:
    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer

    def write(self, data: bytes) -> None:
        self._writer.write(data)

    async def drain(self) -> None:
        raise ConnectionResetError("child closed stdin before drain")

    def close(self) -> None:
        self._writer.close()

    async def wait_closed(self) -> None:
        await self._writer.wait_closed()


class BlockingCloseStdin(ResettingStdin):
    async def wait_closed(self) -> None:
        await asyncio.Event().wait()


def test_typed_usage_is_immutable_strict_and_json_round_trips() -> None:
    usage = ProviderUsage(
        evidence_source="provider_reported", input_tokens=2, output_tokens=3, total_tokens=5,
        context_tokens=2, tool_calls=1, actual_cost_usd=0.01, provider_usage_digest=HASH,
        observed_provider_version="2026-08-14", observed_endpoint_digest=HASH,
    )
    output = b"typed usage response"
    bundle = ResultBundle(
        attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
        response_hash=sha256_bytes(output), response_artifact_id="assistant-output", usage=usage,
        artifacts=(ArtifactRef(artifact_id="assistant-output", media_type="text/plain", sha256=sha256_bytes(output), content=output),),
    )
    assert ResultBundle.model_validate_json(bundle.model_dump_json()).usage == usage
    with pytest.raises((TypeError, ValueError)):
        usage.input_tokens = 9  # type: ignore[misc]
    with pytest.raises(ValueError, match="tokens"):
        ProviderUsage(evidence_source="fixture_recorded", tokens=1)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="total_tokens"):
        ProviderUsage(evidence_source="provider_reported", input_tokens=2, output_tokens=3, total_tokens=4)


def test_completed_result_requires_one_durable_matching_response_artifact() -> None:
    output = b"canonical user-visible output"
    artifact = ArtifactRef(artifact_id="assistant-output", media_type="text/plain", sha256=sha256_bytes(output), content=output)
    with pytest.raises(ValueError, match="requires response_hash"):
        ResultBundle(attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW)
    with pytest.raises(ValueError, match="exactly one"):
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
            response_hash=artifact.sha256, response_artifact_id=artifact.artifact_id, artifacts=(artifact, artifact),
        )
    with pytest.raises(ValueError, match="sha256"):
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
            response_hash=HASH, response_artifact_id=artifact.artifact_id, artifacts=(artifact,),
        )
    with pytest.raises(ValueError, match="durable URI"):
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
            response_hash=artifact.sha256, response_artifact_id=artifact.artifact_id,
            artifacts=(ArtifactRef(artifact_id=artifact.artifact_id, media_type="text/plain", sha256=artifact.sha256),),
        )


def test_terminal_failure_classification_is_explicit_and_outcome_bound() -> None:
    with pytest.raises(ValueError, match="require failure_classification"):
        ResultBundle(attempt_id="attempt-one", terminal_outcome="failed", completed_at=NOW)
    with pytest.raises(ValueError, match="must not declare"):
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="cancelled", completed_at=NOW,
            failure_classification="transient_adapter",
        )
    with pytest.raises(ValueError, match="must not declare"):
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
            response_hash=HASH, response_artifact_id="assistant-output",
            artifacts=(ArtifactRef(
                artifact_id="assistant-output", media_type="text/plain", sha256=HASH,
                uri="fixture://output",
            ),),
            failure_classification="transient_adapter",
        )
    assert ResultBundle(
        attempt_id="attempt-one", terminal_outcome="timed_out", completed_at=NOW,
        failure_classification="transient_provider",
    ).failure_classification == "transient_provider"


@pytest.mark.asyncio
async def test_recorded_command_and_usage_certification_contracts(tmp_path: Path) -> None:
    fixture = result()
    recorded = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": fixture})
    prepared = await recorded.prepare_attempt(harness("recorded", "recorded-one", HASH), input())
    assert (await recorded.execute_attempt(prepared)).usage == fixture.usage

    executable = tmp_path / "runner"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    command = CommandJsonlAdapter(
        adapter_id="command-one", adapter_digest=HASH, executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
    )
    events, parsed = command._parse_jsonl(
        (json.dumps({"result": fixture.model_dump(mode="json")}) + "\n").encode(), attempt()
    )
    assert not events and parsed.usage == fixture.usage

    recorded._capabilities = recorded._capabilities.model_copy(
        update={"capabilities": recorded._capabilities.capabilities.model_copy(update={"usage": True})}
    )
    assert not (await certify_adapter(recorded, harness("recorded", "recorded-one", HASH), input())).passed


@pytest.mark.asyncio
async def test_contract_payload_adapters_reject_completed_results_without_response_artifacts(tmp_path: Path) -> None:
    missing = {
        "attempt_id": "attempt-one", "terminal_outcome": "completed",
        "completed_at": NOW.isoformat(), "artifacts": [],
    }
    executable = tmp_path / "runner"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    command = CommandJsonlAdapter(
        adapter_id="command-one", adapter_digest=HASH, executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
    )
    with pytest.raises(ValueError, match="violates adapter contract"):
        command._parse_jsonl((json.dumps({"result": missing}) + "\n").encode(), attempt())

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    http = HttpRpcAdapter(adapter_id="http-one", adapter_digest=HASH, endpoint="http://127.0.0.1:9000/rpc", allowed_hosts=frozenset({"127.0.0.1"}), client=client)
    with pytest.raises(ValueError, match="violates adapter contract"):
        http._parse_payload({"events": [], "result": missing}, attempt())
    await client.aclose()

    bypass = ResultBundle.model_construct(
        attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
        response_hash=None, response_artifact_id=None, artifacts=(),
    )
    recorded = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": bypass})
    prepared = await recorded.prepare_attempt(harness("recorded", "recorded-one", HASH), input())
    with pytest.raises(ValueError, match="requires response_hash"):
        await recorded.execute_attempt(prepared)


@pytest.mark.asyncio
async def test_command_stream_waits_for_execute_and_cancel_releases_it(tmp_path: Path) -> None:
    fixture = result()
    event = TraceEvent(
        trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0,
        actor="model", event_type="response", timestamp=NOW, monotonic_time=0,
        payload={"transport": "command"}, payload_hash=HASH,
    )
    executable = tmp_path / "runner"
    lines = "\n".join((json.dumps({"event": event.model_dump(mode="json")}), json.dumps({"result": fixture.model_dump(mode="json")})))
    executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{lines}'\n", encoding="utf-8")
    executable.chmod(0o755)
    adapter = CommandJsonlAdapter(
        adapter_id="command-one", adapter_digest=HASH, executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
    )
    prepared = await adapter.prepare_attempt(harness("cli", "command-one", HASH, configuration={"argv": [str(executable)]}), input())
    drain = asyncio.create_task(_drain(adapter, prepared))
    await asyncio.sleep(0)
    assert not drain.done()
    await adapter.execute_attempt(prepared)
    assert [item.payload for item in await asyncio.wait_for(drain, timeout=1)] == [{"transport": "command"}]

    cancelled_attempt = attempt().model_copy(update={"attempt_id": "attempt-two", "episode_id": "episode-two"})
    cancelled = await adapter.prepare_attempt(harness("cli", "command-one", HASH, configuration={"argv": [str(executable)]}), input(cancelled_attempt))
    drain = asyncio.create_task(_drain(adapter, cancelled))
    await adapter.cancel_attempt(cancelled)
    assert await asyncio.wait_for(drain, timeout=1) == []


@pytest.mark.asyncio
async def test_recorded_registry_preflight_and_certification() -> None:
    trace = TraceEvent(
        trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0,
        actor="harness", event_type="request", timestamp=NOW, monotonic_time=0,
        payload={"transport": "recorded"}, payload_hash=HASH,
    )
    adapter = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": result()}, events={"attempt-one": (trace,)})
    spec = harness("recorded", "recorded-one", HASH)
    registry = AdapterRegistry()
    await registry.install_trusted(adapter, HASH)
    assert registry.get("recorded-one", HASH) is adapter
    with pytest.raises(ValueError, match="already installed"):
        await registry.install_trusted(adapter, HASH)
    with pytest.raises(ValueError, match="digest"):
        registry.get("recorded-one", "b" * 64)
    report = await certify_adapter(adapter, spec, input())
    assert report.passed


@pytest.mark.asyncio
async def test_recorded_rejects_capability_and_artifact_hash_mismatch() -> None:
    with pytest.raises(ValueError, match="sha256"):
        ArtifactRef(artifact_id="artifact-one", media_type="text/plain", sha256=HASH, content=b"wrong")
    adapter = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": result()})
    spec = harness("recorded", "recorded-one", HASH, capabilities={"tools": True})
    with pytest.raises(ValueError, match="required capability"):
        await adapter.prepare_attempt(spec, input())
    spec = harness("recorded", "recorded-one", HASH, schema_hashes={"config_schema_hash": "b" * 64})
    with pytest.raises(ValueError, match="does not certify"):
        await adapter.prepare_attempt(spec, input())


@pytest.mark.asyncio
async def test_effective_configuration_hash_is_distinct_from_config_schema_hash() -> None:
    schema_hash = "b" * 64
    configuration = {"fixture": "one"}
    adapter = RecordedAdapter(
        adapter_id="recorded-one",
        adapter_digest=HASH,
        results={"attempt-one": result()},
        config_schema_hash=schema_hash,
    )
    spec = harness(
        "recorded",
        "recorded-one",
        HASH,
        configuration=configuration,
        effective_configuration_hash=sha256(configuration),
        schema_hashes={"config_schema_hash": schema_hash},
    )
    assert spec.effective_configuration_hash != spec.schema_hashes.config_schema_hash
    prepared = await adapter.prepare_attempt(spec, input())
    assert prepared.attempt_id == "attempt-one"

    omitted = harness("recorded", "recorded-one", HASH, configuration=configuration)
    with pytest.raises(ValueError, match="missing or mismatched"):
        await adapter.prepare_attempt(omitted, input())
    mismatched = harness(
        "recorded", "recorded-one", HASH, configuration=configuration,
        schema_hashes={"config_schema_hash": "c" * 64},
    )
    with pytest.raises(ValueError, match="missing or mismatched"):
        await adapter.prepare_attempt(mismatched, input())


@pytest.mark.asyncio
async def test_command_jsonl_rejects_shell_config_and_times_out(tmp_path: Path) -> None:
    executable = tmp_path / "runner"
    executable.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    executable.chmod(0o755)
    adapter = CommandJsonlAdapter(adapter_id="command-one", adapter_digest=HASH, executable=executable, executable_digest=sha256_bytes(executable.read_bytes()))
    spec = harness("cli", "command-one", HASH, timeout_seconds=1, configuration={"argv": str(executable)})
    with pytest.raises(ValueError, match="argv"):
        await adapter.prepare_attempt(spec, input())
    spec = harness("cli", "command-one", HASH, configuration={"argv": [str(executable)], "environment": {"PATH": "bad"}})
    with pytest.raises(ValueError, match="allowlist"):
        await adapter.prepare_attempt(spec, input())
    spec = harness("cli", "command-one", HASH, timeout_seconds=1, configuration={"argv": [str(executable)]})
    prepared = await adapter.prepare_attempt(spec, input())
    assert (await adapter.execute_attempt(prepared)).terminal_outcome == "timed_out"
    await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)


@pytest.mark.asyncio
async def test_command_timeout_includes_stdin_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "runner"
    executable.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    executable.chmod(0o755)
    original_create = command_jsonl.asyncio.create_subprocess_exec

    async def create_with_blocking_close(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        process = await original_create(*args, **kwargs)
        assert process.stdin is not None
        process.stdin = BlockingCloseStdin(process.stdin)
        return process

    monkeypatch.setattr(command_jsonl.asyncio, "create_subprocess_exec", create_with_blocking_close)
    adapter = CommandJsonlAdapter(
        adapter_id="command-one",
        adapter_digest=HASH,
        executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
    )
    prepared = await adapter.prepare_attempt(
        harness("cli", "command-one", HASH, timeout_seconds=1, configuration={"argv": [str(executable)]}),
        input(),
    )
    assert (await adapter.execute_attempt(prepared)).terminal_outcome == "timed_out"
    await adapter.cleanup_attempt(prepared)


@pytest.mark.asyncio
async def test_command_jsonl_rejects_malformed_output(tmp_path: Path) -> None:
    executable = tmp_path / "runner"
    executable.write_text("#!/bin/sh\nprintf '%s\\n' not-json\n", encoding="utf-8")
    executable.chmod(0o755)
    adapter = CommandJsonlAdapter(adapter_id="command-one", adapter_digest=HASH, executable=executable, executable_digest=sha256_bytes(executable.read_bytes()))
    prepared = await adapter.prepare_attempt(harness("cli", "command-one", HASH, configuration={"argv": [str(executable)]}), input())
    with pytest.raises(ValueError, match="malformed JSONL"):
        await adapter.execute_attempt(prepared)


@pytest.mark.asyncio
async def test_command_jsonl_preserves_malformed_output_after_stdin_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "runner"
    executable.write_text("#!/bin/sh\nprintf '%s\\n' not-json\n", encoding="utf-8")
    executable.chmod(0o755)
    original_create = command_jsonl.asyncio.create_subprocess_exec

    async def create_with_resetting_stdin(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        process = await original_create(*args, **kwargs)
        assert process.stdin is not None
        process.stdin = ResettingStdin(process.stdin)
        return process

    monkeypatch.setattr(
        command_jsonl.asyncio,
        "create_subprocess_exec",
        create_with_resetting_stdin,
    )
    adapter = CommandJsonlAdapter(
        adapter_id="command-one",
        adapter_digest=HASH,
        executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
    )
    prepared = await adapter.prepare_attempt(
        harness("cli", "command-one", HASH, configuration={"argv": [str(executable)]}),
        input(),
    )

    with pytest.raises(ValueError, match="malformed JSONL"):
        await adapter.execute_attempt(prepared)

    assert prepared.attempt_id not in adapter._processes
    assert adapter._event_queues[prepared.attempt_id]._closed


@pytest.mark.asyncio
async def test_command_jsonl_terminates_directly_when_group_signal_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    process = ProcessDouble()
    adapter = CommandJsonlAdapter(adapter_id="command-one", adapter_digest=HASH, executable="/usr/bin/true", executable_digest=HASH)

    def denied_group_signal(pid: int, signal_number: int) -> None:
        raise PermissionError

    monkeypatch.setattr(command_jsonl.os, "killpg", denied_group_signal)

    await adapter._terminate_process(process)  # type: ignore[arg-type]

    assert process.terminated == 1
    assert process.killed == 0
    assert process.waits == 1


@pytest.mark.asyncio
async def test_command_jsonl_kills_directly_after_denied_group_signal_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    process = ProcessDouble()
    adapter = CommandJsonlAdapter(adapter_id="command-one", adapter_digest=HASH, executable="/usr/bin/true", executable_digest=HASH)

    def denied_group_signal(pid: int, signal_number: int) -> None:
        raise PermissionError

    async def timeout_after_wait(awaitable: object, timeout: float) -> object:
        await awaitable  # type: ignore[misc]
        raise TimeoutError

    monkeypatch.setattr(command_jsonl.os, "killpg", denied_group_signal)
    monkeypatch.setattr(command_jsonl.asyncio, "wait_for", timeout_after_wait)

    await adapter._terminate_process(process)  # type: ignore[arg-type]

    assert process.terminated == 1
    assert process.killed == 1
    assert process.waits == 2


@pytest.mark.asyncio
async def test_adapters_snapshot_and_transport_the_exact_bound_input(tmp_path: Path) -> None:
    fixture = result()
    bound = input()
    executable = tmp_path / "runner.py"
    captured = tmp_path / "input.json"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "raw = sys.stdin.buffer.read()\n"
        "pathlib.Path(sys.argv[1]).write_bytes(raw)\n"
        f"print(json.dumps({{'result': {fixture.model_dump(mode='json')!r}}}))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    command = CommandJsonlAdapter(
        adapter_id="command-one", adapter_digest=HASH, executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
    )
    prepared = await command.prepare_attempt(
        harness("cli", "command-one", HASH, configuration={"argv": [str(executable), str(captured)]}), bound,
    )
    assert (await command.execute_attempt(prepared)).terminal_outcome == "completed"
    assert captured.read_bytes() == canonical_json(bound.model_dump(mode="json"))

    captured_http: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_http.append(request.content)
        return httpx.Response(200, json={"events": [], "result": fixture.model_dump(mode="json")})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = HttpRpcAdapter(adapter_id="http-one", adapter_digest=HASH, endpoint="http://127.0.0.1:9000/rpc", allowed_hosts=frozenset({"127.0.0.1"}), client=client)
    http_prepared = await http.prepare_attempt(harness("http", "http-one", HASH, execution_mode="remote", isolation="remote_sandbox"), bound)
    assert (await http.execute_attempt(http_prepared)).terminal_outcome == "completed"
    assert captured_http == [canonical_json(bound.model_dump(mode="json"))]
    await client.aclose()


@pytest.mark.asyncio
async def test_attempt_input_rejects_extra_keys_and_nested_mutation_before_adapter_execution() -> None:
    bound = input()
    raw = bound.model_dump(mode="json")
    raw["unexpected"] = True
    with pytest.raises(ValueError, match="Extra inputs"):
        AttemptInput.model_validate_json(canonical_json(raw))
    bound.scenario.prompt = "mutated after binding"
    adapter = RecordedAdapter(adapter_id="recorded-one", adapter_digest=HASH, results={"attempt-one": result()})
    with pytest.raises(ValueError, match="scenario_digest"):
        await adapter.prepare_attempt(harness("recorded", "recorded-one", HASH), bound)


def test_http_endpoint_policy_rejects_ssrf() -> None:
    allowed = frozenset({"127.0.0.1", "example.test", "169.254.169.254"})
    assert validate_rpc_endpoint("http://127.0.0.1:9999/rpc", allowed).startswith("http")
    for endpoint in ("http://example.test/rpc", "https://user@example.test/rpc", "https://169.254.169.254/rpc", "https://example.test/rpc#x"):
        with pytest.raises(ValueError):
            validate_rpc_endpoint(endpoint, allowed)


@pytest.mark.asyncio
async def test_http_rpc_rejects_redirect_and_validates_payload_without_network() -> None:
    redirect = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": "http://127.0.0.1"})))
    adapter = HttpRpcAdapter(adapter_id="http-one", adapter_digest=HASH, endpoint="http://127.0.0.1:9000/rpc", allowed_hosts=frozenset({"127.0.0.1"}), client=redirect)
    prepared = await adapter.prepare_attempt(harness("http", "http-one", HASH, execution_mode="remote", isolation="remote_sandbox"), input())
    failed_drain = asyncio.create_task(_drain(adapter, prepared))
    with pytest.raises(ValueError, match="redirect"):
        await adapter.execute_attempt(prepared)
    assert await asyncio.wait_for(failed_drain, timeout=1) == []
    await redirect.aclose()

    event = TraceEvent(
        trace_id="trace-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0,
        actor="model", event_type="response", timestamp=NOW, monotonic_time=0,
        payload={"transport": "http"}, payload_hash=HASH,
    )
    payload = {"events": [event.model_dump(mode="json")], "result": result().model_dump(mode="json")}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    adapter = HttpRpcAdapter(adapter_id="http-one", adapter_digest=HASH, endpoint="http://127.0.0.1:9000/rpc", allowed_hosts=frozenset({"127.0.0.1"}), client=client)
    prepared = await adapter.prepare_attempt(harness("http", "http-one", HASH, execution_mode="remote", isolation="remote_sandbox"), input())
    drain = asyncio.create_task(_drain(adapter, prepared))
    await asyncio.sleep(0)
    assert not drain.done()
    assert (await adapter.execute_attempt(prepared)).terminal_outcome == "completed"
    assert [item.payload for item in await asyncio.wait_for(drain, timeout=1)] == [{"transport": "http"}]
    await adapter.cancel_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    await client.aclose()


async def _drain(adapter: object, prepared: object) -> list[TraceEvent]:
    return [event async for event in adapter.stream_events(prepared)]  # type: ignore[attr-defined]
