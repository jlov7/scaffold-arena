"""OpenAI-compatible adapter with an immutable local endpoint boundary.

This module intentionally contains no process launcher, model discovery, or
credential lookup.  A caller installs an endpoint and HTTP client explicitly.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import HarnessSpec, TraceEvent

from ..base import HarnessAdapter
from ..models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    FailureClassification,
    PreparedAttempt,
    ProviderUsage,
    ResultBundle,
    validate_events_for_attempt,
    validate_result_for_attempt,
)
from ..preflight import preflight


def validate_local_endpoint(endpoint: str) -> str:
    """Accept only a credential-free literal loopback HTTP(S) endpoint."""
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("endpoint must not contain credentials, query, or fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("endpoint host must be a literal loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("only literal loopback endpoints are permitted")
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1/chat/completions"):
        raise ValueError("endpoint must be the installed /v1/chat/completions path")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def endpoint_digest(endpoint: str) -> str:
    """Hash the normalized installed endpoint; never accept a caller pin."""
    return sha256({"openai_compatible_local_endpoint": validate_local_endpoint(endpoint)})


class OpenAICompatibleAdapter(HarnessAdapter):
    def __init__(
        self,
        *,
        adapter_id: str,
        adapter_digest: str,
        endpoint: str,
        client: httpx.AsyncClient | None = None,
        headers: Mapping[str, str] | None = None,
        config_schema_hash: str | None = None,
    ) -> None:
        self._endpoint = validate_local_endpoint(endpoint)
        self._endpoint_digest = endpoint_digest(self._endpoint)
        self._client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False)
        self._owns_client = client is None
        # Headers can contain a local bearer token, but never leave this object.
        self._headers = dict(headers or {})
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id,
            adapter_digest=adapter_digest,
            adapter_kind="http",
            supported_isolation=("none",),
            claim_eligibility="protocol_only",
            supports_cancellation=True,
            supports_artifacts=True,
            config_schema_hash=config_schema_hash,
        )
        self._attempts: dict[str, tuple[bytes, int]] = {}
        self._events: dict[str, list[TraceEvent]] = {}
        self._results: dict[str, ResultBundle] = {}
        self._artifacts: dict[str, tuple[ArtifactRef, ...]] = {}
        self._ready: dict[str, asyncio.Event] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        # A healthcheck is intentionally local-only.  It must not wake/start a model.
        return AdapterHealth(healthy=True, checked_at=datetime.now(UTC), detail="installed loopback endpoint and immutable digest verified")

    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        bound = AttemptInput.model_validate_json(canonical_json(input.model_dump(mode="json")))
        preflight(self._capabilities, harness, bound)
        attempt = bound.attempt
        if attempt.endpoint_id is None or attempt.pinned_endpoint_digest != self._endpoint_digest:
            raise ValueError("attempt must bind this installed endpoint digest")
        if harness.configuration:
            raise ValueError("provider endpoint, credentials, and request profile are installed, not harness supplied")
        raw = canonical_json(bound.model_dump(mode="json"))
        self._attempts[attempt.attempt_id] = (raw, harness.timeout_seconds)
        self._events[attempt.attempt_id] = []
        self._ready[attempt.attempt_id] = asyncio.Event()
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
        bound, timeout = self._attempt(prepared)
        attempt = bound.attempt
        try:
            if prepared.attempt_id in self._cancelled:
                self._append(prepared, "system", "state", {"status": "cancelled_before_request"})
                result = self._result(attempt.attempt_id, "cancelled", "cancelled before provider request")
            else:
                request = self._request(bound)
                self._append(prepared, "harness", "request", {"endpoint_digest": self._endpoint_digest, "request_digest": sha256(request), "model": attempt.provider_model})
                response = await self._client.post(
                    self._endpoint,
                    content=canonical_json(request),
                    headers={"content-type": "application/json", **self._headers},
                    timeout=timeout,
                    follow_redirects=False,
                )
                if response.is_redirect:
                    raise ValueError("redirect responses are forbidden")
                response.raise_for_status()
                result = self._complete_response(prepared, response)
        except httpx.TimeoutException:
            result = self._result(
                attempt.attempt_id, "timed_out", "local provider timeout",
                failure_classification="transient_provider",
            )
            self._append(prepared, "system", "error", {"error_type": "Timeout"})
        except httpx.HTTPStatusError as exc:
            result = self._result(
                attempt.attempt_id, "failed", f"local provider failure: {type(exc).__name__}",
                failure_classification=("transient_provider" if exc.response.status_code >= 500 else "permanent_provider"),
            )
            self._append(prepared, "system", "error", {"error_type": type(exc).__name__})
        except httpx.RequestError as exc:
            result = self._result(
                attempt.attempt_id, "failed", f"local provider failure: {type(exc).__name__}",
                failure_classification="transient_provider",
            )
            self._append(prepared, "system", "error", {"error_type": type(exc).__name__})
        except (httpx.HTTPError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result = self._result(
                attempt.attempt_id, "failed", f"local provider failure: {type(exc).__name__}",
                failure_classification="permanent_provider",
            )
            self._append(prepared, "system", "error", {"error_type": type(exc).__name__})
        finally:
            self._ready[prepared.attempt_id].set()
        self._results[prepared.attempt_id] = validate_result_for_attempt(result, attempt)
        return self._results[prepared.attempt_id]

    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]:
        self._attempt(prepared)
        await self._ready[prepared.attempt_id].wait()
        events = validate_events_for_attempt(tuple(self._events.get(prepared.attempt_id, ())), self._attempt(prepared)[0].attempt)
        for event in events:
            yield event

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        self._attempt(prepared)
        return self._artifacts.get(prepared.attempt_id, ())

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        self._cancelled.add(prepared.attempt_id)
        if prepared.attempt_id not in self._results:
            self._append(prepared, "system", "state", {"status": "cancellation_requested"})

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        if prepared.attempt_id in self._cleaned:
            return
        await self.cancel_attempt(prepared)
        self._cleaned.add(prepared.attempt_id)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _complete_response(self, prepared: PreparedAttempt, response: httpx.Response) -> ResultBundle:
        bound, _ = self._attempt(prepared)
        attempt = bound.attempt
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("provider response must be a JSON object")
        text = _response_text(payload)
        usage = _provider_usage(payload.get("usage"), response.headers, self._endpoint_digest)
        output_bytes = text.encode("utf-8")
        response_hash = sha256_bytes(output_bytes)
        response_artifact = ArtifactRef(
            artifact_id="assistant-output", media_type="text/plain; charset=utf-8",
            sha256=response_hash, content=output_bytes,
        )
        raw = response.content
        provider_response = ArtifactRef(
            artifact_id="provider-response", media_type="application/json",
            sha256=sha256_bytes(raw), content=raw,
        )
        artifacts: list[ArtifactRef] = [response_artifact, provider_response]
        if usage is not None:
            usage_bytes = canonical_json(usage.model_dump(mode="json"))
            artifacts.append(ArtifactRef(artifact_id="provider-usage", media_type="application/json", sha256=sha256_bytes(usage_bytes), content=usage_bytes))
        self._artifacts[attempt.attempt_id] = tuple(artifacts)
        request_id = response.headers.get("x-request-id")
        self._append(prepared, "model", "response", {"response_hash": response_hash, "provider_request_id": request_id or "UNKNOWN", "text_hash": sha256_bytes(text.encode("utf-8"))})
        if prepared.attempt_id in self._cancelled:
            return self._result(attempt.attempt_id, "cancelled", "cancellation requested while provider call drained", usage=usage, artifacts=tuple(artifacts))
        if usage is None or not usage.complete_evidence:
            return self._result(
                attempt.attempt_id, "incomplete",
                "HOLD: provider, endpoint, token, context, and tool evidence required for completed result",
                response_hash=response_hash, response_artifact_id="assistant-output",
                usage=usage, artifacts=tuple(artifacts), failure_classification="permanent_protocol",
            )
        return self._result(
            attempt.attempt_id, "completed", None,
            response_hash=response_hash, response_artifact_id="assistant-output",
            usage=usage, artifacts=tuple(artifacts),
        )

    def _request(self, bound: AttemptInput) -> dict[str, Any]:
        return {
            "model": bound.attempt.provider_model,
            "messages": [{"role": "user", "content": bound.scenario.prompt}],
            "stream": False,
        }

    def _attempt(self, prepared: PreparedAttempt) -> tuple[AttemptInput, int]:
        stored = self._attempts.get(prepared.attempt_id)
        if prepared.adapter_id != self._capabilities.adapter_id or stored is None:
            raise ValueError("prepared attempt is not owned by this adapter")
        bound = AttemptInput.model_validate_json(stored[0])
        if prepared.input_digest != sha256(bound.model_dump(mode="json")):
            raise ValueError("prepared attempt input binding mismatch")
        return bound, stored[1]

    def _append(self, prepared: PreparedAttempt, actor: str, event_type: str, payload: dict[str, Any]) -> None:
        bound, _ = self._attempt(prepared)
        events = self._events[prepared.attempt_id]
        events.append(TraceEvent(
            trace_id=f"trace-{prepared.input_digest[:16]}",
            episode_id=bound.attempt.episode_id,
            attempt_id=bound.attempt.attempt_id,
            sequence=len(events),
            actor=actor,  # type: ignore[arg-type]
            event_type=event_type,  # type: ignore[arg-type]
            timestamp=datetime.now(UTC),
            monotonic_time=time.monotonic(),
            payload=payload,
            payload_hash=sha256(payload),
        ))

    @staticmethod
    def _result(attempt_id: str, outcome: str, detail: str | None, *, response_hash: str | None = None, response_artifact_id: str | None = None, usage: ProviderUsage | None = None, artifacts: tuple[ArtifactRef, ...] = (), failure_classification: FailureClassification | None = None) -> ResultBundle:
        return ResultBundle(attempt_id=attempt_id, terminal_outcome=outcome, completed_at=datetime.now(UTC), response_hash=response_hash, response_artifact_id=response_artifact_id, usage=usage, artifacts=artifacts, detail=detail, failure_classification=failure_classification)  # type: ignore[arg-type]


def _response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("provider response is missing choices")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise TypeError("provider response is missing text content")
    return message["content"]


def _provider_usage(raw: object, headers: httpx.Headers, pinned_endpoint_digest: str) -> ProviderUsage | None:
    if not isinstance(raw, dict):
        return None
    provider_version = headers.get("x-scaffold-provider-version")
    observed_endpoint = headers.get("x-scaffold-endpoint-digest")
    values = {
        "input_tokens": raw.get("prompt_tokens"),
        "output_tokens": raw.get("completion_tokens"),
        "total_tokens": raw.get("total_tokens"),
        "context_tokens": raw.get("context_tokens"),
        "tool_calls": raw.get("tool_calls"),
    }
    if any(value is not None and (not isinstance(value, int) or value < 0) for value in values.values()):
        raise ValueError("provider usage values must be non-negative integers")
    if observed_endpoint is not None and observed_endpoint != pinned_endpoint_digest:
        raise ValueError("provider observed endpoint digest does not match immutable pin")
    receipt = {"usage": raw, "provider_version": provider_version, "endpoint_digest": observed_endpoint}
    return ProviderUsage(
        evidence_source="provider_reported",
        input_tokens=values["input_tokens"],
        output_tokens=values["output_tokens"],
        total_tokens=values["total_tokens"],
        context_tokens=values["context_tokens"],
        tool_calls=values["tool_calls"],
        actual_cost_usd=raw.get("actual_cost_usd") if isinstance(raw.get("actual_cost_usd"), (int, float)) and raw.get("actual_cost_usd") >= 0 else None,
        provider_usage_digest=sha256(receipt),
        observed_provider_version=provider_version,
        observed_endpoint_digest=observed_endpoint,
    )
