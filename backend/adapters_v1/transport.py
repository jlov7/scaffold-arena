"""Shared hard bounds and operational transport helpers for trusted adapters."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC
from typing import Any, Final

from pydantic import ConfigDict, Field, model_validator

from protocol_v1.models import AttemptEnvelope, ProtocolModel, TraceEvent

from .invocation import InvocationContext
from .models import ArtifactRef, ResultBundle, validate_result_for_attempt


class TransportLimitExceeded(ValueError):
    """A transport crossed a configured byte, record, event, or artifact bound."""


class AdapterTransportLimits(ProtocolModel):
    """Immutable resource ceilings enforced before data reaches protocol models."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    max_request_bytes: int = Field(default=4 * 1024 * 1024, ge=1, le=64 * 1024 * 1024)
    max_response_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)
    max_stderr_bytes: int = Field(default=256 * 1024, ge=1, le=16 * 1024 * 1024)
    max_jsonl_line_bytes: int = Field(default=1024 * 1024, ge=1, le=16 * 1024 * 1024)
    max_events: int = Field(default=10_000, ge=1, le=1_000_000)
    max_pending_events: int = Field(default=256, ge=1, le=65_536)
    max_artifact_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    max_total_artifact_bytes: int = Field(default=64 * 1024 * 1024, ge=1, le=4 * 1024 * 1024 * 1024)

    @model_validator(mode="before")
    @classmethod
    def choose_pending_default(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "max_pending_events" not in value:
            values = dict(value)
            requested_total = values.get("max_events", 10_000)
            if isinstance(requested_total, int) and not isinstance(requested_total, bool):
                values["max_pending_events"] = min(256, requested_total)
            return values
        return value

    @model_validator(mode="after")
    def validate_relationships(self) -> AdapterTransportLimits:
        if self.max_jsonl_line_bytes > self.max_response_bytes:
            raise ValueError("JSONL line limit cannot exceed the response limit")
        if self.max_artifact_bytes > self.max_total_artifact_bytes:
            raise ValueError("per-artifact limit cannot exceed the total artifact limit")
        if self.max_pending_events > self.max_events:
            raise ValueError("pending event limit cannot exceed total event limit")
        return self


DEFAULT_TRANSPORT_LIMITS: Final = AdapterTransportLimits()


class EventChannel:
    """Single-consumer retained event log with bounded live backpressure.

    Before a consumer claims the stream, producers may complete and retain the
    total bounded trace for execute-then-read integrations. Once a consumer is
    live, at most ``max_pending_events`` emitted events may remain undelivered.
    No event is dropped and no second unbounded queue duplicates retained
    evidence.
    """

    def __init__(self, *, max_pending_events: int = 256) -> None:
        if (
            not isinstance(max_pending_events, int)
            or isinstance(max_pending_events, bool)
            or max_pending_events < 1
        ):
            raise ValueError("max_pending_events must be a positive integer")
        self._max_pending_events = max_pending_events
        self._condition = asyncio.Condition()
        self._closed = False
        self._claimed = False
        self._events: list[TraceEvent] = []
        self._consumed = 0

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    @property
    def max_pending_events(self) -> int:
        return self._max_pending_events

    async def emit(self, event: TraceEvent) -> None:
        async with self._condition:
            while (
                self._claimed
                and len(self._events) - self._consumed >= self._max_pending_events
                and not self._closed
            ):
                await self._condition.wait()
            if self._closed:
                raise RuntimeError("event channel is closed")
            self._events.append(event)
            self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()

    async def iterate(self) -> AsyncIterator[TraceEvent]:
        async with self._condition:
            if self._claimed:
                raise RuntimeError("adapter event stream may be consumed only once")
            self._claimed = True
            self._condition.notify_all()

        cursor = 0
        while True:
            async with self._condition:
                await self._condition.wait_for(
                    lambda: cursor < len(self._events) or self._closed
                )
                if cursor >= len(self._events):
                    return
                item = self._events[cursor]
                cursor += 1
                self._consumed = cursor
                self._condition.notify_all()
            yield item


class JsonlResultParser:
    """Incrementally validate event/result records without buffering stdout."""

    def __init__(
        self,
        *,
        attempt: AttemptEnvelope,
        limits: AdapterTransportLimits,
        channel: EventChannel,
        source: str,
    ) -> None:
        self.attempt = attempt
        self.limits = limits
        self.channel = channel
        self.source = source
        self.total_bytes = 0
        self.event_count = 0
        self.previous_sequence = -1
        self.result: ResultBundle | None = None

    async def consume_line(self, raw_line: bytes) -> None:
        self.total_bytes += len(raw_line)
        if self.total_bytes > self.limits.max_response_bytes:
            raise TransportLimitExceeded(
                f"{self.source} response exceeded {self.limits.max_response_bytes} bytes"
            )
        if len(raw_line) > self.limits.max_jsonl_line_bytes:
            raise TransportLimitExceeded(
                f"{self.source} JSONL line exceeded {self.limits.max_jsonl_line_bytes} bytes"
            )
        line = raw_line.rstrip(b"\r\n")
        if not line:
            return
        if self.result is not None:
            raise ValueError(f"{self.source} emitted records after its terminal result")
        try:
            item = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{self.source} emitted malformed JSONL") from exc
        if not isinstance(item, dict) or set(item) not in ({"event"}, {"result"}):
            raise ValueError(
                f"{self.source} JSONL records must contain exactly event or result"
            )
        if "event" in item:
            self.event_count += 1
            if self.event_count > self.limits.max_events:
                raise TransportLimitExceeded(
                    f"{self.source} emitted more than {self.limits.max_events} events"
                )
            event = TraceEvent.model_validate_json(json.dumps(item["event"]))
            if (
                event.attempt_id != self.attempt.attempt_id
                or event.episode_id != self.attempt.episode_id
                or event.sequence <= self.previous_sequence
            ):
                raise ValueError(f"{self.source} emitted an invalid trace sequence")
            self.previous_sequence = event.sequence
            await self.channel.emit(event)
            return
        self.result = validate_result_for_attempt(
            ResultBundle.model_validate_json(json.dumps(item["result"])),
            self.attempt,
        )

    def finish(self) -> ResultBundle:
        if self.result is None:
            raise ValueError(f"{self.source} did not contain a result")
        validate_result_transport_limits(self.result, self.limits)
        return self.result


def parse_jsonl_response(
    content: bytes,
    *,
    attempt: AttemptEnvelope,
    limits: AdapterTransportLimits,
    source: str,
) -> tuple[tuple[TraceEvent, ...], ResultBundle]:
    """Validate a complete JSONL payload for compatibility and offline probes."""

    if len(content) > limits.max_response_bytes:
        raise TransportLimitExceeded(
            f"{source} response exceeded {limits.max_response_bytes} bytes"
        )
    events: list[TraceEvent] = []
    result: ResultBundle | None = None
    previous_sequence = -1
    for raw_line in content.splitlines(keepends=True):
        if len(raw_line) > limits.max_jsonl_line_bytes:
            raise TransportLimitExceeded(
                f"{source} JSONL line exceeded {limits.max_jsonl_line_bytes} bytes"
            )
        line = raw_line.rstrip(b"\r\n")
        if not line:
            continue
        if result is not None:
            raise ValueError(f"{source} emitted records after its terminal result")
        try:
            item = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{source} emitted malformed JSONL") from exc
        if not isinstance(item, dict) or set(item) not in ({"event"}, {"result"}):
            raise ValueError(
                f"{source} JSONL records must contain exactly event or result"
            )
        if "event" in item:
            if len(events) >= limits.max_events:
                raise TransportLimitExceeded(
                    f"{source} emitted more than {limits.max_events} events"
                )
            event = TraceEvent.model_validate_json(json.dumps(item["event"]))
            if (
                event.attempt_id != attempt.attempt_id
                or event.episode_id != attempt.episode_id
                or event.sequence <= previous_sequence
            ):
                raise ValueError(f"{source} emitted an invalid trace sequence")
            previous_sequence = event.sequence
            events.append(event)
            continue
        result = validate_result_for_attempt(
            ResultBundle.model_validate_json(json.dumps(item["result"])),
            attempt,
        )
    if result is None:
        raise ValueError(f"{source} did not contain a result")
    validate_result_transport_limits(result, limits)
    return tuple(events), result


async def read_bounded_stream(
    stream: Any,
    *,
    maximum: int,
    label: str,
    chunk_size: int = 64 * 1024,
) -> bytes:
    data = bytearray()
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > maximum:
            raise TransportLimitExceeded(f"{label} exceeded {maximum} bytes")


def validate_request_size(content: bytes, limits: AdapterTransportLimits, *, label: str) -> None:
    if len(content) > limits.max_request_bytes:
        raise TransportLimitExceeded(
            f"{label} request exceeded {limits.max_request_bytes} bytes"
        )


def validate_result_transport_limits(
    result: ResultBundle,
    limits: AdapterTransportLimits,
) -> None:
    total = 0
    for artifact in result.artifacts:
        size = _inline_size(artifact)
        if size is None:
            continue
        if size > limits.max_artifact_bytes:
            raise TransportLimitExceeded(
                f"artifact {artifact.artifact_id} exceeded {limits.max_artifact_bytes} bytes"
            )
        total += size
        if total > limits.max_total_artifact_bytes:
            raise TransportLimitExceeded(
                f"inline artifacts exceeded {limits.max_total_artifact_bytes} bytes"
            )


def _inline_size(artifact: ArtifactRef) -> int | None:
    return len(artifact.content) if artifact.content is not None else None


def invocation_environment(context: InvocationContext | None) -> dict[str, str]:
    if context is None:
        return {}
    values = {
        "SCAFFOLD_ARENA_INVOCATION_ID": context.invocation_id,
        "SCAFFOLD_ARENA_INVOCATION_GENERATION": str(context.generation),
        "SCAFFOLD_ARENA_FENCE_TOKEN": context.fence_token,
        "SCAFFOLD_ARENA_IDEMPOTENCY_KEY": context.provider_idempotency_key,
        "SCAFFOLD_ARENA_INVOCATION_DIGEST": context.context_digest,
    }
    if context.aggregate_deadline_at is not None:
        values["SCAFFOLD_ARENA_DEADLINE_AT"] = (
            context.aggregate_deadline_at.astimezone(UTC).isoformat()
        )
    return values


def invocation_headers(context: InvocationContext | None) -> dict[str, str]:
    if context is None:
        return {}
    values = {
        "Idempotency-Key": context.provider_idempotency_key,
        "X-Scaffold-Arena-Invocation-ID": context.invocation_id,
        "X-Scaffold-Arena-Invocation-Generation": str(context.generation),
        "X-Scaffold-Arena-Fence-Token": context.fence_token,
        "X-Scaffold-Arena-Invocation-Digest": context.context_digest,
    }
    if context.aggregate_deadline_at is not None:
        values["X-Scaffold-Arena-Deadline-At"] = (
            context.aggregate_deadline_at.astimezone(UTC).isoformat()
        )
    return values


def validate_connected_peer(
    *,
    response: Any,
    endpoint_host: str,
    required: bool,
) -> None:
    network_stream = response.extensions.get("network_stream")
    if network_stream is None:
        if required:
            raise ValueError("connected peer identity is unavailable")
        return
    address = None
    for name in ("server_addr", "peername"):
        try:
            address = network_stream.get_extra_info(name)
        except (AttributeError, OSError, RuntimeError):
            address = None
        if address:
            break
    if isinstance(address, (tuple, list)) and address:
        address = address[0]
    if not isinstance(address, str):
        if required:
            raise ValueError("connected peer identity is unavailable")
        return
    try:
        peer = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError as exc:
        raise ValueError("connected peer address is invalid") from exc
    normalized_host = endpoint_host.lower().rstrip(".")
    if normalized_host == "localhost":
        if not peer.is_loopback:
            raise ValueError("connected peer is not loopback")
        return
    try:
        expected = ipaddress.ip_address(normalized_host)
    except ValueError:
        if not peer.is_global:
            raise ValueError("connected peer is not a global address")
        return
    if expected != peer:
        raise ValueError("connected peer does not match the literal endpoint address")


def parse_json_response(
    content: bytes,
    *,
    attempt: AttemptEnvelope,
    limits: AdapterTransportLimits,
    source: str,
) -> tuple[tuple[TraceEvent, ...], ResultBundle]:
    if len(content) > limits.max_response_bytes:
        raise TransportLimitExceeded(
            f"{source} response exceeded {limits.max_response_bytes} bytes"
        )
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source} response is not valid JSON") from exc
    if (
        not isinstance(payload, Mapping)
        or set(payload) != {"events", "result"}
        or not isinstance(payload["events"], list)
    ):
        raise ValueError(f"{source} response must have exactly events and result")
    if len(payload["events"]) > limits.max_events:
        raise TransportLimitExceeded(
            f"{source} emitted more than {limits.max_events} events"
        )
    events = tuple(
        TraceEvent.model_validate_json(json.dumps(item))
        for item in payload["events"]
    )
    previous = -1
    for event in events:
        if (
            event.attempt_id != attempt.attempt_id
            or event.episode_id != attempt.episode_id
            or event.sequence <= previous
        ):
            raise ValueError(f"{source} emitted an invalid trace sequence")
        previous = event.sequence
    result = validate_result_for_attempt(
        ResultBundle.model_validate_json(json.dumps(payload["result"])),
        attempt,
    )
    validate_result_transport_limits(result, limits)
    return events, result
