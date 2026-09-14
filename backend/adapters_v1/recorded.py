"""A deterministic adapter for protocol fixtures, never live-provider claims."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from protocol_v1.canonical import canonical_json, sha256
from protocol_v1.models import HarnessSpec, TraceEvent

from .base import HarnessAdapter
from .models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    PreparedAttempt,
    ResultBundle,
    validate_events_for_attempt,
    validate_result_for_attempt,
)
from .preflight import preflight


class RecordedAdapter(HarnessAdapter):
    def __init__(self, *, adapter_id: str, adapter_digest: str, results: dict[str, ResultBundle], events: dict[str, tuple[TraceEvent, ...]] | None = None, artifacts: dict[str, tuple[ArtifactRef, ...]] | None = None, config_schema_hash: str | None = None) -> None:
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id, adapter_digest=adapter_digest, adapter_kind="recorded",
            supported_isolation=("none",), claim_eligibility="fixture_only", supports_cancellation=True, supports_artifacts=True,
            config_schema_hash=config_schema_hash,
        )
        self._results = dict(results)
        self._events = dict(events or {})
        self._artifacts = dict(artifacts or {})
        self._attempts: dict[str, bytes] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(healthy=True, checked_at=datetime.now(UTC), detail="recorded fixtures available")

    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        input = AttemptInput.model_validate_json(canonical_json(input.model_dump(mode="json")))
        preflight(self._capabilities, harness, input)
        attempt = input.attempt
        if attempt.attempt_id not in self._results:
            raise ValueError("recorded result fixture is missing")
        self._attempts[attempt.attempt_id] = canonical_json(input.model_dump(mode="json"))
        return PreparedAttempt(attempt_id=attempt.attempt_id, adapter_id=self._capabilities.adapter_id, prepared_at=datetime.now(UTC), timeout_seconds=harness.timeout_seconds, opaque_handle=attempt.attempt_id, input_digest=sha256(input.model_dump(mode="json")))

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        attempt = self._attempt(prepared).attempt
        if prepared.attempt_id in self._cancelled:
            return ResultBundle(attempt_id=prepared.attempt_id, terminal_outcome="cancelled", completed_at=datetime.now(UTC), detail="cancelled")
        return validate_result_for_attempt(self._results[prepared.attempt_id], attempt)

    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]:
        events = validate_events_for_attempt(self._events.get(prepared.attempt_id, ()), self._attempt(prepared).attempt)
        for event in events:
            yield event

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        self._attempt(prepared)
        return self._artifacts.get(prepared.attempt_id, self._results[prepared.attempt_id].artifacts)

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        self._cancelled.add(prepared.attempt_id)

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        self._cleaned.add(prepared.attempt_id)

    def _attempt(self, prepared: PreparedAttempt) -> AttemptInput:
        if prepared.adapter_id != self._capabilities.adapter_id or prepared.attempt_id not in self._attempts:
            raise ValueError("prepared attempt is not owned by this adapter")
        input = AttemptInput.model_validate_json(self._attempts[prepared.attempt_id])
        if prepared.input_digest != sha256(input.model_dump(mode="json")):
            raise ValueError("prepared attempt input binding mismatch")
        return input
