"""Fail-closed execution bridge for compiled P/V/R/M recipes.

The bridge decorates an already trusted :class:`adapters_v1.HarnessAdapter`.
It does not turn a generic adapter into a treatment runtime: callers must
provide a trusted ``FactorRuntime`` that supplies the observed mechanism
artifacts.  Missing or inconsistent evidence prevents provider execution (at
prepare time) or produces an ``incomplete`` HOLD (at finalization time).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, Protocol

from adapters_v1 import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    HarnessAdapter,
    PreparedAttempt,
    ResultBundle,
)
from adapters_v1.models import validate_events_for_attempt, validate_result_for_attempt
from protocol_v1.canonical import canonical_json, sha256
from protocol_v1.models import HarnessSpec, TraceEvent

from .compiler import enumerate_flagship_recipes
from .fidelity import check_manipulation_fidelity
from .models import (
    CheckpointArtifact,
    CompiledRecipe,
    EpisodeMemory,
    EvidencePointer,
    FailureEvent,
    FinalizationCandidate,
    ManipulationFidelity,
    PlanArtifact,
    RecoveryDecision,
    RecoveryPolicy,
    TreatmentBudget,
    VerificationArtifact,
)
from .planning import transition_plan_step
from .recovery import authorize_recovery


class FactorAdapterError(ValueError):
    """A compiled arm cannot be truthfully executed by this adapter/runtime."""


@dataclass(frozen=True)
class RecoveryObservation:
    """A recovery decision plus the complete inputs needed to replay its gate."""

    failure: FailureEvent
    checkpoint: CheckpointArtifact | None
    policy: RecoveryPolicy
    retries_used: int
    idempotency_key: str
    observed_checkpoint_sequences: frozenset[int]
    used_idempotency_keys: frozenset[str] = frozenset()
    decision: RecoveryDecision | None = None


@dataclass(frozen=True)
class FactorExecutionReport:
    """Observed runtime evidence; it establishes delivery only, never outcome."""

    observed_assignment: dict[str, bool]
    observed_budgets: dict[str, TreatmentBudget]
    evidence: tuple[EvidencePointer, ...]
    plan_history: tuple[PlanArtifact, ...] = ()
    verification: VerificationArtifact | None = None
    recovery: tuple[RecoveryObservation, ...] = ()
    memory: EpisodeMemory | None = None


@dataclass(frozen=True)
class FactorRuntimeSession:
    """Opaque runtime state bound to one canonical attempt snapshot."""

    token: object
    initial_report: FactorExecutionReport


class FactorRuntime(Protocol):
    """Trusted semantic implementation supplied by the integrating harness.

    The runtime owns actual plan/checkpoint/memory operations.  It must not
    alter the attempt snapshot, provider, sampling, task, evaluator, or budget.
    """

    async def start(self, recipe: CompiledRecipe, input: AttemptInput) -> FactorRuntimeSession: ...

    async def finalize(
        self, recipe: CompiledRecipe, input: AttemptInput, session: FactorRuntimeSession, result: ResultBundle
    ) -> FactorExecutionReport: ...

    async def cancel(self, recipe: CompiledRecipe, input: AttemptInput, session: FactorRuntimeSession) -> None: ...

    async def cleanup(self, recipe: CompiledRecipe, input: AttemptInput, session: FactorRuntimeSession) -> None: ...


@dataclass(frozen=True)
class _StoredAttempt:
    raw_input: bytes
    harness: HarnessSpec
    prepared: PreparedAttempt
    session: FactorRuntimeSession


class FactorizedHarnessAdapter(HarnessAdapter):
    """Decorate a trusted adapter with one immutable compiled factor recipe.

    Its identity remains the wrapped adapter's identity so ordinary adapter
    preflight remains authoritative.  Install this decorator only alongside a
    runtime that can deliver the stated semantics; a generic recorded/HTTP/CLI
    adapter alone is insufficient.
    """

    def __init__(self, *, adapter: HarnessAdapter, recipe: CompiledRecipe, runtime: FactorRuntime) -> None:
        self._adapter = adapter
        self._recipe_raw = canonical_json(recipe.model_dump(mode="json"))
        self._runtime = runtime
        self._attempts: dict[str, _StoredAttempt] = {}
        self._results: dict[str, ResultBundle] = {}
        self._reports: dict[str, FactorExecutionReport] = {}
        self._completed: dict[str, asyncio.Event] = {}
        self._execution_locks: dict[str, asyncio.Lock] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    @property
    def recipe(self) -> CompiledRecipe:
        return self._bound_recipe()

    @property
    def fidelity(self) -> dict[str, tuple[ManipulationFidelity, ...]]:
        """Observed delivery evidence, deliberately separate from Arena evaluation."""
        return {
            attempt_id: check_manipulation_fidelity(
                self._bound_recipe(), report.observed_assignment, report.observed_budgets, report.evidence
            )
            for attempt_id, report in self._reports.items()
        }

    async def describe_capabilities(self) -> AdapterCapabilities:
        return await self._adapter.describe_capabilities()

    async def healthcheck(self) -> AdapterHealth:
        return await self._adapter.healthcheck()

    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        bound = AttemptInput.model_validate_json(canonical_json(input.model_dump(mode="json")))
        raw = canonical_json(bound.model_dump(mode="json"))
        self._assert_assignment(bound)
        capabilities = await self._adapter.describe_capabilities()
        self._assert_capabilities(capabilities)
        try:
            session = await self._runtime.start(self._bound_recipe(), bound)
            self._assert_unchanged(raw, bound)
            self._validate_delivery(session.initial_report, bound, final=False)
            prepared = await self._adapter.prepare_attempt(harness, bound)
            self._assert_unchanged(raw, bound)
        except FactorAdapterError:
            raise
        except Exception as exc:
            raise FactorAdapterError(f"HOLD: factor runtime preparation failed: {type(exc).__name__}") from exc
        if prepared.input_digest != sha256(bound.model_dump(mode="json")):
            raise FactorAdapterError("wrapped adapter did not preserve canonical AttemptInput binding")
        self._attempts[prepared.attempt_id] = _StoredAttempt(raw, harness, prepared, session)
        self._results.pop(prepared.attempt_id, None)
        self._reports.pop(prepared.attempt_id, None)
        self._completed[prepared.attempt_id] = asyncio.Event()
        self._execution_locks[prepared.attempt_id] = asyncio.Lock()
        self._cancelled.discard(prepared.attempt_id)
        self._cleaned.discard(prepared.attempt_id)
        return prepared

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        stored, bound = self._attempt(prepared)
        completed = self._completed[prepared.attempt_id]
        if prepared.attempt_id in self._results:
            completed.set()
            return self._results[prepared.attempt_id]
        async with self._execution_locks[prepared.attempt_id]:
            if prepared.attempt_id in self._results:
                completed.set()
                return self._results[prepared.attempt_id]
            try:
                result = await self._adapter.execute_attempt(stored.prepared)
                self._assert_unchanged(stored.raw_input, bound)
                result = validate_result_for_attempt(result, bound.attempt)
                report = await self._runtime.finalize(self._bound_recipe(), bound, stored.session, result)
                self._assert_unchanged(stored.raw_input, bound)
                self._validate_delivery(report, bound, final=True, result=result)
                self._reports[prepared.attempt_id] = report
                final = result
            except Exception as exc:  # noqa: BLE001 - an evidence boundary must fail closed for all runtime faults.
                final = ResultBundle(
                    attempt_id=prepared.attempt_id,
                    terminal_outcome="incomplete",
                    completed_at=datetime.now(UTC),
                    detail=f"HOLD: factor manipulation fidelity or semantics unavailable: {type(exc).__name__}",
                    failure_classification="permanent_protocol",
                )
            finally:
                self._results[prepared.attempt_id] = final
                completed.set()
            return final

    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]:
        stored, bound = self._attempt(prepared)
        yield self._recipe_binding_event(prepared, bound)
        base = tuple([event async for event in self._adapter.stream_events(stored.prepared)])
        validate_events_for_attempt(base, bound.attempt)
        for index, event in enumerate(base, start=1):
            payload = {"wrapped_event": event.payload, "wrapped_sequence": event.sequence}
            yield TraceEvent(
                trace_id=f"factor-{prepared.input_digest[:16]}", episode_id=event.episode_id,
                attempt_id=event.attempt_id, sequence=index, actor=event.actor, event_type=event.event_type,
                timestamp=event.timestamp, monotonic_time=event.monotonic_time,
                source_time=event.source_time, state_ref=event.state_ref, redaction=event.redaction,
                payload=payload, payload_hash=sha256(payload),
            )
        await self._completed[prepared.attempt_id].wait()
        for index, event in enumerate(self._final_factor_events(prepared, bound), start=len(base) + 1):
            yield event.model_copy(update={"sequence": index})

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        stored, _ = self._attempt(prepared)
        result = self._results.get(prepared.attempt_id)
        if result is not None:
            return result.artifacts
        return await self._adapter.collect_artifacts(stored.prepared)

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        stored, bound = self._attempt(prepared)
        if prepared.attempt_id in self._cancelled:
            return
        await self._runtime.cancel(self._bound_recipe(), bound, stored.session)
        await self._adapter.cancel_attempt(stored.prepared)
        self._cancelled.add(prepared.attempt_id)

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        stored, bound = self._attempt(prepared)
        if prepared.attempt_id in self._cleaned:
            return
        await self.cancel_attempt(prepared)
        await self._runtime.cleanup(self._bound_recipe(), bound, stored.session)
        await self._adapter.cleanup_attempt(stored.prepared)
        self._cleaned.add(prepared.attempt_id)

    def _attempt(self, prepared: PreparedAttempt) -> tuple[_StoredAttempt, AttemptInput]:
        stored = self._attempts.get(prepared.attempt_id)
        if stored is None or stored.prepared != prepared:
            raise FactorAdapterError("prepared attempt is not owned by this factor adapter")
        bound = AttemptInput.model_validate_json(stored.raw_input)
        if prepared.input_digest != sha256(bound.model_dump(mode="json")):
            raise FactorAdapterError("prepared attempt input binding mismatch")
        return stored, bound

    def _assert_assignment(self, input: AttemptInput) -> None:
        observed = input.attempt.factor_assignments
        recipe = self._bound_recipe()
        if set(observed) != set(recipe.assignment) or any(type(value) is not bool for value in observed.values()):
            raise FactorAdapterError("AttemptInput must bind exactly the compiled strict-boolean P/V/R/M assignment")
        if dict(observed) != recipe.assignment:
            raise FactorAdapterError("AttemptInput factor assignment does not match the immutable compiled recipe")

    def _assert_capabilities(self, capabilities: AdapterCapabilities) -> None:
        missing = sorted({name for mechanism in self._bound_recipe().mechanisms for name in mechanism.required_capabilities if not getattr(capabilities.capabilities, name, False)})
        if missing:
            raise FactorAdapterError(f"HOLD: wrapped adapter lacks required factor capabilities: {', '.join(missing)}")

    @staticmethod
    def _assert_unchanged(raw: bytes, input: AttemptInput) -> None:
        if canonical_json(input.model_dump(mode="json")) != raw:
            raise FactorAdapterError("factor runtime mutated the canonical AttemptInput binding")

    def _validate_delivery(
        self, report: FactorExecutionReport, input: AttemptInput, *, final: bool, result: ResultBundle | None = None
    ) -> None:
        fidelity = check_manipulation_fidelity(
            self._bound_recipe(), report.observed_assignment, report.observed_budgets, report.evidence
        )
        if not all(item.delivered and item.compute_context_matched for item in fidelity):
            raise FactorAdapterError("every active and sham factor requires explicit compute/context-matched delivery evidence")
        active = self._bound_recipe().assignment
        if active["planning"]:
            self._validate_plan(report.plan_history, input.attempt.episode_id)
        if active["memory"] and (report.memory is None or report.memory.episode_id != input.attempt.episode_id or not report.memory.items):
            raise FactorAdapterError("active memory requires bounded, sourced within-episode memory evidence")
        if active["recovery"]:
            self._validate_recovery(report.recovery, input)
        if final and active["verification"]:
            self._validate_verification(report.verification, input, result)

    @staticmethod
    def _validate_plan(history: tuple[PlanArtifact, ...], episode_id: str) -> None:
        if len(history) < 3 or any(plan.episode_id != episode_id for plan in history):
            raise FactorAdapterError("active planning requires an episode-bound plan and evidenced state transitions")
        for before, after in pairwise(history):
            if before.plan_id != after.plan_id or len(before.steps) != len(after.steps):
                raise FactorAdapterError("plan history must preserve one immutable plan artifact")
            changed = [(old, new) for old, new in zip(before.steps, after.steps, strict=True) if old != new]
            if len(changed) != 1:
                raise FactorAdapterError("each plan transition must update exactly one step")
            old, new = changed[0]
            expected = transition_plan_step(before, step_id=old.step_id, state=new.state, evidence=new.terminal_evidence)
            if expected != after:
                raise FactorAdapterError("plan history contains an invalid state transition")
        if not all(step.state in {"completed", "failed"} for step in history[-1].steps):
            raise FactorAdapterError("active plan must reach evidenced terminal step states before finalization")

    @staticmethod
    def _validate_recovery(observations: tuple[RecoveryObservation, ...], input: AttemptInput) -> None:
        for observed in observations:
            if observed.failure.episode_id != input.attempt.episode_id or observed.failure.attempt_id != input.attempt.attempt_id:
                raise FactorAdapterError("recovery observation does not bind this attempt")
            expected = authorize_recovery(
                observed.failure, observed.checkpoint, observed.policy, retries_used=observed.retries_used,
                idempotency_key=observed.idempotency_key,
                observed_checkpoint_sequences=observed.observed_checkpoint_sequences,
                used_idempotency_keys=observed.used_idempotency_keys,
            )
            if observed.decision != expected:
                raise FactorAdapterError("recovery decision was not authorized by the declared-transient checkpoint gate")

    @staticmethod
    def _validate_verification(
        verification: VerificationArtifact | None, input: AttemptInput, result: ResultBundle | None
    ) -> None:
        if result is None or result.terminal_outcome != "completed" or result.response_hash is None:
            return
        if verification is None:
            raise FactorAdapterError("active verification requires agent-side pre-finalization evidence")
        candidate = FinalizationCandidate(episode_id=input.attempt.episode_id, response_hash=result.response_hash)
        if verification.scope != "agent_pre_finalization" or verification.independent_arena_evaluation:
            raise FactorAdapterError("factor verification must remain distinct from Arena evaluation")
        if verification.episode_id != candidate.episode_id or verification.candidate_response_hash != candidate.response_hash:
            raise FactorAdapterError("verification artifact does not bind the candidate response")
        if verification.repairs_used > 1 or not verification.finalization_allowed or verification.final_response_hash != result.response_hash:
            raise FactorAdapterError("agent verification did not permit this final response within its one-repair budget")

    def _recipe_binding_event(self, prepared: PreparedAttempt, input: AttemptInput) -> TraceEvent:
        payload: dict[str, Any] = {
            "event": "factor_recipe_bound", "recipe_id": self._bound_recipe().recipe_id,
            "configuration_hash": self._bound_recipe().configuration_hash, "input_digest": prepared.input_digest,
            "claim": "delivery_evidence_only",
        }
        return TraceEvent(
            trace_id=f"factor-{prepared.input_digest[:16]}", episode_id=input.attempt.episode_id,
            attempt_id=input.attempt.attempt_id, sequence=0, actor="system", event_type="state",
            timestamp=datetime.now(UTC), monotonic_time=time.monotonic(), payload=payload, payload_hash=sha256(payload),
        )

    def _final_factor_events(self, prepared: PreparedAttempt, input: AttemptInput) -> tuple[TraceEvent, ...]:
        report = self._reports.get(prepared.attempt_id)
        entries: list[dict[str, Any]] = []
        if report is not None:
            for item in check_manipulation_fidelity(self._bound_recipe(), report.observed_assignment, report.observed_budgets, report.evidence):
                entries.append({"event": "factor_fidelity", "factor_id": item.factor_id, "mode": item.mode, "passed": item.delivered, "compute_context_matched": item.compute_context_matched, "claim": item.claim})
        else:
            for mechanism in self._bound_recipe().mechanisms:
                entries.append({"event": "factor_fidelity", "factor_id": mechanism.factor_id, "mode": mechanism.mode, "passed": False, "compute_context_matched": False, "reason": "no finalized fidelity report", "claim": "delivery_evidence_only"})
        terminal = self._results.get(prepared.attempt_id)
        if terminal is None:
            raise FactorAdapterError("stream observed completion without a terminal factor result")
        entries.append({"event": "factor_terminal", "outcome": terminal.terminal_outcome, "fidelity_observed": report is not None})
        now = datetime.now(UTC)
        start = time.monotonic()
        return tuple(
            TraceEvent(
                trace_id=f"factor-{prepared.input_digest[:16]}", episode_id=input.attempt.episode_id,
                attempt_id=input.attempt.attempt_id, sequence=index, actor="system", event_type="state",
                timestamp=now, monotonic_time=start + index / 1_000_000, payload=payload, payload_hash=sha256(payload),
            )
            for index, payload in enumerate(entries)
        )

    def _bound_recipe(self) -> CompiledRecipe:
        """Return a fresh immutable-by-canonical-snapshot recipe for each boundary call."""
        return CompiledRecipe.model_validate_json(self._recipe_raw)


class FactorizedRecipeRouterAdapter(HarnessAdapter):
    """Route each bound P/V/R/M assignment to one factor adapter instance.

    A factorial experiment has one harness identity but sixteen treatment
    assignments.  Installing sixteen aliases would either duplicate a trusted
    identity or let a harness select an adapter dynamically.  This router is a
    single installed adapter: it selects only from the closed, compiled
    flagship recipe set using the already-bound ``AttemptInput`` assignment.
    """

    def __init__(self, *, adapter: HarnessAdapter, runtime: FactorRuntime) -> None:
        self._adapter = adapter
        self._runtime = runtime
        self._by_assignment = {
            self._key(recipe.assignment): FactorizedHarnessAdapter(adapter=adapter, recipe=recipe, runtime=runtime)
            for recipe in enumerate_flagship_recipes()
        }
        self._prepared: dict[str, FactorizedHarnessAdapter] = {}

    async def describe_capabilities(self) -> AdapterCapabilities:
        return await self._adapter.describe_capabilities()

    async def healthcheck(self) -> AdapterHealth:
        return await self._adapter.healthcheck()

    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        try:
            child = self._by_assignment[self._key(input.attempt.factor_assignments)]
        except (KeyError, TypeError, ValueError) as exc:
            raise FactorAdapterError("AttemptInput must bind one of the sixteen strict P/V/R/M recipes") from exc
        prepared = await child.prepare_attempt(harness, input)
        self._prepared[prepared.attempt_id] = child
        return prepared

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        return await self._child(prepared).execute_attempt(prepared)

    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]:
        async for event in self._child(prepared).stream_events(prepared):
            yield event

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        return await self._child(prepared).collect_artifacts(prepared)

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        await self._child(prepared).cancel_attempt(prepared)

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        await self._child(prepared).cleanup_attempt(prepared)

    def _child(self, prepared: PreparedAttempt) -> FactorizedHarnessAdapter:
        try:
            return self._prepared[prepared.attempt_id]
        except KeyError as exc:
            raise FactorAdapterError("prepared attempt is not owned by this factor router") from exc

    @staticmethod
    def _key(value: dict[str, bool] | Any) -> tuple[tuple[str, bool], ...]:
        if not isinstance(value, dict) or set(value) != {"planning", "verification", "recovery", "memory"}:
            raise ValueError("P/V/R/M assignment required")
        if any(type(item) is not bool for item in value.values()):
            raise TypeError("P/V/R/M assignment values must be booleans")
        return tuple(sorted(value.items()))
