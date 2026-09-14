"""Invocation-fenced wrapper around the durable adapter worker."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from adapters_v1 import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    HarnessAdapter,
    InvocationContext,
    PreparedAttempt,
    ResultBundle,
)
from persistence_v1.invocation_schema import budget_reservations, invocation_records
from persistence_v1.jobs import JobLease
from protocol_v1.canonical import sha256
from protocol_v1.models import HarnessSpec, TraceEvent

from .budget import AggregateBudgetExceeded
from .invocations import (
    DuplicateProviderRequest,
    InvocationRecord,
    InvocationRepository,
)
from .worker import (
    DurableWorker as _BaseDurableWorker,
    LeaseLost,
    WorkerResult,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class _InvocationAdapter(HarnessAdapter):
    """Attach operational fencing without mutating the scientific AttemptInput."""

    def __init__(
        self,
        adapter: HarnessAdapter,
        repository: InvocationRepository,
        invocation: InvocationRecord,
    ) -> None:
        self._adapter = adapter
        self._repository = repository
        self._invocation = invocation
        self._context = invocation.context

    async def describe_capabilities(self) -> AdapterCapabilities:
        return await self._adapter.describe_capabilities()

    async def healthcheck(self) -> AdapterHealth:
        return await self._adapter.healthcheck()

    async def prepare_attempt(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
    ) -> PreparedAttempt:
        remaining = self._context.remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise AggregateBudgetExceeded(
                "aggregate wall-time budget expired before adapter preparation"
            )
        supported = (
            type(self._adapter).prepare_invocation
            is not HarnessAdapter.prepare_invocation
        )
        self._repository.mark_transport_context(
            self._invocation,
            supported=supported,
        )
        self._invocation = self._repository.mark_dispatch_started(self._invocation)
        operation = self._adapter.prepare_invocation(harness, input, self._context)
        if remaining is None:
            return await operation
        try:
            return await asyncio.wait_for(operation, timeout=remaining)
        except TimeoutError as exc:
            raise AggregateBudgetExceeded(
                "aggregate wall-time budget expired during adapter preparation"
            ) from exc

    async def prepare_invocation(
        self,
        harness: HarnessSpec,
        input: AttemptInput,
        context: InvocationContext,
    ) -> PreparedAttempt:
        if context != self._context:
            raise ValueError("nested invocation context does not match the active fence")
        return await self.prepare_attempt(harness, input)

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        remaining = self._context.remaining_seconds()
        if remaining is not None and remaining <= 0:
            await self.cancel_attempt(prepared)
            raise AggregateBudgetExceeded(
                "aggregate wall-time budget expired before provider execution"
            )
        try:
            if remaining is None:
                result = await self._adapter.execute_attempt(prepared)
            else:
                result = await asyncio.wait_for(
                    self._adapter.execute_attempt(prepared),
                    timeout=remaining,
                )
        except TimeoutError as exc:
            await self.cancel_attempt(prepared)
            raise AggregateBudgetExceeded(
                "aggregate wall-time budget expired during provider execution"
            ) from exc

        provider_request_id = None
        applied = getattr(result, "applied_controls", None)
        if applied is not None:
            provider_request_id = applied.provider_request_id
        if provider_request_id:
            self._invocation = self._repository.observe_provider_request(
                self._invocation,
                provider_request_id,
            )
        usage = result.usage
        usage_state = (
            "observed"
            if usage is not None and usage.complete_usage
            else "unknown"
        )
        admitted = self._repository.admit_terminal(
            self._invocation,
            result_digest=sha256(result.model_dump(mode="json")),
            terminal_outcome=result.terminal_outcome,
            usage_state=usage_state,
        )
        if not admitted:
            raise LeaseLost
        return result

    async def stream_events(
        self,
        prepared: PreparedAttempt,
    ) -> AsyncIterator[TraceEvent]:
        async for event in self._adapter.stream_events(prepared):
            yield event

    async def collect_artifacts(
        self,
        prepared: PreparedAttempt,
    ) -> tuple[ArtifactRef, ...]:
        return await self._adapter.collect_artifacts(prepared)

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        current = self._repository.get(self._invocation.invocation_id)
        if current.cancellation_state == "not_requested":
            current = self._repository.request_cancel(current)
        if current.cancellation_state == "requested":
            current = self._repository.mark_cancel_dispatched(current)
        try:
            await self._adapter.cancel_attempt(prepared)
        except Exception:
            current = self._repository.get(current.invocation_id)
            if current.cancellation_state == "dispatched":
                self._repository.mark_cancel_unknown(current)
            raise
        current = self._repository.get(current.invocation_id)
        if current.cancellation_state == "dispatched":
            self._repository.mark_cancel_acknowledged(current)

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        await self._adapter.cleanup_attempt(prepared)


class _InvocationRegistry:
    def __init__(self, registry: Any, invocations: InvocationRepository) -> None:
        self._registry = registry
        self._invocations = invocations
        self._active: ContextVar[InvocationRecord | None] = ContextVar(
            "scaffold_arena_invocation",
            default=None,
        )

    @contextmanager
    def activate(self, invocation: InvocationRecord) -> Iterator[None]:
        token = self._active.set(invocation)
        try:
            yield
        finally:
            self._active.reset(token)

    async def install_trusted(self, adapter: HarnessAdapter, expected_digest: str):
        return await self._registry.install_trusted(adapter, expected_digest)

    def get(self, adapter_id: str, digest: str) -> HarnessAdapter:
        adapter = self._registry.get(adapter_id, digest)
        invocation = self._active.get()
        if invocation is None:
            return adapter
        return _InvocationAdapter(adapter, self._invocations, invocation)

    def capabilities(self, adapter_id: str, digest: str):
        return self._registry.capabilities(adapter_id, digest)


class DurableWorker(_BaseDurableWorker):
    """Durable worker whose accepted results are bound to one invocation generation."""

    def __init__(self, repository, registry, artifacts_store, **kwargs: Any) -> None:
        self.invocations = InvocationRepository(repository)
        self._invocation_registry = _InvocationRegistry(registry, self.invocations)
        super().__init__(
            repository,
            self._invocation_registry,
            artifacts_store,
            **kwargs,
        )

    async def run_lease(self, lease: JobLease) -> WorkerResult:
        invocation: InvocationRecord | None = None
        result: WorkerResult | None = None
        if lease.kind != "attempt" or lease.attempt_id is None:
            return await super().run_lease(lease)
        try:
            raw_input = lease.payload.get("attempt_input")
            if not isinstance(raw_input, Mapping):
                return await super().run_lease(lease)
            input = AttemptInput.model_validate_json(json.dumps(raw_input))
            deadline = self._aggregate_deadline(lease.payload.get("aggregate_budget"))
            if deadline is not None and deadline <= datetime.now(UTC):
                status = self.jobs.fail(
                    lease.id,
                    lease.owner,
                    lease_token=lease.token,
                    attempt_status="incomplete",
                    result_metadata={
                        "error_code": "aggregate_wall_time_hold",
                        "failure_classification": "permanent_protocol",
                        "aggregate_deadline_at": deadline.isoformat(),
                    },
                )
                return WorkerResult(
                    lease.id,
                    status or "lost",
                    "aggregate_wall_time_hold",
                )
            invocation = self.invocations.begin(
                lease,
                input,
                aggregate_deadline_at=deadline,
            )
            with self._invocation_registry.activate(invocation):
                result = await super().run_lease(lease)
            if result.detail == "lease_lost":
                self.invocations.mark_lease_lost(invocation)
            return result
        except DuplicateProviderRequest:
            status = self.jobs.fail(
                lease.id,
                lease.owner,
                lease_token=lease.token,
                attempt_status="incomplete",
                result_metadata={
                    "error_code": "duplicate_provider_request",
                    "failure_classification": "permanent_protocol",
                },
            )
            result = WorkerResult(
                lease.id,
                status or "lost",
                "duplicate_provider_request",
            )
            return result
        finally:
            if invocation is not None:
                if result is not None and result.status == "lost":
                    try:
                        invocation = self.invocations.mark_lease_lost(invocation)
                    except ValueError:
                        invocation = self.invocations.get(invocation.invocation_id)
                self.budgets.settle_open_for_invocation(
                    invocation.invocation_id,
                    reason=(
                        f"worker exited with {result.detail or result.status}"
                        if result is not None
                        else "worker exited before durable terminalization"
                    ),
                )
                self._synchronize_usage_state(invocation.invocation_id)

    @staticmethod
    def _aggregate_deadline(value: object) -> datetime | None:
        if not isinstance(value, Mapping):
            return None
        raw = value.get("deadline_at")
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise ValueError("aggregate deadline must be an ISO-8601 string")
        deadline = datetime.fromisoformat(raw)
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ValueError("aggregate deadline must be timezone-aware")
        return deadline.astimezone(UTC)

    def _synchronize_usage_state(self, invocation_id: str) -> None:
        with self.repository.transaction(immediate=True) as connection:
            states = tuple(
                connection.execute(
                    select(budget_reservations.c.state).where(
                        budget_reservations.c.invocation_id == invocation_id
                    )
                ).scalars()
            )
            if not states:
                return
            if "disputed" in states:
                usage_state, side_effect_state = "disputed", "ambiguous"
            elif "unknown_usage" in states:
                usage_state, side_effect_state = "unknown", "ambiguous"
            elif "committed" in states:
                usage_state, side_effect_state = "reconciled", "reconciled"
            elif all(state in {"released", "expired"} for state in states):
                usage_state, side_effect_state = "not_observed", "not_started"
            else:
                return
            connection.execute(
                update(invocation_records)
                .where(invocation_records.c.id == invocation_id)
                .values(
                    usage_state=usage_state,
                    side_effect_state=side_effect_state,
                    updated_at=datetime.now(UTC),
                )
            )
