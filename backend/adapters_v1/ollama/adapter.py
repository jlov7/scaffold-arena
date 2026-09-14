"""Native, fail-closed adapter for an explicitly installed local Ollama API."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import HarnessCapabilities, HarnessSpec, TraceEvent

from ..base import HarnessAdapter
from ..controlled_models import AttemptInput, ResultBundle
from ..controls import AppliedControls, ControlApplication, execution_controls_for
from ..models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    FailureClassification,
    PreparedAttempt,
    ProviderUsage,
    validate_events_for_attempt,
    validate_result_for_attempt,
)
from ..preflight import preflight

_MAX_IDENTITY_RESPONSE_BYTES = 256 * 1024
_MAX_CHAT_RESPONSE_BYTES = 1024 * 1024


class OllamaEvidenceHold(ValueError):
    pass


def validate_ollama_endpoint(endpoint: str) -> str:
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
    if path != "/api":
        raise ValueError("endpoint must be the installed /api base path")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def ollama_endpoint_digest(endpoint: str) -> str:
    return sha256({"ollama_local_endpoint": validate_ollama_endpoint(endpoint)})


def _response_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "model",
        "created_at",
        "done",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    ):
        value = payload.get(key)
        if isinstance(value, (str, int, bool)):
            summary[key] = value
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("role"), str) and isinstance(message.get("content"), str):
        summary["message"] = {"role": message["role"], "content": message["content"]}
    return summary


class OllamaAdapter(HarnessAdapter):
    def __init__(
        self,
        *,
        adapter_id: str,
        adapter_digest: str,
        endpoint: str,
        client: httpx.AsyncClient | None = None,
        config_schema_hash: str | None = None,
    ) -> None:
        self._endpoint = validate_ollama_endpoint(endpoint)
        self._endpoint_digest = ollama_endpoint_digest(self._endpoint)
        self._client = client or httpx.AsyncClient(
            follow_redirects=False, trust_env=False
        )
        self._owns_client = client is None
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id,
            adapter_digest=adapter_digest,
            adapter_kind="http",
            capabilities=HarnessCapabilities(usage=True),
            supported_isolation=("none",),
            claim_eligibility="live_provider",
            supports_cancellation=False,
            supports_artifacts=True,
            config_schema_hash=config_schema_hash,
        )
        self._attempts: dict[str, tuple[bytes, int, dict[str, Any]]] = {}
        self._events: dict[str, list[TraceEvent]] = {}
        self._results: dict[str, ResultBundle] = {}
        self._artifacts: dict[str, tuple[ArtifactRef, ...]] = {}
        self._ready: dict[str, asyncio.Event] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        try:
            version, _ = await self._read_json(
                "GET", f"{self._endpoint}/version", max_bytes=_MAX_IDENTITY_RESPONSE_BYTES
            )
            healthy = isinstance(version, dict) and isinstance(version.get("version"), str) and bool(version["version"])
        except (httpx.HTTPError, OllamaEvidenceHold, json.JSONDecodeError):
            healthy = False
        return AdapterHealth(
            healthy=healthy,
            checked_at=datetime.now(UTC),
            detail=("running local Ollama version endpoint verified; no runtime was started" if healthy else "configured local Ollama endpoint was not verified; no runtime was started"),
        )

    async def prepare_attempt(
        self, harness: HarnessSpec, input: AttemptInput
    ) -> PreparedAttempt:
        bound = AttemptInput.model_validate_json(
            canonical_json(input.model_dump(mode="json"))
        )
        preflight(self._capabilities, harness, bound)
        if (
            bound.attempt.endpoint_id is None
            or bound.attempt.pinned_endpoint_digest != self._endpoint_digest
        ):
            raise ValueError("attempt must bind this installed Ollama endpoint digest")
        if harness.configuration:
            raise ValueError(
                "provider endpoint and request profile are installed, not harness supplied"
            )
        identity = await self._runtime_identity(
            bound.attempt.provider_model, bound.attempt.budget.max_context_tokens
        )
        raw = canonical_json(bound.model_dump(mode="json"))
        self._attempts[bound.attempt.attempt_id] = (
            raw,
            harness.timeout_seconds,
            identity,
        )
        self._events[bound.attempt.attempt_id] = []
        self._ready[bound.attempt.attempt_id] = asyncio.Event()
        self._cleaned.discard(bound.attempt.attempt_id)
        return PreparedAttempt(
            attempt_id=bound.attempt.attempt_id,
            adapter_id=self._capabilities.adapter_id,
            prepared_at=datetime.now(UTC),
            timeout_seconds=harness.timeout_seconds,
            opaque_handle=bound.attempt.attempt_id,
            input_digest=sha256(bound.model_dump(mode="json")),
        )

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        if prepared.attempt_id in self._results:
            return self._results[prepared.attempt_id]
        bound, timeout, before_identity = self._attempt(prepared)
        attempt = bound.attempt
        try:
            if prepared.attempt_id in self._cancelled:
                self._append(
                    prepared, "system", "state", {"status": "cancelled_before_request"}
                )
                result = self._result(
                    attempt.attempt_id, "cancelled", "cancelled before provider request"
                )
            else:
                request = self._request(bound)
                self._append(
                    prepared,
                    "harness",
                    "request",
                    {
                        "endpoint_digest": self._endpoint_digest,
                        "runtime_identity_digest": before_identity[
                            "runtime_identity_digest"
                        ],
                        "request_digest": sha256(request),
                        "model": attempt.provider_model,
                    },
                )
                payload, raw_response = await self._read_json(
                    "POST",
                    f"{self._endpoint}/chat",
                    max_bytes=_MAX_CHAT_RESPONSE_BYTES,
                    content=canonical_json(request),
                    headers={"content-type": "application/json"},
                    timeout=timeout,
                )
                result = await self._complete_response(
                    prepared, payload, raw_response, before_identity
                )
        except OllamaEvidenceHold as exc:
            result = self._result(
                attempt.attempt_id,
                "incomplete",
                f"HOLD: {exc}",
                failure_classification="permanent_protocol",
            )
            self._append(
                prepared, "system", "error", {"error_type": "OllamaEvidenceHold"}
            )
        except httpx.TimeoutException:
            result = self._result(
                attempt.attempt_id,
                "timed_out",
                "local Ollama provider timeout",
                failure_classification="transient_provider",
            )
            self._append(prepared, "system", "error", {"error_type": "Timeout"})
        except httpx.HTTPStatusError as exc:
            result = self._result(
                attempt.attempt_id,
                "failed",
                f"local Ollama provider failure: {type(exc).__name__}",
                failure_classification=(
                    "transient_provider"
                    if exc.response.status_code >= 500
                    else "permanent_provider"
                ),
            )
            self._append(
                prepared, "system", "error", {"error_type": type(exc).__name__}
            )
        except (
            httpx.HTTPError,
            httpx.RequestError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            result = self._result(
                attempt.attempt_id,
                "failed",
                f"local Ollama provider failure: {type(exc).__name__}",
                failure_classification="permanent_provider",
            )
            self._append(
                prepared, "system", "error", {"error_type": type(exc).__name__}
            )
        finally:
            self._ready[prepared.attempt_id].set()
        self._results[prepared.attempt_id] = validate_result_for_attempt(
            result, attempt
        )
        return self._results[prepared.attempt_id]

    async def stream_events(
        self, prepared: PreparedAttempt
    ) -> AsyncIterator[TraceEvent]:
        self._attempt(prepared)
        await self._ready[prepared.attempt_id].wait()
        for event in validate_events_for_attempt(
            tuple(self._events.get(prepared.attempt_id, ())),
            self._attempt(prepared)[0].attempt,
        ):
            yield event

    async def collect_artifacts(
        self, prepared: PreparedAttempt
    ) -> tuple[ArtifactRef, ...]:
        self._attempt(prepared)
        return self._artifacts.get(prepared.attempt_id, ())

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        self._cancelled.add(prepared.attempt_id)
        if prepared.attempt_id not in self._results:
            self._append(
                prepared, "system", "state", {"status": "cancellation_requested"}
            )

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        if prepared.attempt_id in self._cleaned:
            return
        self._attempt(prepared)
        await self.cancel_attempt(prepared)
        attempt_id = prepared.attempt_id
        self._attempts.pop(attempt_id, None)
        self._events.pop(attempt_id, None)
        self._results.pop(attempt_id, None)
        self._artifacts.pop(attempt_id, None)
        self._ready.pop(attempt_id, None)
        self._cancelled.discard(attempt_id)
        self._cleaned.add(attempt_id)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _complete_response(
        self,
        prepared: PreparedAttempt,
        payload: object,
        raw_response: bytes,
        before_identity: dict[str, Any],
    ) -> ResultBundle:
        bound, _, _ = self._attempt(prepared)
        if not isinstance(payload, dict):
            raise OllamaEvidenceHold("Ollama response must be a JSON object")
        if (
            payload.get("model") != bound.attempt.provider_model
            or payload.get("done") is not True
        ):
            raise OllamaEvidenceHold(
                "Ollama response model or completion state does not match the bound request"
            )
        message = payload.get("message")
        if (
            not isinstance(message, dict)
            or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str)
        ):
            raise OllamaEvidenceHold(
                "Ollama response is missing an assistant text message"
            )
        input_tokens = self._integer(payload, "prompt_eval_count")
        output_tokens = self._integer(payload, "eval_count")
        tool_calls = message.get("tool_calls", [])
        if not isinstance(tool_calls, list) or tool_calls:
            raise OllamaEvidenceHold(
                "Ollama response contains unrequested or unverifiable tool calls"
            )
        after_identity = await self._runtime_identity(
            bound.attempt.provider_model, bound.attempt.budget.max_context_tokens
        )
        if after_identity != before_identity:
            raise OllamaEvidenceHold(
                "Ollama runtime identity changed during the attempt"
            )
        controls = execution_controls_for(bound)
        if controls.max_tool_calls != 0:
            raise OllamaEvidenceHold(
                "native Ollama admission supports only zero-tool attempts"
            )
        usage = ProviderUsage(
            evidence_source="provider_reported",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            context_tokens=input_tokens,
            tool_calls=0,
            provider_usage_digest=sha256(
                {"raw_response_sha256": sha256_bytes(raw_response), "runtime_identity": after_identity}
            ),
            observed_provider_version=after_identity["ollama_version"],
            observed_endpoint_digest=self._endpoint_digest,
        )
        output = message["content"].encode("utf-8")
        response_artifact = ArtifactRef(
            artifact_id="assistant-output",
            media_type="text/plain; charset=utf-8",
            sha256=sha256_bytes(output),
            content=output,
        )
        provider_summary_bytes = canonical_json(
            {
                "response": _response_summary(payload),
                "raw_response_sha256": sha256_bytes(raw_response),
            }
        )
        provider_response = ArtifactRef(
            artifact_id="provider-response-summary",
            media_type="application/json",
            sha256=sha256_bytes(provider_summary_bytes),
            content=provider_summary_bytes,
        )
        identity_bytes = canonical_json(
            {"before": before_identity, "after": after_identity}
        )
        identity_artifact = ArtifactRef(
            artifact_id="runtime-identity",
            media_type="application/vnd.scaffold-arena.ollama-runtime-identity+json",
            sha256=sha256_bytes(identity_bytes),
            content=identity_bytes,
        )
        usage_bytes = canonical_json(usage.model_dump(mode="json"))
        usage_artifact = ArtifactRef(
            artifact_id="provider-usage",
            media_type="application/json",
            sha256=sha256_bytes(usage_bytes),
            content=usage_bytes,
        )
        applications = tuple(
            ControlApplication(
                control_id=control_id,
                status=(
                    "applied"
                    if control_id
                    in {
                        "temperature",
                        "top_p",
                        "max_output_tokens",
                        "seed",
                        "max_context_tokens",
                    }
                    else "bound"
                ),
                requested_value=value,
                observed_value=value,
            )
            for control_id, value in controls.control_values().items()
        )
        applied = AppliedControls.bind(applications)
        applied_bytes = canonical_json(applied.model_dump(mode="json"))
        applied_artifact = ArtifactRef(
            artifact_id="applied-controls",
            media_type="application/vnd.scaffold-arena.applied-controls+json",
            sha256=sha256_bytes(applied_bytes),
            content=applied_bytes,
        )
        artifacts = (
            response_artifact,
            provider_response,
            identity_artifact,
            usage_artifact,
            applied_artifact,
        )
        self._artifacts[bound.attempt.attempt_id] = artifacts
        self._append(
            prepared,
            "model",
            "response",
            {
                "response_hash": response_artifact.sha256,
                "runtime_identity_digest": after_identity["runtime_identity_digest"],
                "text_hash": response_artifact.sha256,
            },
        )
        if prepared.attempt_id in self._cancelled:
            return self._result(
                bound.attempt.attempt_id,
                "cancelled",
                "cancellation requested while provider call drained",
                usage=usage,
                artifacts=artifacts,
            )
        return self._result(
            bound.attempt.attempt_id,
            "completed",
            None,
            response_hash=response_artifact.sha256,
            response_artifact_id="assistant-output",
            usage=usage,
            artifacts=artifacts,
            applied_controls=applied,
        )

    def _request(self, bound: AttemptInput) -> dict[str, Any]:
        controls = execution_controls_for(bound)
        if controls.max_tool_calls != 0:
            raise OllamaEvidenceHold(
                "native Ollama admission supports only zero-tool attempts"
            )
        return {
            "model": bound.attempt.provider_model,
            "messages": [{"role": "user", "content": bound.scenario.prompt}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": controls.temperature,
                "top_p": controls.top_p,
                "num_predict": controls.max_output_tokens,
                "seed": controls.seed,
                "num_ctx": controls.max_context_tokens,
            },
        }

    async def _runtime_identity(
        self, model: str, max_context_tokens: int
    ) -> dict[str, Any]:
        version, _ = await self._read_json(
            "GET", f"{self._endpoint}/version", max_bytes=_MAX_IDENTITY_RESPONSE_BYTES
        )
        tags, _ = await self._read_json(
            "GET", f"{self._endpoint}/tags", max_bytes=_MAX_IDENTITY_RESPONSE_BYTES
        )
        if (
            not isinstance(version, dict)
            or not isinstance(version.get("version"), str)
            or not version["version"]
        ):
            raise OllamaEvidenceHold("Ollama version response is missing a version")
        rows = tags.get("models") if isinstance(tags, dict) else None
        if not isinstance(rows, list):
            raise OllamaEvidenceHold("Ollama tags response is missing models")
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("name") == model
            and row.get("model") == model
        ]
        if len(matches) != 1:
            raise OllamaEvidenceHold(
                "bound Ollama model identity is absent or ambiguous"
            )
        row = matches[0]
        digest = row.get("digest")
        details = row.get("details")
        context_length = (
            details.get("context_length") if isinstance(details, dict) else None
        )
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise OllamaEvidenceHold("bound Ollama model digest is missing or invalid")
        if not isinstance(context_length, int) or context_length < max_context_tokens:
            raise OllamaEvidenceHold(
                "Ollama model does not attest the requested context window"
            )
        identity = {
            "endpoint": self._endpoint,
            "endpoint_digest": self._endpoint_digest,
            "ollama_version": version["version"],
            "model_name": model,
            "model_digest": digest,
            "context_length": context_length,
        }
        return {**identity, "runtime_identity_digest": sha256(identity)}

    async def _read_json(
        self,
        method: str,
        url: str,
        *,
        max_bytes: int,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 5,
    ) -> tuple[object, bytes]:
        self._observe_transport(method, url, "request", content or b"")
        async with self._client.stream(
            method,
            url,
            content=content,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                raise OllamaEvidenceHold("redirect responses are forbidden")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise OllamaEvidenceHold("Ollama response exceeds the configured byte limit")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise OllamaEvidenceHold("Ollama response exceeds the configured byte limit")
        raw = bytes(body)
        self._observe_transport(method, url, "response", raw)
        response.raise_for_status()
        try:
            return json.loads(raw), raw
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaEvidenceHold("Ollama response is not valid JSON") from exc

    def _observe_transport(self, method: str, url: str, phase: str, content: bytes) -> None:
        """Optional local custody hook; it cannot alter transport bytes."""

    def _attempt(
        self, prepared: PreparedAttempt
    ) -> tuple[AttemptInput, int, dict[str, Any]]:
        stored = self._attempts.get(prepared.attempt_id)
        if prepared.adapter_id != self._capabilities.adapter_id or stored is None:
            raise ValueError("prepared attempt is not owned by this adapter")
        bound = AttemptInput.model_validate_json(stored[0])
        if prepared.input_digest != sha256(bound.model_dump(mode="json")):
            raise ValueError("prepared attempt input binding mismatch")
        return bound, stored[1], stored[2]

    def _append(
        self,
        prepared: PreparedAttempt,
        actor: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        bound, _, _ = self._attempt(prepared)
        events = self._events[prepared.attempt_id]
        events.append(
            TraceEvent(
                trace_id=f"trace-{prepared.input_digest[:16]}",
                episode_id=bound.attempt.episode_id,
                attempt_id=bound.attempt.attempt_id,
                sequence=len(events),
                actor=actor,
                event_type=event_type,
                timestamp=datetime.now(UTC),
                monotonic_time=time.monotonic(),
                payload=payload,
                payload_hash=sha256(payload),
            )
        )  # type: ignore[arg-type]

    @staticmethod
    def _integer(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int) or value < 0:
            raise OllamaEvidenceHold(f"Ollama response is missing valid {key}")
        return value

    @staticmethod
    def _result(
        attempt_id: str,
        outcome: str,
        detail: str | None,
        *,
        response_hash: str | None = None,
        response_artifact_id: str | None = None,
        usage: ProviderUsage | None = None,
        artifacts: tuple[ArtifactRef, ...] = (),
        failure_classification: FailureClassification | None = None,
        applied_controls: AppliedControls | None = None,
    ) -> ResultBundle:
        return ResultBundle(
            attempt_id=attempt_id,
            terminal_outcome=outcome,
            completed_at=datetime.now(UTC),
            response_hash=response_hash,
            response_artifact_id=response_artifact_id,
            usage=usage,
            artifacts=artifacts,
            detail=detail,
            failure_classification=failure_classification,
            applied_controls=applied_controls,
        )  # type: ignore[arg-type]
