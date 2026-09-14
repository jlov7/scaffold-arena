"""Bounded HTTP RPC adapter with redirect, peer, and cancellation controls."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from protocol_v1.canonical import canonical_json, sha256
from protocol_v1.models import AttemptEnvelope, HarnessSpec, TraceEvent

from .base import HarnessAdapter
from .invocation import InvocationContext
from .models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    PreparedAttempt,
    ResultBundle,
    validate_result_for_attempt,
)
from .preflight import preflight
from .transport import (
    DEFAULT_TRANSPORT_LIMITS,
    AdapterTransportLimits,
    EventChannel,
    JsonlResultParser,
    TransportLimitExceeded,
    invocation_headers,
    parse_json_response,
    validate_connected_peer,
    validate_request_size,
    validate_result_transport_limits,
)


def validate_rpc_endpoint(endpoint: str, allowed_hosts: frozenset[str]) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "endpoint must be credential-free exact https or loopback http, without query or fragment"
        )
    host = parsed.hostname.lower().rstrip(".")
    if host not in allowed_hosts:
        raise ValueError("endpoint host is not on the adapter allowlist")
    is_loopback = host == "localhost"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host.endswith(".local") or host in {
            "metadata.google.internal",
            "metadata",
        }:
            raise ValueError("local and metadata hostnames are forbidden")
    else:
        is_loopback = address.is_loopback
        if not address.is_global and not is_loopback:
            raise ValueError(
                "private, link-local, and metadata IP addresses are forbidden"
            )
    if parsed.scheme == "http" and not is_loopback:
        raise ValueError("plain HTTP is permitted only for exact loopback endpoints")
    if parsed.scheme == "https" and is_loopback:
        raise ValueError("loopback endpoints must use the explicit local HTTP profile")
    return endpoint


@dataclass(frozen=True)
class _HttpAttempt:
    input_bytes: bytes
    timeout_seconds: int
    invocation: InvocationContext | None


class HttpRpcAdapter(HarnessAdapter):
    """Invoke an installed RPC endpoint with hard resource and SSRF boundaries."""

    def __init__(
        self,
        *,
        adapter_id: str,
        adapter_digest: str,
        endpoint: str,
        allowed_hosts: frozenset[str],
        client: httpx.AsyncClient | None = None,
        limits: AdapterTransportLimits | None = None,
        require_peer_validation: bool | None = None,
    ) -> None:
        self._endpoint = validate_rpc_endpoint(endpoint, allowed_hosts)
        self._endpoint_host = urlsplit(self._endpoint).hostname or ""
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None
        self._require_peer_validation = (
            self._owns_client
            if require_peer_validation is None
            else require_peer_validation
        )
        self._limits = limits or DEFAULT_TRANSPORT_LIMITS
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id,
            adapter_digest=adapter_digest,
            adapter_kind="http",
            supported_isolation=("remote_sandbox",),
            claim_eligibility="protocol_only",
            supports_cancellation=True,
            supports_artifacts=True,
        )
        self._attempts: dict[str, _HttpAttempt] = {}
        self._events: dict[str, tuple[TraceEvent, ...]] = {}
        self._results: dict[str, ResultBundle] = {}
        self._event_queues: dict[str, EventChannel] = {}
        self._execution_locks: dict[str, asyncio.Lock] = {}
        self._execution_tasks: dict[str, asyncio.Task[ResultBundle]] = {}
        self._responses: dict[str, httpx.Response] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        try:
            async with self._client.stream(
                "GET",
                self._endpoint,
                timeout=5,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    return AdapterHealth(
                        healthy=False,
                        checked_at=datetime.now(UTC),
                        detail="redirect responses are forbidden",
                    )
                validate_connected_peer(
                    response=response,
                    endpoint_host=self._endpoint_host,
                    required=self._require_peer_validation,
                )
                healthy = response.status_code < 400
                detail = f"HTTP {response.status_code}"
        except (httpx.HTTPError, ValueError) as exc:
            healthy, detail = False, f"HTTP error: {type(exc).__name__}"
        return AdapterHealth(
            healthy=healthy,
            checked_at=datetime.now(UTC),
            detail=detail,
        )

    async def prepare_attempt(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
    ) -> PreparedAttempt:
        return await self._prepare(harness, input, invocation=None)

    async def prepare_invocation(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
        context: InvocationContext,
    ) -> PreparedAttempt:
        if context.attempt_id != input.attempt.attempt_id:
            raise ValueError("invocation context does not bind the prepared attempt")
        return await self._prepare(harness, input, invocation=context)

    async def _prepare(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
        *,
        invocation: InvocationContext | None,
    ) -> PreparedAttempt:
        bound = AttemptInput.model_validate_json(
            canonical_json(input.model_dump(mode="json"))
        )
        preflight(self._capabilities, harness, bound)
        attempt = bound.attempt
        if harness.configuration:
            raise ValueError(
                "HTTP adapter endpoint and request shape are installed, not harness supplied"
            )
        if attempt.attempt_id in self._attempts and attempt.attempt_id not in self._cleaned:
            raise ValueError("attempt is already prepared by this adapter")
        input_bytes = canonical_json(bound.model_dump(mode="json"))
        validate_request_size(input_bytes, self._limits, label="HTTP RPC")
        self._attempts[attempt.attempt_id] = _HttpAttempt(
            input_bytes=input_bytes,
            timeout_seconds=harness.timeout_seconds,
            invocation=invocation,
        )
        self._event_queues[attempt.attempt_id] = EventChannel(
            max_pending_events=self._limits.max_pending_events
        )
        self._execution_locks[attempt.attempt_id] = asyncio.Lock()
        self._events.pop(attempt.attempt_id, None)
        self._results.pop(attempt.attempt_id, None)
        self._cancelled.discard(attempt.attempt_id)
        self._cleaned.discard(attempt.attempt_id)
        return PreparedAttempt(
            attempt_id=attempt.attempt_id,
            adapter_id=self._capabilities.adapter_id,
            prepared_at=datetime.now(UTC),
            timeout_seconds=harness.timeout_seconds,
            opaque_handle=attempt.attempt_id,
            input_digest=sha256(bound.model_dump(mode="json")),
        )

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        if prepared.attempt_id in self._results:
            return self._results[prepared.attempt_id]
        stored, bound = self._attempt(prepared)
        async with self._execution_locks[prepared.attempt_id]:
            if prepared.attempt_id in self._results:
                return self._results[prepared.attempt_id]
            channel = self._event_queues[prepared.attempt_id]
            if prepared.attempt_id in self._cancelled:
                result = self._cancelled_result(prepared.attempt_id, "cancelled before HTTP dispatch")
                self._results[prepared.attempt_id] = result
                await channel.close()
                return result

            current = asyncio.current_task()
            if current is None:
                raise RuntimeError("HTTP adapter execution requires an asyncio task")
            self._execution_tasks[prepared.attempt_id] = current  # type: ignore[assignment]
            headers = {
                "content-type": "application/json",
                "accept": "application/json, application/x-ndjson",
                **invocation_headers(stored.invocation),
            }
            try:
                async with self._client.stream(
                    "POST",
                    self._endpoint,
                    content=stored.input_bytes,
                    headers=headers,
                    timeout=stored.timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    self._responses[prepared.attempt_id] = response
                    if response.is_redirect:
                        raise ValueError("redirect responses are forbidden")
                    validate_connected_peer(
                        response=response,
                        endpoint_host=self._endpoint_host,
                        required=self._require_peer_validation,
                    )
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if media_type in {
                        "application/x-ndjson",
                        "application/jsonl",
                        "application/json-seq",
                    }:
                        result = await self._consume_ndjson(response, bound.attempt, channel)
                    else:
                        content = await self._read_response(response)
                        events, result = self._parse_json_bytes(content, bound.attempt)
                        for event in events:
                            await channel.emit(event)
                if prepared.attempt_id in self._cancelled:
                    result = self._cancelled_result(
                        prepared.attempt_id,
                        "HTTP cancellation requested while response drained",
                    )
                validate_result_transport_limits(result, self._limits)
                self._events[prepared.attempt_id] = channel.events
                self._results[prepared.attempt_id] = validate_result_for_attempt(
                    result,
                    bound.attempt,
                )
                return self._results[prepared.attempt_id]
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and hasattr(task, "uncancel"):
                    task.uncancel()
                result = self._cancelled_result(
                    prepared.attempt_id,
                    "HTTP execution cancelled",
                )
                self._results[prepared.attempt_id] = result
                return result
            except httpx.TimeoutException:
                result = ResultBundle(
                    attempt_id=prepared.attempt_id,
                    terminal_outcome="timed_out",
                    completed_at=datetime.now(UTC),
                    detail="HTTP timeout",
                    failure_classification="transient_provider",
                )
                self._results[prepared.attempt_id] = result
                return result
            except httpx.HTTPStatusError as exc:
                result = ResultBundle(
                    attempt_id=prepared.attempt_id,
                    terminal_outcome="failed",
                    completed_at=datetime.now(UTC),
                    detail=f"HTTP {exc.response.status_code}",
                    failure_classification=(
                        "transient_provider"
                        if exc.response.status_code >= 500
                        else "permanent_provider"
                    ),
                )
                self._results[prepared.attempt_id] = result
                return result
            except httpx.RequestError as exc:
                result = ResultBundle(
                    attempt_id=prepared.attempt_id,
                    terminal_outcome="failed",
                    completed_at=datetime.now(UTC),
                    detail=f"HTTP transport failure: {type(exc).__name__}",
                    failure_classification="transient_provider",
                )
                self._results[prepared.attempt_id] = result
                return result
            finally:
                self._responses.pop(prepared.attempt_id, None)
                self._execution_tasks.pop(prepared.attempt_id, None)
                await channel.close()

    async def _read_response(self, response: httpx.Response) -> bytes:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > self._limits.max_response_bytes:
                raise TransportLimitExceeded(
                    f"HTTP response exceeded {self._limits.max_response_bytes} bytes"
                )
        return bytes(content)

    async def _consume_ndjson(
        self,
        response: httpx.Response,
        attempt: AttemptEnvelope,
        channel: EventChannel,
    ) -> ResultBundle:
        parser = JsonlResultParser(
            attempt=attempt,
            limits=self._limits,
            channel=channel,
            source="HTTP RPC",
        )
        buffer = bytearray()
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._limits.max_response_bytes:
                raise TransportLimitExceeded(
                    f"HTTP response exceeded {self._limits.max_response_bytes} bytes"
                )
            buffer.extend(chunk)
            while True:
                newline = buffer.find(b"\n")
                if newline < 0:
                    if len(buffer) > self._limits.max_jsonl_line_bytes:
                        raise TransportLimitExceeded(
                            "HTTP RPC JSONL line exceeded the configured limit"
                        )
                    break
                line = bytes(buffer[: newline + 1])
                del buffer[: newline + 1]
                await parser.consume_line(line)
        if buffer:
            await parser.consume_line(bytes(buffer))
        return parser.finish()

    def _parse_json_bytes(
        self,
        content: bytes,
        attempt: AttemptEnvelope,
    ) -> tuple[tuple[TraceEvent, ...], ResultBundle]:
        try:
            return parse_json_response(
                content,
                attempt=attempt,
                limits=self._limits,
                source="HTTP RPC",
            )
        except ValidationError as exc:
            raise ValueError("HTTP RPC response violates adapter contract") from exc

    def _parse_payload(
        self,
        payload: object,
        attempt: AttemptEnvelope,
    ) -> tuple[tuple[TraceEvent, ...], ResultBundle]:
        try:
            content = canonical_json(payload)
            return self._parse_json_bytes(content, attempt)
        except (TypeError, ValueError, ValidationError) as exc:
            if isinstance(exc, TransportLimitExceeded):
                raise
            if "violates adapter contract" in str(exc):
                raise
            raise ValueError("HTTP RPC response violates adapter contract") from exc

    async def stream_events(
        self,
        prepared: PreparedAttempt,
    ) -> AsyncIterator[TraceEvent]:
        self._attempt(prepared)
        async for event in self._event_queues[prepared.attempt_id].iterate():
            yield event

    async def collect_artifacts(
        self,
        prepared: PreparedAttempt,
    ) -> tuple[ArtifactRef, ...]:
        self._attempt(prepared)
        result = self._results.get(prepared.attempt_id)
        return () if result is None else result.artifacts

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        if prepared.attempt_id in self._cleaned:
            return
        self._attempt(prepared)
        self._cancelled.add(prepared.attempt_id)
        response = self._responses.get(prepared.attempt_id)
        if response is not None:
            with contextlib.suppress(httpx.HTTPError, RuntimeError):
                await response.aclose()
        task = self._execution_tasks.get(prepared.attempt_id)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        channel = self._event_queues.get(prepared.attempt_id)
        if channel is not None:
            await channel.close()

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        if prepared.attempt_id in self._cleaned:
            return
        self._attempt(prepared)
        await self.cancel_attempt(prepared)
        attempt_id = prepared.attempt_id
        self._attempts.pop(attempt_id, None)
        self._events.pop(attempt_id, None)
        self._results.pop(attempt_id, None)
        self._event_queues.pop(attempt_id, None)
        self._execution_locks.pop(attempt_id, None)
        self._execution_tasks.pop(attempt_id, None)
        self._responses.pop(attempt_id, None)
        self._cancelled.discard(attempt_id)
        self._cleaned.add(attempt_id)

    async def aclose(self) -> None:
        for attempt_id, response in tuple(self._responses.items()):
            with contextlib.suppress(httpx.HTTPError, RuntimeError):
                await response.aclose()
            self._responses.pop(attempt_id, None)
        if self._owns_client:
            await self._client.aclose()

    def _attempt(
        self,
        prepared: PreparedAttempt,
    ) -> tuple[_HttpAttempt, AttemptInput]:
        stored = self._attempts.get(prepared.attempt_id)
        if prepared.adapter_id != self._capabilities.adapter_id or stored is None:
            raise ValueError("prepared attempt is not owned by this adapter")
        bound = AttemptInput.model_validate_json(stored.input_bytes)
        if prepared.input_digest != sha256(bound.model_dump(mode="json")):
            raise ValueError("prepared attempt input binding mismatch")
        return stored, bound

    @staticmethod
    def _cancelled_result(attempt_id: str, detail: str) -> ResultBundle:
        return ResultBundle(
            attempt_id=attempt_id,
            terminal_outcome="cancelled",
            completed_at=datetime.now(UTC),
            detail=detail,
        )
