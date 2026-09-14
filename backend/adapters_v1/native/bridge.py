"""Dependency-injected bridge to Scaffold Arena's in-process scaffolds.

The bridge does not resolve tasks, scaffolds, providers, or credentials itself.
An application must explicitly supply a runtime factory for each attempt.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import HarnessCapabilities, HarnessSpec, TraceEvent

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
    validate_result_for_attempt,
)
from ..preflight import preflight


@dataclass(frozen=True)
class UsageEvidence:
    """Provider-observed evidence supplied by the runtime owner.

    ``None`` means unknown.  The bridge never translates a missing field to
    zero, and it will not emit a completed result without complete evidence.
    """

    provider_version: str | None = None
    endpoint_digest: str | None = None
    context_tokens: int | None = None
    tool_calls: int | None = None
    actual_cost_usd: float | None = None


@dataclass(frozen=True)
class ScaffoldRuntime:
    """Explicitly provisioned current Scaffold Arena runtime."""

    scaffold: Any
    task: Any
    provider: Any
    options: Any
    run_id: str
    usage_evidence: UsageEvidence = UsageEvidence()
    config_override: dict[str, Any] | None = None


RuntimeFactory = Callable[[HarnessSpec, AttemptInput], ScaffoldRuntime]


class NativeScaffoldAdapter(HarnessAdapter):
    """Run the existing ``BaseScaffold.run`` protocol without hidden startup."""

    def __init__(
        self,
        *,
        adapter_id: str,
        adapter_digest: str,
        runtime_factory: RuntimeFactory,
        config_schema_hash: str | None = None,
        capabilities: HarnessCapabilities | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id,
            adapter_digest=adapter_digest,
            adapter_kind="in_process",
            supported_isolation=("none", "process"),
            capabilities=capabilities or HarnessCapabilities(),
            claim_eligibility="protocol_only",
            supports_cancellation=True,
            supports_artifacts=True,
            config_schema_hash=config_schema_hash,
        )
        self._attempts: dict[str, tuple[bytes, HarnessSpec]] = {}
        self._events: dict[str, list[TraceEvent]] = {}
        self._results: dict[str, ResultBundle] = {}
        self._ready: dict[str, asyncio.Event] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        # The factory is deliberately not called here: that could start a provider.
        return AdapterHealth(healthy=True, checked_at=datetime.now(UTC), detail="runtime factory installed; provider startup is caller-owned")

    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        bound = AttemptInput.model_validate_json(canonical_json(input.model_dump(mode="json")))
        preflight(self._capabilities, harness, bound)
        raw = canonical_json(bound.model_dump(mode="json"))
        attempt_id = bound.attempt.attempt_id
        self._attempts[attempt_id] = (raw, harness)
        self._events[attempt_id] = []
        self._ready[attempt_id] = asyncio.Event()
        self._cleaned.discard(attempt_id)
        return PreparedAttempt(
            attempt_id=attempt_id,
            adapter_id=self._capabilities.adapter_id,
            prepared_at=datetime.now(UTC),
            timeout_seconds=harness.timeout_seconds,
            opaque_handle=attempt_id,
            input_digest=sha256(bound.model_dump(mode="json")),
        )

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        if prepared.attempt_id in self._results:
            return self._results[prepared.attempt_id]
        bound, harness = self._attempt(prepared)
        attempt = bound.attempt
        input_tokens: int | None = None
        output_tokens: int | None = None
        calls = 0
        output = ""
        output_observed = False
        try:
            if prepared.attempt_id in self._cancelled:
                self._append(prepared, "system", "state", {"status": "cancelled_before_start"})
                result = self._terminal(attempt.attempt_id, "cancelled", "cancelled before native scaffold start")
            else:
                runtime = self._runtime_factory(harness, bound)
                self._append(prepared, "harness", "request", {"scaffold_id": getattr(runtime.scaffold, "id", "unknown"), "input_digest": prepared.input_digest})
                async for event_type, event_data in runtime.scaffold.run(
                    run_id=runtime.run_id,
                    task=runtime.task,
                    model_id=attempt.provider_model,
                    provider=runtime.provider,
                    options=runtime.options,
                    config_override=runtime.config_override,
                    cancelled_check=lambda: prepared.attempt_id in self._cancelled,
                ):
                    if event_type == "usage":
                        calls += 1
                        reported_input = event_data.get("input_tokens") if isinstance(event_data, dict) else None
                        reported_output = event_data.get("output_tokens") if isinstance(event_data, dict) else None
                        if isinstance(reported_input, int) and reported_input >= 0:
                            input_tokens = (input_tokens or 0) + reported_input
                        if isinstance(reported_output, int) and reported_output >= 0:
                            output_tokens = (output_tokens or 0) + reported_output
                        self._append(prepared, "harness", "state", {"event": "usage_observed", "call": calls})
                    elif event_type == "final_output" and isinstance(event_data, dict):
                        candidate = event_data.get("output")
                        if isinstance(candidate, str):
                            output = candidate
                            output_observed = True
                    elif event_type == "scaffold_delta" and isinstance(event_data, dict):
                        self._append(prepared, "model", "response", {"delta": event_data.get("delta", "")})
                    else:
                        self._append(prepared, "harness", "state", {"event": event_type, "data": _safe_data(event_data)})

                if prepared.attempt_id in self._cancelled:
                    result = self._terminal(attempt.attempt_id, "cancelled", "native scaffold cancellation drained")
                else:
                    usage = self._usage(attempt, input_tokens, output_tokens, calls, runtime.usage_evidence)
                    output_bytes = output.encode("utf-8")
                    output_hash = sha256_bytes(output_bytes)
                    artifacts = (
                        ArtifactRef(
                            artifact_id="native-output", media_type="text/plain; charset=utf-8",
                            sha256=output_hash, content=output_bytes,
                        ),
                    ) if output_observed else ()
                    if usage is None or not usage.complete_evidence:
                        result = self._terminal(
                            attempt.attempt_id, "incomplete",
                            "HOLD: provider, endpoint, token, context, and tool evidence required for completed result",
                            response_hash=output_hash if output_observed else None,
                            response_artifact_id="native-output" if output_observed else None,
                            usage=usage, artifacts=artifacts,
                            failure_classification="permanent_protocol",
                        )
                    else:
                        result = self._terminal(
                            attempt.attempt_id, "completed", None,
                            response_hash=output_hash, response_artifact_id="native-output",
                            usage=usage, artifacts=artifacts,
                        )
        except Exception as exc:  # noqa: BLE001 - adapter boundary preserves arbitrary runtime faults
            self._append(prepared, "system", "error", {"error_type": type(exc).__name__})
            result = self._terminal(
                attempt.attempt_id, "failed", f"native scaffold failed: {type(exc).__name__}",
                failure_classification="permanent_adapter",
            )
        finally:
            self._ready[prepared.attempt_id].set()
        self._results[prepared.attempt_id] = validate_result_for_attempt(result, attempt)
        return self._results[prepared.attempt_id]

    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]:
        self._attempt(prepared)
        await self._ready[prepared.attempt_id].wait()
        for event in tuple(self._events.get(prepared.attempt_id, ())):
            yield event

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        self._attempt(prepared)
        return self._results.get(
            prepared.attempt_id,
            self._terminal(
                prepared.attempt_id, "incomplete", "not executed",
                failure_classification="permanent_adapter",
            ),
        ).artifacts

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        self._cancelled.add(prepared.attempt_id)
        if prepared.attempt_id not in self._results:
            # Do not set ready during execution: consumers must drain durable events.
            self._append(prepared, "system", "state", {"status": "cancellation_requested"})

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        if prepared.attempt_id in self._cleaned:
            return
        await self.cancel_attempt(prepared)
        self._cleaned.add(prepared.attempt_id)

    def _attempt(self, prepared: PreparedAttempt) -> tuple[AttemptInput, HarnessSpec]:
        stored = self._attempts.get(prepared.attempt_id)
        if prepared.adapter_id != self._capabilities.adapter_id or stored is None:
            raise ValueError("prepared attempt is not owned by this adapter")
        bound = AttemptInput.model_validate_json(stored[0])
        if prepared.input_digest != sha256(bound.model_dump(mode="json")):
            raise ValueError("prepared attempt input binding mismatch")
        return bound, stored[1]

    def _append(self, prepared: PreparedAttempt, actor: str, event_type: str, payload: dict[str, Any]) -> None:
        bound, _ = self._attempt(prepared)
        event_list = self._events[prepared.attempt_id]
        safe_payload = _safe_data(payload)
        event_list.append(TraceEvent(
            trace_id=f"trace-{prepared.input_digest[:16]}",
            episode_id=bound.attempt.episode_id,
            attempt_id=bound.attempt.attempt_id,
            sequence=len(event_list),
            actor=actor,  # type: ignore[arg-type]
            event_type=event_type,  # type: ignore[arg-type]
            timestamp=datetime.now(UTC),
            monotonic_time=time.monotonic(),
            payload=safe_payload,
            payload_hash=sha256(safe_payload),
        ))

    def _usage(self, attempt: Any, input_tokens: int | None, output_tokens: int | None, calls: int, evidence: UsageEvidence) -> ProviderUsage | None:
        if input_tokens is None or output_tokens is None:
            return None
        # The old scaffold event interface cannot certify context/tool evidence by itself.
        if evidence.provider_version is None or evidence.endpoint_digest is None or evidence.context_tokens is None or evidence.tool_calls is None:
            return ProviderUsage(evidence_source="provider_reported", input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens + output_tokens, context_tokens=evidence.context_tokens, tool_calls=evidence.tool_calls, actual_cost_usd=evidence.actual_cost_usd, observed_provider_version=evidence.provider_version, observed_endpoint_digest=evidence.endpoint_digest)
        if attempt.pinned_endpoint_digest != evidence.endpoint_digest:
            return None
        payload = {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens, "context_tokens": evidence.context_tokens, "tool_calls": evidence.tool_calls, "provider_version": evidence.provider_version, "endpoint_digest": evidence.endpoint_digest, "call_count": calls}
        return ProviderUsage(evidence_source="provider_reported", input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens + output_tokens, context_tokens=evidence.context_tokens, tool_calls=evidence.tool_calls, actual_cost_usd=evidence.actual_cost_usd, provider_usage_digest=sha256(payload), observed_provider_version=evidence.provider_version, observed_endpoint_digest=evidence.endpoint_digest)

    @staticmethod
    def _terminal(attempt_id: str, outcome: str, detail: str | None, *, response_hash: str | None = None, response_artifact_id: str | None = None, usage: ProviderUsage | None = None, artifacts: tuple[ArtifactRef, ...] = (), failure_classification: FailureClassification | None = None) -> ResultBundle:
        return ResultBundle(attempt_id=attempt_id, terminal_outcome=outcome, completed_at=datetime.now(UTC), response_hash=response_hash, response_artifact_id=response_artifact_id, usage=usage, artifacts=artifacts, detail=detail, failure_classification=failure_classification)  # type: ignore[arg-type]


def _safe_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if any(token in str(key).lower() for token in ("api_key", "authorization", "password", "secret", "token")) else _safe_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_data(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_data(item) for item in value]
    return value
