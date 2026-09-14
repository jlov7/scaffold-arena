from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from adapters_v1 import (
    AdapterTransportLimits,
    ArtifactRef,
    AttemptInput,
    CommandJsonlAdapter,
    HttpRpcAdapter,
    InvocationContext,
    ProviderUsage,
    ResultBundle,
    TransportLimitExceeded,
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


def provenance() -> ExecutionProvenance:
    return ExecutionProvenance(
        code_revision="fixture",
        code_hash=HASH,
        runtime_image="fixture",
        runtime_image_hash=HASH,
        environment_hash=HASH,
        prompt_hash=HASH,
        context_hash=HASH,
        tool_hash=HASH,
        source_refs=({"source_uri": "fixture://source", "content_hash": HASH},),
        captured_at=NOW,
    )


def attempt(attempt_id: str = "attempt-one", episode_id: str = "episode-one") -> AttemptEnvelope:
    return AttemptEnvelope(
        attempt_id=attempt_id,
        episode_id=episode_id,
        ordinal=1,
        provider_model="fixture",
        provider="test",
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=1,
            max_cost_usd=1.0,
            max_latency_seconds=5.0,
            max_tokens=128,
            max_tool_calls=2,
            max_context_tokens=1024,
        ),
        provenance=provenance(),
        request_hash=HASH,
        status="queued",
        queued_at=NOW,
    )


def bound_input(attempt_value: AttemptEnvelope | None = None) -> AttemptInput:
    return AttemptInput.bind(
        ScenarioSpec(
            scenario_id="scenario-one",
            title="Scenario",
            task_family="fixture",
            prompt="Synthetic fixture prompt.",
        ),
        attempt_value or attempt(),
    )


def harness(kind: str, adapter_id: str, digest: str, **updates: object) -> HarnessSpec:
    values: dict[str, object] = {
        "harness_id": "harness-one",
        "version": "1",
        "adapter": kind,
        "adapter_identity": adapter_id,
        "adapter_digest": digest,
        "timeout_seconds": 5,
    }
    values.update(updates)
    if values.get("configuration") and "effective_configuration_hash" not in values:
        values["effective_configuration_hash"] = sha256(values["configuration"])
    return HarnessSpec(**values)


def result(attempt_id: str = "attempt-one") -> ResultBundle:
    output = b"fixture response"
    return ResultBundle(
        attempt_id=attempt_id,
        terminal_outcome="completed",
        completed_at=NOW,
        response_hash=sha256_bytes(output),
        response_artifact_id="assistant-output",
        usage=ProviderUsage(evidence_source="fixture_recorded", total_tokens=1),
        artifacts=(
            ArtifactRef(
                artifact_id="assistant-output",
                media_type="text/plain",
                sha256=sha256_bytes(output),
                content=output,
            ),
        ),
    )


def trace_event(attempt_id: str = "attempt-one", episode_id: str = "episode-one") -> TraceEvent:
    payload = {"transport": "bounded"}
    return TraceEvent(
        trace_id="trace-one",
        episode_id=episode_id,
        attempt_id=attempt_id,
        sequence=0,
        actor="model",
        event_type="response",
        timestamp=NOW,
        monotonic_time=0,
        payload=payload,
        payload_hash=sha256(payload),
    )


def invocation(attempt_id: str = "attempt-one") -> InvocationContext:
    return InvocationContext.bind(
        invocation_id="invocation-one",
        attempt_id=attempt_id,
        generation=1,
        fence_token="b" * 64,
        provider_idempotency_key="stable-provider-key",
        aggregate_deadline_at=NOW + timedelta(minutes=5),
    )


def command_adapter(executable: Path, *, limits: AdapterTransportLimits | None = None) -> CommandJsonlAdapter:
    return CommandJsonlAdapter(
        adapter_id="command-one",
        adapter_digest=HASH,
        executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
        limits=limits,
    )


def command_harness(executable: Path) -> HarnessSpec:
    return harness(
        "cli",
        "command-one",
        HASH,
        configuration={"argv": [str(executable)]},
    )


def http_harness() -> HarnessSpec:
    return harness(
        "http",
        "http-one",
        HASH,
        execution_mode="remote",
        isolation="remote_sandbox",
    )


def test_transport_limits_are_strict_and_bounded() -> None:
    limits = AdapterTransportLimits(
        max_request_bytes=1024,
        max_response_bytes=2048,
        max_stderr_bytes=512,
        max_jsonl_line_bytes=256,
        max_events=8,
        max_artifact_bytes=1024,
        max_total_artifact_bytes=2048,
    )
    assert limits.max_events == 8
    with pytest.raises(ValidationError):
        AdapterTransportLimits(max_response_bytes=0)
    with pytest.raises(ValidationError, match="line"):
        AdapterTransportLimits(max_jsonl_line_bytes=2048, max_response_bytes=1024)
    with pytest.raises(ValidationError, match="artifact"):
        AdapterTransportLimits(max_artifact_bytes=4096, max_total_artifact_bytes=1024)


@pytest.mark.asyncio
async def test_command_transport_caps_request_stderr_events_and_artifacts(tmp_path: Path) -> None:
    executable = tmp_path / "limits.py"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stderr.write('x' * 4096)\n"
        "sys.stderr.flush()\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    request_limited = command_adapter(
        executable,
        limits=AdapterTransportLimits(max_request_bytes=32),
    )
    with pytest.raises(TransportLimitExceeded, match="request"):
        await request_limited.prepare_attempt(command_harness(executable), bound_input())

    stderr_limited = command_adapter(
        executable,
        limits=AdapterTransportLimits(max_stderr_bytes=128),
    )
    prepared = await stderr_limited.prepare_attempt(
        command_harness(executable),
        bound_input(),
    )
    with pytest.raises(TransportLimitExceeded, match="stderr"):
        await asyncio.wait_for(stderr_limited.execute_attempt(prepared), timeout=2)
    await stderr_limited.cleanup_attempt(prepared)

    first = trace_event()
    second_payload = {"transport": "bounded-second"}
    second = first.model_copy(
        update={
            "sequence": 1,
            "payload": second_payload,
            "payload_hash": sha256(second_payload),
        }
    )
    event_limited = command_adapter(
        executable,
        limits=AdapterTransportLimits(max_events=1),
    )
    payload = b"\n".join(
        (
            json.dumps({"event": first.model_dump(mode="json")}).encode(),
            json.dumps({"event": second.model_dump(mode="json")}).encode(),
            json.dumps({"result": result().model_dump(mode="json")}).encode(),
        )
    )
    with pytest.raises(TransportLimitExceeded, match="events"):
        event_limited._parse_jsonl(payload, attempt())

    oversized_output = b"artifact-is-too-large"
    oversized_result = ResultBundle(
        attempt_id="attempt-one",
        terminal_outcome="completed",
        completed_at=NOW,
        response_hash=sha256_bytes(oversized_output),
        response_artifact_id="assistant-output",
        artifacts=(
            ArtifactRef(
                artifact_id="assistant-output",
                media_type="text/plain",
                sha256=sha256_bytes(oversized_output),
                content=oversized_output,
            ),
        ),
    )
    artifact_limited = command_adapter(
        executable,
        limits=AdapterTransportLimits(
            max_artifact_bytes=8,
            max_total_artifact_bytes=8,
        ),
    )
    with pytest.raises(TransportLimitExceeded, match="artifact"):
        artifact_limited._parse_jsonl(
            json.dumps({"result": oversized_result.model_dump(mode="json")}).encode(),
            attempt(),
        )


@pytest.mark.asyncio
async def test_command_jsonl_streams_incrementally_and_bounds_stdout(tmp_path: Path) -> None:
    fixture = result()
    event = trace_event()
    executable = tmp_path / "stream.py"
    event_record = json.dumps({"event": event.model_dump(mode="json")})
    result_record = json.dumps({"result": fixture.model_dump(mode="json")})
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        f"print({event_record!r}, flush=True)\n"
        "time.sleep(2.0)\n"
        f"print({result_record!r}, flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    adapter = command_adapter(executable)
    prepared = await adapter.prepare_attempt(command_harness(executable), bound_input())
    execution = asyncio.create_task(adapter.execute_attempt(prepared))
    stream = adapter.stream_events(prepared).__aiter__()
    observed = await asyncio.wait_for(anext(stream), timeout=1.0)
    assert observed.payload == {"transport": "bounded"}
    assert not execution.done()
    assert (await execution).terminal_outcome == "completed"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)

    oversized = tmp_path / "oversized.py"
    oversized.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stdout.write('x' * 4096)\n"
        "sys.stdout.flush()\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    oversized.chmod(0o755)
    limited = command_adapter(
        oversized,
        limits=AdapterTransportLimits(
            max_response_bytes=128,
            max_jsonl_line_bytes=64,
        ),
    )
    prepared = await limited.prepare_attempt(command_harness(oversized), bound_input())
    with pytest.raises(TransportLimitExceeded, match="stdout|line"):
        await asyncio.wait_for(limited.execute_attempt(prepared), timeout=2)
    await limited.cleanup_attempt(prepared)


@pytest.mark.asyncio
async def test_command_invocation_context_is_injected_without_mutating_stdin(tmp_path: Path) -> None:
    fixture = result()
    executable = tmp_path / "capture.py"
    capture = tmp_path / "capture.json"
    payload_json = json.dumps({"result": fixture.model_dump(mode="json")})
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "raw = sys.stdin.buffer.read()\n"
        "payload = {\n"
        "  'stdin': raw.decode('utf-8'),\n"
        "  'invocation_id': os.environ.get('SCAFFOLD_ARENA_INVOCATION_ID'),\n"
        "  'generation': os.environ.get('SCAFFOLD_ARENA_INVOCATION_GENERATION'),\n"
        "  'fence': os.environ.get('SCAFFOLD_ARENA_FENCE_TOKEN'),\n"
        "  'idempotency': os.environ.get('SCAFFOLD_ARENA_IDEMPOTENCY_KEY'),\n"
        "  'digest': os.environ.get('SCAFFOLD_ARENA_INVOCATION_DIGEST'),\n"
        "}\n"
        f"pathlib.Path({str(capture)!r}).write_text(json.dumps(payload))\n"
        f"print({payload_json!r})\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    adapter = command_adapter(executable)
    bound = bound_input()
    context = invocation()
    prepared = await adapter.prepare_invocation(command_harness(executable), bound, context)
    assert (await adapter.execute_attempt(prepared)).terminal_outcome == "completed"
    captured = json.loads(capture.read_text())
    assert captured["stdin"] == canonical_json(bound.model_dump(mode="json")).decode()
    assert captured == {
        **captured,
        "invocation_id": context.invocation_id,
        "generation": "1",
        "fence": context.fence_token,
        "idempotency": context.provider_idempotency_key,
        "digest": context.context_digest,
    }


class _DelayedNdjsonStream(httpx.AsyncByteStream):
    def __init__(self, event_record: bytes, result_record: bytes) -> None:
        self.event_record = event_record
        self.result_record = result_record
        self.release = asyncio.Event()

    async def __aiter__(self):
        yield self.event_record + b"\n"
        await self.release.wait()
        yield self.result_record + b"\n"


class _NeverEndingStream(httpx.AsyncByteStream):
    def __init__(self, event_record: bytes) -> None:
        self.event_record = event_record
        self.block = asyncio.Event()

    async def __aiter__(self):
        yield self.event_record + b"\n"
        await self.block.wait()


class _Peer:
    def __init__(self, host: str) -> None:
        self.host = host

    def get_extra_info(self, name: str):
        if name == "server_addr":
            return (self.host, 443)
        return None


@pytest.mark.asyncio
async def test_http_rpc_streams_ndjson_and_sends_fence_headers() -> None:
    fixture = result()
    event = trace_event()
    stream = _DelayedNdjsonStream(
        json.dumps({"event": event.model_dump(mode="json")}).encode(),
        json.dumps({"result": fixture.model_dump(mode="json")}).encode(),
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            stream=stream,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpRpcAdapter(
        adapter_id="http-one",
        adapter_digest=HASH,
        endpoint="http://127.0.0.1:9000/rpc",
        allowed_hosts=frozenset({"127.0.0.1"}),
        client=client,
    )
    context = invocation()
    prepared = await adapter.prepare_invocation(http_harness(), bound_input(), context)
    execution = asyncio.create_task(adapter.execute_attempt(prepared))
    events = adapter.stream_events(prepared).__aiter__()
    assert (await asyncio.wait_for(anext(events), timeout=0.2)).payload == {
        "transport": "bounded"
    }
    assert not execution.done()
    request = captured[0]
    assert request.headers["idempotency-key"] == context.provider_idempotency_key
    assert request.headers["x-scaffold-arena-fence-token"] == context.fence_token
    assert request.headers["x-scaffold-arena-invocation-id"] == context.invocation_id
    stream.release.set()
    assert (await execution).terminal_outcome == "completed"
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    await client.aclose()


@pytest.mark.asyncio
async def test_http_rpc_enforces_response_cap_and_connected_peer_policy() -> None:
    huge = b"{" + b"x" * 4096 + b"}"

    class HugeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield huge

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=HugeStream(),
            )
        )
    )
    adapter = HttpRpcAdapter(
        adapter_id="http-one",
        adapter_digest=HASH,
        endpoint="http://127.0.0.1:9000/rpc",
        allowed_hosts=frozenset({"127.0.0.1"}),
        client=client,
        limits=AdapterTransportLimits(
            max_response_bytes=128,
            max_jsonl_line_bytes=64,
        ),
    )
    prepared = await adapter.prepare_attempt(http_harness(), bound_input())
    with pytest.raises(TransportLimitExceeded, match="response"):
        await adapter.execute_attempt(prepared)
    await client.aclose()

    fixture = result()
    payload = {"events": [], "result": fixture.model_dump(mode="json")}
    peer_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=payload,
                extensions={"network_stream": _Peer("169.254.169.254")},
            )
        )
    )
    peer_adapter = HttpRpcAdapter(
        adapter_id="http-one",
        adapter_digest=HASH,
        endpoint="https://example.test/rpc",
        allowed_hosts=frozenset({"example.test"}),
        client=peer_client,
        require_peer_validation=True,
    )
    prepared = await peer_adapter.prepare_attempt(http_harness(), bound_input())
    with pytest.raises(ValueError, match="connected peer"):
        await peer_adapter.execute_attempt(prepared)
    await peer_client.aclose()


@pytest.mark.asyncio
async def test_http_rpc_cancellation_interrupts_inflight_stream_and_cleanup_is_complete() -> None:
    event = trace_event()
    body = _NeverEndingStream(
        json.dumps({"event": event.model_dump(mode="json")}).encode()
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/x-ndjson"},
                stream=body,
            )
        )
    )
    adapter = HttpRpcAdapter(
        adapter_id="http-one",
        adapter_digest=HASH,
        endpoint="http://127.0.0.1:9000/rpc",
        allowed_hosts=frozenset({"127.0.0.1"}),
        client=client,
    )
    prepared = await adapter.prepare_attempt(http_harness(), bound_input())
    execution = asyncio.create_task(adapter.execute_attempt(prepared))
    events = adapter.stream_events(prepared).__aiter__()
    await asyncio.wait_for(anext(events), timeout=0.2)
    await adapter.cancel_attempt(prepared)
    assert (await asyncio.wait_for(execution, timeout=1)).terminal_outcome == "cancelled"
    await adapter.cleanup_attempt(prepared)
    await adapter.cleanup_attempt(prepared)
    assert prepared.attempt_id not in adapter._attempts
    assert prepared.attempt_id not in adapter._events
    assert prepared.attempt_id not in adapter._results
    assert prepared.attempt_id not in adapter._event_queues
    await client.aclose()
