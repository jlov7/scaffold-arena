"""Native, fail-closed adapter for an explicitly running local LM Studio API."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
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

_MAX_MODELS_RESPONSE_BYTES = 256 * 1024
_MAX_CHAT_RESPONSE_BYTES = 1024 * 1024
# A UTF-8 byte can require up to one tokenizer token, while typical text uses
# several bytes per token.  Keeping at most 16 bytes per declared context token
# is a conservative tokenizer-independent admission bound; it prevents a pack
# from making the local runtime parse an arbitrarily larger prompt before usage
# evidence can be checked.
_MAX_PROMPT_UTF8_BYTES_PER_CONTEXT_TOKEN = 16


class LMStudioEvidenceHold(ValueError):
    pass


def validate_lm_studio_endpoint(endpoint: str) -> str:
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
    if path != "/api/v1":
        raise ValueError("endpoint must be the installed /api/v1 base path")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def lm_studio_endpoint_digest(endpoint: str) -> str:
    return sha256({"lm_studio_local_endpoint": validate_lm_studio_endpoint(endpoint)})


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    model_instance_id = payload.get("model_instance_id")
    if isinstance(model_instance_id, str):
        summary["model_instance_id"] = model_instance_id
    output = payload.get("output")
    if isinstance(output, list):
        messages = [
            {"type": "message", "content": item["content"]}
            for item in output
            if isinstance(item, dict)
            and item.get("type") == "message"
            and isinstance(item.get("content"), str)
        ]
        summary["output"] = messages
    stats = payload.get("stats")
    if isinstance(stats, dict):
        summary["stats"] = {
            key: value
            for key, value in stats.items()
            if key
            in {
                "input_tokens",
                "total_output_tokens",
                "reasoning_output_tokens",
                "tokens_per_second",
                "time_to_first_token_seconds",
                "model_load_time_seconds",
            }
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
    return summary


class LMStudioAdapter(HarnessAdapter):
    def __init__(
        self,
        *,
        adapter_id: str,
        adapter_digest: str,
        endpoint: str,
        runtime_revision: str,
        model_artifact_digest: str,
        client: httpx.AsyncClient | None = None,
        config_schema_hash: str | None = None,
    ) -> None:
        self._endpoint = validate_lm_studio_endpoint(endpoint)
        self._endpoint_digest = lm_studio_endpoint_digest(self._endpoint)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", runtime_revision):
            raise ValueError("runtime_revision must be a bounded non-empty operator revision")
        if not re.fullmatch(r"[a-f0-9]{64}", model_artifact_digest):
            raise ValueError("model_artifact_digest must be a lowercase SHA-256 digest")
        # Native v1 exposes neither server version nor model file digests. These
        # values are operator attestations only, never provider-observed facts.
        self._runtime_revision = runtime_revision
        self._model_artifact_digest = model_artifact_digest
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
            payload, _ = await self._read_json(
                "GET", f"{self._endpoint}/models", max_bytes=_MAX_MODELS_RESPONSE_BYTES
            )
            healthy = self._models_payload(payload) is not None
        except (httpx.HTTPError, LMStudioEvidenceHold, json.JSONDecodeError):
            healthy = False
        return AdapterHealth(
            healthy=healthy,
            checked_at=datetime.now(UTC),
            detail=(
                "running local LM Studio models endpoint verified; no runtime was started"
                if healthy
                else "configured local LM Studio endpoint was not verified; no runtime was started"
            ),
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
            raise ValueError(
                "attempt must bind this installed LM Studio endpoint digest"
            )
        if harness.configuration:
            raise ValueError(
                "provider endpoint and request profile are installed, not harness supplied"
            )
        identity = await self._runtime_identity(
            bound.attempt.provider_model, bound.attempt.budget.max_context_tokens
        )
        self._attempts[bound.attempt.attempt_id] = (
            canonical_json(bound.model_dump(mode="json")),
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
        except LMStudioEvidenceHold as exc:
            result = self._result(
                attempt.attempt_id,
                "incomplete",
                f"HOLD: {exc}",
                failure_classification="permanent_protocol",
            )
            self._append(
                prepared, "system", "error", {"error_type": "LMStudioEvidenceHold"}
            )
        except httpx.TimeoutException:
            result = self._result(
                attempt.attempt_id,
                "timed_out",
                "local LM Studio provider timeout",
                failure_classification="transient_provider",
            )
            self._append(prepared, "system", "error", {"error_type": "Timeout"})
        except httpx.HTTPStatusError as exc:
            result = self._result(
                attempt.attempt_id,
                "failed",
                f"local LM Studio provider failure: {type(exc).__name__}",
                failure_classification="transient_provider"
                if exc.response.status_code >= 500
                else "permanent_provider",
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
                f"local LM Studio provider failure: {type(exc).__name__}",
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
            raise LMStudioEvidenceHold("LM Studio response must be a JSON object")
        if payload.get("response_id") is not None:
            raise LMStudioEvidenceHold(
                "LM Studio response retained state despite store=false"
            )
        if payload.get("model_instance_id") != before_identity["model_instance_id"]:
            raise LMStudioEvidenceHold(
                "LM Studio response model instance does not match the bound request"
            )
        output = payload.get("output")
        if not isinstance(output, list) or not output:
            raise LMStudioEvidenceHold("LM Studio response is missing output items")
        messages: list[str] = []
        for item in output:
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise LMStudioEvidenceHold(
                    "LM Studio response contains malformed output"
                )
            if item["type"] == "message" and isinstance(item.get("content"), str):
                messages.append(item["content"])
                continue
            if item["type"] == "reasoning":
                raise LMStudioEvidenceHold(
                    "LM Studio emitted reasoning despite reasoning=off"
                )
            raise LMStudioEvidenceHold(
                "LM Studio response contains an unrequested or unverifiable tool output"
            )
        if not messages:
            raise LMStudioEvidenceHold(
                "LM Studio response is missing an assistant text message"
            )
        stats = payload.get("stats")
        if not isinstance(stats, dict):
            raise LMStudioEvidenceHold("LM Studio response is missing usage stats")
        input_tokens = self._integer(stats, "input_tokens")
        output_tokens = self._integer(stats, "total_output_tokens")
        if self._integer(stats, "reasoning_output_tokens") != 0:
            raise LMStudioEvidenceHold(
                "LM Studio response reported reasoning usage despite reasoning=off"
            )
        after_identity = await self._runtime_identity(
            bound.attempt.provider_model, bound.attempt.budget.max_context_tokens
        )
        if after_identity != before_identity:
            raise LMStudioEvidenceHold(
                "LM Studio runtime identity changed during the attempt"
            )
        controls = execution_controls_for(bound)
        if controls.max_tool_calls != 0:
            raise LMStudioEvidenceHold(
                "native LM Studio admission supports only zero-tool attempts"
            )
        usage = ProviderUsage(
            evidence_source="provider_reported",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            context_tokens=input_tokens,
            tool_calls=0,
            provider_usage_digest=sha256(
                {
                    "raw_response_sha256": sha256_bytes(raw_response),
                    "runtime_identity": after_identity,
                }
            ),
            observed_endpoint_digest=self._endpoint_digest,
            operator_attested_runtime_revision=self._runtime_revision,
        )
        output_bytes = "\n".join(messages).encode("utf-8")
        response_artifact = ArtifactRef(
            artifact_id="assistant-output",
            media_type="text/plain; charset=utf-8",
            sha256=sha256_bytes(output_bytes),
            content=output_bytes,
        )
        summary_bytes = canonical_json(
            {
                "response": _summary(payload),
                "raw_response_sha256": sha256_bytes(raw_response),
            }
        )
        summary_artifact = ArtifactRef(
            artifact_id="provider-response-summary",
            media_type="application/json",
            sha256=sha256_bytes(summary_bytes),
            content=summary_bytes,
        )
        identity_bytes = canonical_json(
            {"before": before_identity, "after": after_identity}
        )
        identity_artifact = ArtifactRef(
            artifact_id="runtime-identity",
            media_type="application/vnd.scaffold-arena.lm-studio-runtime-identity+json",
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
                status="unsupported"
                if control_id == "seed"
                else "bound"
                if control_id == "max_context_tokens"
                else "applied"
                if control_id
                in {
                    "temperature",
                    "top_p",
                    "max_output_tokens",
                }
                else "bound",
                requested_value=value,
                observed_value=None if control_id == "seed" else value,
                detail=(
                    "LM Studio native v1 API does not expose a seed control"
                    if control_id == "seed"
                    else "Scaffold Arena bounds input context; the loaded instance context is attested separately"
                    if control_id == "max_context_tokens"
                    else None
                ),
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
            summary_artifact,
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
            "incomplete",
            "HOLD: LM Studio native v1 API does not expose a verifiable provider runtime version; operator attestation is recorded separately",
            response_hash=response_artifact.sha256,
            response_artifact_id="assistant-output",
            usage=usage,
            artifacts=artifacts,
            applied_controls=applied,
            failure_classification="permanent_protocol",
        )

    def _request(self, bound: AttemptInput) -> dict[str, Any]:
        controls = execution_controls_for(bound)
        if controls.max_tool_calls != 0:
            raise LMStudioEvidenceHold(
                "native LM Studio admission supports only zero-tool attempts"
            )
        prompt_bytes = bound.scenario.prompt.encode("utf-8")
        max_prompt_bytes = (
            controls.max_context_tokens * _MAX_PROMPT_UTF8_BYTES_PER_CONTEXT_TOKEN
        )
        if len(prompt_bytes) > max_prompt_bytes:
            raise LMStudioEvidenceHold(
                "LM Studio prompt exceeds the tokenizer-independent context byte cap"
            )
        return {
            "model": bound.attempt.provider_model,
            "input": bound.scenario.prompt,
            "stream": False,
            "store": False,
            "reasoning": "off",
            "temperature": controls.temperature,
            "top_p": controls.top_p,
            "max_output_tokens": controls.max_output_tokens,
        }

    async def _runtime_identity(
        self, model: str, max_context_tokens: int
    ) -> dict[str, Any]:
        payload, _ = await self._read_json(
            "GET", f"{self._endpoint}/models", max_bytes=_MAX_MODELS_RESPONSE_BYTES
        )
        models = self._models_payload(payload)
        if models is None:
            raise LMStudioEvidenceHold("LM Studio models response is malformed")
        matches = [
            item
            for item in models
            if item.get("key") == model and item.get("type") == "llm"
        ]
        if len(matches) != 1:
            raise LMStudioEvidenceHold(
                "bound LM Studio model identity is absent or ambiguous"
            )
        selected = matches[0]
        instances = selected.get("loaded_instances")
        if not isinstance(instances, list):
            raise LMStudioEvidenceHold(
                "LM Studio model identity is missing loaded instances"
            )
        valid_instances = [
            item
            for item in instances
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"]
            and isinstance(item.get("config"), dict)
            and isinstance(item["config"].get("context_length"), int)
        ]
        if len(valid_instances) != 1:
            raise LMStudioEvidenceHold(
                "bound LM Studio model instance is absent or ambiguous"
            )
        instance = valid_instances[0]
        context_length = instance["config"]["context_length"]
        if context_length < max_context_tokens:
            raise LMStudioEvidenceHold(
                "LM Studio model instance does not attest the requested context window"
            )
        model_identity = {
            "key": selected.get("key"),
            "publisher": selected.get("publisher"),
            "architecture": selected.get("architecture"),
            "quantization": selected.get("quantization"),
            "size_bytes": selected.get("size_bytes"),
            "params_string": selected.get("params_string"),
            "max_context_length": selected.get("max_context_length"),
            "format": selected.get("format"),
            "selected_variant": selected.get("selected_variant"),
        }
        if not isinstance(model_identity["publisher"], str) or not isinstance(
            model_identity["size_bytes"], int
        ):
            raise LMStudioEvidenceHold(
                "LM Studio model identity is missing immutable model metadata"
            )
        identity = {
            "endpoint": self._endpoint,
            "endpoint_digest": self._endpoint_digest,
            "runtime_revision": self._runtime_revision,
            "runtime_revision_attestation": "operator_owned_native_api_version_unavailable",
            "model_artifact_digest": self._model_artifact_digest,
            "model_artifact_digest_attestation": "operator_owned_native_api_digest_unavailable",
            "model_key": model,
            "model_instance_id": instance["id"],
            "context_length": context_length,
            "model_identity": model_identity,
        }
        return {**identity, "runtime_identity_digest": sha256(identity)}

    @staticmethod
    def _models_payload(payload: object) -> list[dict[str, Any]] | None:
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            return None
        return (
            [item for item in payload["models"] if isinstance(item, dict)]
            if len(payload["models"])
            == sum(isinstance(item, dict) for item in payload["models"])
            else None
        )

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
        async with self._client.stream(
            method,
            url,
            content=content,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                raise LMStudioEvidenceHold("redirect responses are forbidden")
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise LMStudioEvidenceHold(
                    "LM Studio response exceeds the configured byte limit"
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise LMStudioEvidenceHold(
                        "LM Studio response exceeds the configured byte limit"
                    )
        raw = bytes(body)
        try:
            return json.loads(raw), raw
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LMStudioEvidenceHold("LM Studio response is not valid JSON") from exc

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
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise LMStudioEvidenceHold(f"LM Studio response is missing valid {key}")
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
