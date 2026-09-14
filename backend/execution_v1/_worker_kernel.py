"""A durable worker that is intentionally the only adapter invocation point."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from adapters_v1 import AdapterRegistry, ArtifactRef, AttemptInput
from adapters_v1.models import ProviderUsage, ResultBundle
from artifacts_v1.store import ArtifactStore
from persistence_v1 import ArenaRepository
from persistence_v1.jobs import JobLease, JobLeaseRepository
from persistence_v1.schema import (
    artifacts,
    attempts,
    episodes,
    executions,
    jobs,
    usage_ledger,
)
from protocol_v1.canonical import canonical_json
from protocol_v1.models import AttemptEnvelope, HarnessSpec, ScenarioSpec, TraceEvent
from sqlalchemy import select

from .budget import AggregateBudgetExceeded, BudgetReservationService
from .currency import currency_exceeds
from .pricing import PriceResolver
from .state import FaultHook, StateOracleHook


@dataclass(frozen=True)
class WorkerResult:
    job_id: str
    status: str
    detail: str | None = None


@dataclass
class AttemptEvidence:
    """Evidence collected by one invocation, including an intentionally partial trace."""

    input_artifact_digest: str | None = None
    output_artifact_digest: str | None = None
    trace_artifact_digest: str | None = None
    trace_complete: bool = False
    trace_events: list[TraceEvent] = field(default_factory=list)


class DurableWorker:
    def __init__(
        self, repository: ArenaRepository, registry: AdapterRegistry, artifacts_store: ArtifactStore,
        *, state_oracle: StateOracleHook | None = None, fault_hook: FaultHook | None = None,
        after_artifacts_hook: Callable[[JobLease, ResultBundle], None] | None = None,
        price_resolver: PriceResolver | None = None,
        project_id: str | None = None,
        terminalize_on_cancel: bool = False,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.artifact_store = artifacts_store
        self.jobs = JobLeaseRepository(repository)
        self.budgets = BudgetReservationService(repository)
        self.state_oracle = state_oracle
        self.fault_hook = fault_hook
        self.after_artifacts_hook = after_artifacts_hook
        self.price_resolver = price_resolver
        self.project_id = project_id
        self.terminalize_on_cancel = terminalize_on_cancel

    async def run_once(
        self,
        owner: str,
        *,
        lease_seconds: float = 30.0,
        execution_id: str | None = None,
    ) -> WorkerResult | None:
        # Evaluation jobs are deliberately invisible to the adapter worker.
        # This keeps a provider-capable process from leasing evaluator work.
        lease = self.jobs.claim(
            owner,
            lease_seconds=lease_seconds,
            kind="attempt",
            project_id=self.project_id,
            execution_id=execution_id,
        )
        if lease is None:
            return None
        return await self.run_lease(lease)

    async def run_lease(self, lease: JobLease) -> WorkerResult:
        prepared = None
        adapter = None
        reservation: str | None = None
        result: ResultBundle | None = None
        terminal: tuple[str, str, Mapping[str, Any]] | None = None
        evidence = AttemptEvidence()
        try:
            if lease.kind != "attempt" or lease.attempt_id is None:
                status = self.jobs.fail(lease.id, lease.owner, lease_token=lease.token, result_metadata={"error": "unsupported job kind"})
                return WorkerResult(lease.id, status or "lost", "unsupported job kind")
            if set(lease.payload) - {"attempt_input", "harness", "aggregate_budget"}:
                raise ValueError("attempt job payload contains unsupported keys")
            input = AttemptInput.model_validate_json(json.dumps(lease.payload["attempt_input"]))
            input = AttemptInput.model_validate_json(canonical_json(input.model_dump(mode="json")))
            queued_envelope = input.attempt
            envelope = queued_envelope.model_copy(update={"status": "started", "started_at": datetime.now(UTC)})
            harness = HarnessSpec.model_validate_json(json.dumps(lease.payload["harness"]))
            if envelope.attempt_id != lease.attempt_id:
                raise ValueError("job payload envelope does not bind the leased attempt")
            self._validate_scenario_binding(lease, input)
            if not harness.adapter_identity or not harness.adapter_digest:
                raise ValueError("harness must bind an explicitly trusted adapter identity and digest")
            adapter = self.registry.get(harness.adapter_identity, harness.adapter_digest)
            reservation = self._reserve_once(lease, envelope)
            scenario = ScenarioSpec.model_validate_json(canonical_json(input.scenario.model_dump(mode="json")))
            if self.fault_hook is not None:
                self.fault_hook.before_attempt(scenario, envelope)
            self._mark_started(lease)
            started = monotonic()
            started_input = AttemptInput.bind(scenario, envelope)
            evidence.input_artifact_digest = self._persist_generated_artifact(
                canonical_json(started_input.model_dump(mode="json")),
                media_type="application/vnd.scaffold-arena.attempt-input+json",
                metadata={"artifact_role": "attempt_input", "attempt_id": envelope.attempt_id},
            )
            prepared = await asyncio.wait_for(adapter.prepare_attempt(harness, started_input), timeout=min(harness.timeout_seconds, envelope.budget.max_latency_seconds))
            result = await self._execute_supervised(adapter, prepared, lease, envelope, harness, evidence.trace_events)
            elapsed = monotonic() - started
            if elapsed > envelope.budget.max_latency_seconds:
                terminal = ("failed", "timed_out", {"error_code": "latency_budget_exceeded", "failure_classification": "transient"})
                return await self._finish(lease, terminal, adapter, prepared, evidence)
            if result.terminal_outcome == "completed" and not evidence.trace_events:
                raise PartialTrace
            evidence.trace_artifact_digest = self._persist_trace(evidence.trace_events)
            evidence.trace_complete = True
            manipulation_pass, manipulation_artifact_digest, manipulation_detail = self._derive_manipulation_evidence(
                envelope, evidence.trace_events,
            )
            self._validate_result_lifecycle(result, envelope)
            self._enforce_usage(
                result,
                envelope,
                claim_eligibility=harness.claim_eligibility,
                require_complete=result.terminal_outcome == "completed",
            )
            artifact_digests, artifact_ids = self._persist_artifacts(result.artifacts + await adapter.collect_artifacts(prepared))
            evidence.output_artifact_digest = self._resolve_output_artifact(result, artifact_ids)
            if self.after_artifacts_hook is not None:
                self.after_artifacts_hook(lease, result)
            decision = self._oracle_decision(scenario, envelope, result)
            state_oracle_artifact_digest = (
                self._persist_generated_artifact(
                    canonical_json({
                        "terminal_outcome": decision[0],
                        "detail_code": decision[1],
                        "evidence": decision[2],
                    }),
                    media_type="application/vnd.scaffold-arena.state-oracle+json",
                    metadata={"artifact_role": "state_oracle", "attempt_id": envelope.attempt_id},
                )
                if decision is not None
                else None
            )
            # State-oracle results are immutable evaluation evidence. They do
            # not rewrite the adapter's observed lifecycle terminal state.
            outcome = result.terminal_outcome
            detail = "state_oracle" if decision else None
            cost = self._reconcile(reservation, result, envelope)
            terminal_envelope = self._terminal_envelope(envelope, result, status=outcome)
            metadata = {
                "terminal_outcome": outcome, "detail_code": detail, "response_hash": result.response_hash,
                "failure_classification": result.failure_classification,
                "usage": result.usage.model_dump(mode="json") if result.usage is not None else None, "artifact_digests": artifact_digests,
                "artifact_ids": artifact_ids,
                "cost_status": cost.status, "cost_usd": cost.cost_usd,
                "state_oracle": decision[2] if decision else None,
                "state_oracle_artifact_digest": state_oracle_artifact_digest,
                "terminal_envelope": terminal_envelope,
                "manipulation_pass": manipulation_pass,
                "manipulation_artifact_digest": manipulation_artifact_digest,
                "manipulation_detail": manipulation_detail,
                "captured_adapter_terminal": True,
                "limitations": (["fixture_only_recorded_evidence_cost_unknown"] if harness.claim_eligibility == "fixture_only" and cost.status == "unknown" else [])
                    + (["aggregate_token_and_tool_reconciliation_requires_persisted_usage_schema"] if lease.payload.get("aggregate_budget") and not self._aggregate_usage_reconciliation_supported() else []),
            }
            if (
                result.terminal_outcome == "completed"
                and harness.claim_eligibility != "fixture_only"
                and cost.status != "reconciled"
            ):
                metadata["limitations"] = list(metadata["limitations"]) + ["claim_eligible_completion_requires_central_price_resolution"]
            terminal = (outcome, outcome, metadata)
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except asyncio.CancelledError:
            if not self.terminalize_on_cancel:
                raise
            await self._cancel_with_timeout(adapter, prepared, lease, "task_cancel_failed")
            terminal = ("cancelled", "cancelled", {"error_code": "worker_task_cancelled", "failure_classification": "transient"})
            await self._finish(lease, terminal, adapter, prepared, evidence)
            raise
        except LeaseLost:
            if lease.attempt_id is not None:
                self.jobs.record_diagnostic(lease.attempt_id, "lease_lost", {"error_code": "lease_lost"})
            terminal = ("incomplete", "incomplete", {"error_code": "lease_lost", "failure_classification": "transient"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except CancellationRequested:
            terminal = ("cancelled", "cancelled", {"error_code": "cancel_requested"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except UsageMismatch:
            if reservation is not None:
                self.budgets.mismatch(reservation, usage=result.usage if result is not None else None)
            terminal = ("failed", "failed", {"error_code": "usage_mismatch", "failure_classification": "permanent_protocol"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except MissingUsageEvidence:
            if reservation is not None:
                self._reconcile_unknown(reservation, result.usage if result is not None else None)
            terminal = ("incomplete", "incomplete", {"error_code": "usage_evidence_hold", "failure_classification": "permanent_protocol"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except AggregateBudgetExceeded:
            terminal = ("incomplete", "incomplete", {"error_code": "aggregate_budget_hold", "failure_classification": "permanent_protocol"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except PartialTrace:
            terminal = ("incomplete", "incomplete", {"error_code": "partial_trace", "failure_classification": "transient"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except TimeoutError:
            await self._cancel_with_timeout(adapter, prepared, lease, "timeout_cancel_failed")
            terminal = ("failed", "timed_out", {"error_code": "adapter_timeout", "failure_classification": "transient_adapter"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except MissingOutputEvidence:
            terminal = ("failed", "failed", {"error_code": "output_artifact_evidence_missing", "failure_classification": "permanent_protocol"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)
        except Exception as exc:  # noqa: BLE001 - durable workers must turn all adapter faults into evidence
            terminal = ("failed", "failed", {"error_code": type(exc).__name__, "failure_classification": "permanent_protocol"})
            return await self._finish(lease, terminal, adapter, prepared, evidence)

    async def _finish(
        self, lease: JobLease, terminal: tuple[str, str, Mapping[str, Any]], adapter: Any, prepared: Any,
        evidence: AttemptEvidence,
    ) -> WorkerResult:
        metadata = dict(terminal[2])
        if adapter is not None and prepared is not None:
            if "artifact_digests" not in metadata:
                try:
                    digests, ids = self._persist_artifacts(await adapter.collect_artifacts(prepared))
                    metadata.update({"artifact_digests": digests, "artifact_ids": ids})
                except Exception as exc:  # noqa: BLE001 - retain terminal evidence if artifact capture fails
                    metadata["artifact_persistence_error"] = type(exc).__name__
            try:
                await adapter.cleanup_attempt(prepared)
            except Exception as exc:  # noqa: BLE001 - diagnostics must not replace the terminal outcome
                if lease.attempt_id is not None:
                    self.jobs.record_diagnostic(lease.attempt_id, "cleanup_failed", {"error_code": type(exc).__name__})
        if evidence.trace_artifact_digest is None and evidence.trace_events:
            try:
                evidence.trace_artifact_digest = self._persist_trace(evidence.trace_events)
            except Exception as exc:  # noqa: BLE001 - partial evidence must not replace the terminal outcome
                metadata["trace_persistence_error"] = type(exc).__name__
        metadata.update({
            "input_artifact_digest": evidence.input_artifact_digest,
            "output_artifact_digest": evidence.output_artifact_digest,
            "trace_artifact_digest": evidence.trace_artifact_digest,
            "trace_complete": evidence.trace_complete,
        })
        return self._terminal(lease, terminal[0], terminal[1], metadata)

    async def _execute_supervised(
        self, adapter: Any, prepared: Any, lease: JobLease, envelope: AttemptEnvelope, harness: HarnessSpec,
        trace_events: list[TraceEvent],
    ) -> ResultBundle:
        events_task = asyncio.create_task(self._collect_events(adapter, prepared, envelope, trace_events))
        execute_task = asyncio.create_task(adapter.execute_attempt(prepared))
        lease_seconds = max(0.05, (lease.expires_at - datetime.now(UTC)).total_seconds())
        supervisor = asyncio.create_task(self._supervise(adapter, prepared, lease, lease_seconds))
        timeout = min(harness.timeout_seconds, envelope.budget.max_latency_seconds)
        deadline = monotonic() + timeout
        try:
            done, _ = await asyncio.wait({execute_task, supervisor}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError
            if supervisor in done:
                reason = supervisor.result()
                if reason == "lease_lost":
                    raise LeaseLost
                if reason == "cancel_requested":
                    raise CancellationRequested
            if self.jobs.cancel_requested(lease.id, lease.owner, lease_token=lease.token):
                await adapter.cancel_attempt(prepared)
                raise CancellationRequested
            result = execute_task.result()
            # The adapter may buffer final trace records after it returns its
            # result. Keep supervision alive and drain that bounded tail; a
            # non-closing stream is incomplete evidence, never completion.
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise PartialTrace
            drained, _ = await asyncio.wait({events_task, supervisor}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if supervisor in drained:
                reason = supervisor.result()
                if reason == "lease_lost":
                    raise LeaseLost
                if reason == "cancel_requested":
                    raise CancellationRequested
            if events_task not in drained:
                raise PartialTrace
            events_task.result()
            return result
        finally:
            for task in (supervisor, events_task, execute_task):
                if not task.done():
                    task.cancel()
            for task in (supervisor, events_task, execute_task):
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _supervise(self, adapter: Any, prepared: Any, lease: JobLease, lease_seconds: float) -> str:
        interval = min(1.0, max(0.01, lease_seconds / 3))
        while True:
            await asyncio.sleep(interval)
            cancel = self.jobs.cancel_requested(lease.id, lease.owner, lease_token=lease.token)
            if cancel is None or not self.jobs.heartbeat(lease.id, lease.owner, lease_token=lease.token, lease_seconds=lease_seconds):
                with contextlib.suppress(Exception):
                    await adapter.cancel_attempt(prepared)
                return "lease_lost"
            if cancel:
                with contextlib.suppress(Exception):
                    await adapter.cancel_attempt(prepared)
                return "cancel_requested"

    async def _cancel_with_timeout(self, adapter: Any, prepared: Any, lease: JobLease, diagnostic: str) -> None:
        if adapter is None or prepared is None:
            return
        try:
            await asyncio.wait_for(adapter.cancel_attempt(prepared), timeout=1.0)
        except Exception as exc:  # noqa: BLE001 - timeout cleanup evidence must remain redacted
            if lease.attempt_id is not None:
                self.jobs.record_diagnostic(lease.attempt_id, diagnostic, {"error_code": type(exc).__name__})

    async def _collect_events(
        self, adapter: Any, prepared: Any, envelope: AttemptEnvelope, trace_events: list[TraceEvent],
    ) -> None:
        previous = -1
        async for event in adapter.stream_events(prepared):
            event = TraceEvent.model_validate_json(canonical_json(event.model_dump(mode="json")))
            if event.attempt_id != envelope.attempt_id or event.episode_id != envelope.episode_id or event.sequence <= previous:
                raise ValueError("invalid streamed trace event")
            previous = event.sequence
            trace_events.append(event)
            self.repository.append_attempt_event(envelope.attempt_id, "trace", event.model_dump(mode="json"))

    def _mark_started(self, lease: JobLease) -> None:
        with self.repository.transaction(immediate=True) as conn:
            conn.execute(attempts.update().where(attempts.c.id == lease.attempt_id, attempts.c.status == "queued").values(status="running"))
            conn.execute(executions.update().where(executions.c.id == lease.execution_id, executions.c.status == "queued").values(status="running", started_at=datetime.now(UTC)))
        self.repository.append_attempt_event(str(lease.attempt_id), "started", {"job_id": lease.id, "lease_owner": lease.owner})

    def _validate_scenario_binding(self, lease: JobLease, input: AttemptInput) -> None:
        if lease.attempt_id is None:
            raise ValueError("attempt job lease is missing attempt_id")
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(
                attempts.c.id, attempts.c.episode_id, episodes.c.execution_id, episodes.c.scenario_id,
            ).join(episodes, episodes.c.id == attempts.c.episode_id).where(attempts.c.id == lease.attempt_id)).mappings().first()
        if row is None:
            raise ValueError("leased attempt is not persisted")
        if input.attempt.episode_id != row["episode_id"]:
            raise ValueError("attempt input episode_id does not match persisted attempt")
        if row["execution_id"] != lease.execution_id:
            raise ValueError("leased attempt does not belong to the leased execution")
        if row["scenario_id"] is None or input.scenario.scenario_id != row["scenario_id"]:
            raise ValueError("attempt input scenario_id does not match persisted episode")

    def _reserve_once(self, lease: JobLease, envelope: AttemptEnvelope) -> str:
        existing = self.budgets.latest_for_attempt(envelope.attempt_id)
        if existing is not None:
            return str(existing["id"])
        aggregate = lease.payload.get("aggregate_budget")
        if aggregate is not None and not isinstance(aggregate, Mapping):
            raise ValueError("aggregate_budget job payload must be an object")
        return self.budgets.reserve_with_aggregate(
            lease.execution_id, envelope.attempt_id, model_id=envelope.provider_model,
            max_cost_usd=envelope.budget.max_cost_usd,
            max_attempts=int(aggregate["max_attempts"]) if aggregate else None,
            max_total_cost_usd=float(aggregate["max_total_cost_usd"]) if aggregate else None,
            max_tokens=envelope.budget.max_tokens,
            max_tool_calls=envelope.budget.max_tool_calls,
            max_total_tokens=int(aggregate["max_total_tokens"]) if aggregate else None,
            max_total_tool_calls=int(aggregate["max_total_tool_calls"]) if aggregate else None,
        )

    @staticmethod
    def _enforce_usage(
        result: ResultBundle, envelope: AttemptEnvelope, *, claim_eligibility: str, require_complete: bool = True,
    ) -> None:
        usage = result.usage
        if usage is None:
            if require_complete:
                raise MissingUsageEvidence
            return
        if require_complete and claim_eligibility != "fixture_only" and (usage.evidence_source != "provider_reported" or not usage.complete_evidence):
            raise MissingUsageEvidence
        if require_complete and claim_eligibility == "fixture_only" and (
            usage.total_tokens is None or usage.context_tokens is None or usage.tool_calls is None
        ):
            raise MissingUsageEvidence
        if usage.total_tokens is not None and ((usage.input_tokens is None) != (usage.output_tokens is None)):
            raise UsageMismatch
        total_tokens = usage.total_tokens
        if total_tokens is not None and total_tokens > envelope.budget.max_tokens:
            raise UsageMismatch
        if usage.context_tokens is not None and usage.context_tokens > envelope.budget.max_context_tokens:
            raise UsageMismatch
        if usage.tool_calls is not None and usage.tool_calls > envelope.budget.max_tool_calls:
            raise UsageMismatch
        pinned = getattr(envelope, "pinned_endpoint_digest", None)
        if require_complete and claim_eligibility != "fixture_only" and (
            usage.observed_provider_version is None or usage.observed_endpoint_digest is None
            or (pinned is not None and usage.observed_endpoint_digest != pinned)
        ):
            raise MissingUsageEvidence

    @staticmethod
    def _validate_result_lifecycle(result: ResultBundle, envelope: AttemptEnvelope) -> None:
        if envelope.started_at is None:
            raise ValueError("started envelope is required before result terminalization")
        if result.completed_at < envelope.started_at:
            raise ValueError("result completed_at precedes attempt start")
        if result.attempt_id != envelope.attempt_id:
            raise ValueError("result attempt_id does not match attempt envelope")
        if envelope.response_hash is not None and result.response_hash != envelope.response_hash:
            raise ValueError("result response_hash does not match attempt envelope")

    @staticmethod
    def _terminal_envelope(
        envelope: AttemptEnvelope, result: ResultBundle, *, status: str,
    ) -> Mapping[str, Any]:
        usage = result.usage
        terminal = envelope.model_copy(update={
            "status": status,
            "completed_at": result.completed_at,
            "response_hash": result.response_hash,
            "observed_provider_version": usage.observed_provider_version if usage else None,
            "observed_endpoint_digest": usage.observed_endpoint_digest if usage else None,
        })
        return json.loads(canonical_json(terminal.model_dump(mode="json")))

    def _derive_manipulation_evidence(
        self, envelope: AttemptEnvelope, trace_events: list[TraceEvent],
    ) -> tuple[bool, str, str | None]:
        bound_factor_ids = set(envelope.factor_assignments)
        fidelity = [
            {"sequence": event.sequence, "payload": event.payload}
            for event in trace_events
            if event.payload.get("event") == "factor_fidelity"
        ]
        detail: str | None = None
        if not bound_factor_ids:
            passed = True
        else:
            by_factor: dict[str, list[Mapping[str, Any]]] = {}
            malformed = False
            for entry in fidelity:
                factor_id = entry["payload"].get("factor_id")
                if not isinstance(factor_id, str):
                    malformed = True
                    continue
                by_factor.setdefault(factor_id, []).append(entry)
            observed_factor_ids = set(by_factor)
            if malformed or observed_factor_ids != bound_factor_ids:
                passed = False
                detail = "factor_fidelity_keys_do_not_match_bound_factor_assignments"
            elif any(len(entries) != 1 for entries in by_factor.values()):
                passed = False
                detail = "factor_fidelity_duplicate_or_ambiguous"
            elif any(
                entry["payload"].get("passed") is not True
                or entry["payload"].get("compute_context_matched") is not True
                for entries in by_factor.values() for entry in entries
            ):
                passed = False
                detail = "factor_fidelity_failed"
            else:
                passed = True
        digest = self._persist_generated_artifact(
            canonical_json({
                "attempt_id": envelope.attempt_id,
                "factor_assignments": envelope.factor_assignments,
                "fidelity": fidelity,
                "manipulation_pass": passed,
                "detail": detail,
            }),
            media_type="application/vnd.scaffold-arena.manipulation-fidelity+json",
            metadata={"artifact_role": "manipulation_fidelity", "attempt_id": envelope.attempt_id},
        )
        return passed, digest, detail

    def _aggregate_usage_reconciliation_supported(self) -> bool:
        return {"total_tokens", "tool_calls", "reserved_max_tokens", "reserved_max_tool_calls"}.issubset(usage_ledger.c.keys())

    def _persist_generated_artifact(
        self, content: bytes, *, media_type: str, metadata: Mapping[str, str],
    ) -> str:
        digest = self.artifact_store.put_bytes(content, media_type=media_type, metadata=metadata)
        persisted = self.artifact_store.get_bytes(digest)
        if persisted != content:
            raise ValueError("artifact store reread does not match persisted content")
        self.repository.register_artifact(
            digest,
            size_bytes=len(persisted),
            storage_uri=self.artifact_store.uri_for(digest),
            media_type=media_type,
            content_metadata=metadata,
        )
        return digest

    def _persist_trace(self, events: list[TraceEvent]) -> str:
        return self._persist_generated_artifact(
            canonical_json([event.model_dump(mode="json") for event in events]),
            media_type="application/vnd.scaffold-arena.trace+json",
            metadata={"artifact_role": "trace"},
        )

    def _persist_artifacts(self, refs: tuple[ArtifactRef, ...]) -> tuple[list[str], dict[str, str]]:
        persisted: list[str] = []
        seen: set[str] = set()
        by_artifact_id: dict[str, str] = {}
        for ref in refs:
            existing = by_artifact_id.get(ref.artifact_id)
            if existing is not None:
                if existing != ref.sha256:
                    raise ValueError("logical artifact_id has conflicting digests")
                continue
            by_artifact_id[ref.artifact_id] = ref.sha256
            if ref.sha256 in seen:
                continue
            if ref.content is not None:
                digest = self.artifact_store.put_bytes(ref.content, media_type=ref.media_type)
            else:
                # A bare URI is narration; a durable execution requires bytes
                # that can be re-read and hash-checked by its configured store.
                self.artifact_store.get_bytes(ref.sha256)
                digest = ref.sha256
            if digest != ref.sha256:
                raise ValueError("artifact store digest does not match adapter artifact")
            content = self.artifact_store.get_bytes(digest)
            self.repository.register_artifact(digest, size_bytes=len(content), storage_uri=self.artifact_store.uri_for(digest), media_type=ref.media_type)
            persisted.append(digest)
            seen.add(digest)
        return persisted, by_artifact_id

    def _resolve_output_artifact(
        self, result: ResultBundle, artifact_ids: Mapping[str, str], *, require_completed: bool = False,
    ) -> str | None:
        response_artifact_id = getattr(result, "response_artifact_id", None)
        response_declared = result.response_hash is not None or response_artifact_id is not None
        if not response_declared and result.terminal_outcome != "completed" and not require_completed:
            return None
        if not isinstance(response_artifact_id, str) or result.response_hash is None:
            raise MissingOutputEvidence
        digest = artifact_ids.get(response_artifact_id)
        if digest != result.response_hash:
            raise MissingOutputEvidence
        # get_bytes is intentionally repeated even though _persist_artifacts
        # verified the artifact: this binds the completed result to re-readable
        # bytes at the exact point its completion claim is made.
        self.artifact_store.get_bytes(digest)
        return digest

    def _oracle_decision(self, scenario: ScenarioSpec, envelope: AttemptEnvelope, result: ResultBundle) -> tuple[str, str, Mapping[str, Any]] | None:
        oracle = scenario.final_state_oracle or scenario.state_oracle
        if self.state_oracle is None or oracle is None:
            return None
        decision = self.state_oracle.evaluate(scenario, oracle, envelope, result)
        if decision.terminal_outcome not in {"completed", "failed", "timed_out", "cancelled", "incomplete"}:
            raise ValueError("state oracle returned an invalid terminal outcome")
        evidence = dict(decision.evidence)
        if result.terminal_outcome != "completed" and decision.terminal_outcome == "completed":
            if evidence.get("authoritative_terminal_evidence") is not True:
                return result.terminal_outcome, "state_oracle_upgrade_denied", {
                    "limitation": "state_oracle_cannot_upgrade_noncompleted_adapter_result_without_authoritative_terminal_evidence"
                }
            evidence["limitation"] = "adapter_noncompleted_outcome_authoritatively_overridden"
        return decision.terminal_outcome, decision.detail, evidence

    def _reconcile(self, ledger_id: str, result: ResultBundle, envelope: AttemptEnvelope):
        usage = result.usage
        if usage is None or usage.input_tokens is None or usage.output_tokens is None or usage.provider_usage_digest is None:
            return self._reconcile_unknown(ledger_id, usage)
        if self.price_resolver is None:
            return self._reconcile_unknown(ledger_id, usage)
        quote = self.price_resolver.resolve(provider=envelope.provider, model_id=envelope.provider_model, usage=usage)
        if quote is None or (
            quote.provider != envelope.provider or quote.model_id != envelope.provider_model
            or quote.provider_usage_digest != usage.provider_usage_digest
        ):
            return self.budgets.mismatch(ledger_id, usage=usage)
        if usage.actual_cost_usd is not None and usage.actual_cost_usd != quote.cost_usd:
            return self.budgets.mismatch(ledger_id, usage=usage)
        if currency_exceeds(quote.cost_usd, envelope.budget.max_cost_usd):
            return self.budgets.mismatch(ledger_id, usage=usage)
        return self.budgets.reconcile(
            ledger_id, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            actual_cost_usd=quote.cost_usd, provider_usage_digest=usage.provider_usage_digest,
            price_catalog_revision=quote.price_catalog_revision, expected_cost_usd=quote.cost_usd,
            usage=usage,
        )

    def _reconcile_unknown(self, ledger_id: str, usage: ProviderUsage | None):
        return self.budgets.unknown(ledger_id, usage=usage)

    def _terminal(self, lease: JobLease, outcome: str, attempt_status: str, metadata: Mapping[str, Any]) -> WorkerResult:
        if outcome == "cancelled":
            job_outcome = "cancelled"
        elif metadata.get("captured_adapter_terminal") is True:
            job_outcome = "completed"
        else:
            job_outcome = "failed"
        if metadata.get("captured_adapter_terminal") is True:
            # The evaluator's durable work must exist before `finalize` can
            # derive an execution terminal state. This is intentionally one
            # transaction: an adapter-terminal attempt is never visible as a
            # completed execution without its queued independent evaluation.
            winner = self.jobs.finalize_with_followup(
                lease.id,
                lease.owner,
                outcome=job_outcome,
                attempt_status=attempt_status,
                followup_kind="evaluation",
                result_metadata=metadata,
                lease_token=lease.token,
            )
        else:
            winner = self.jobs.finalize(
                lease.id,
                lease.owner,
                outcome=job_outcome,
                attempt_status=attempt_status,
                result_metadata=metadata,
                lease_token=lease.token,
            )
        return WorkerResult(lease.id, winner or "lost", str(metadata.get("detail_code") or metadata.get("error_code") or "") or None)

    def retry(self, job_id: str) -> tuple[str, str]:
        return self.jobs.retry(job_id)

    def resume(self, job_id: str, harness: HarnessSpec) -> tuple[str, str]:
        if not harness.capabilities.checkpoint:
            raise ValueError("resume is forbidden because the harness does not declare checkpoint support")
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(attempts, jobs.c.payload).join(jobs, jobs.c.attempt_id == attempts.c.id).where(jobs.c.id == job_id)).mappings().first()
        if row is None:
            raise KeyError(job_id)
        checkpoint = dict(row["result_metadata"] or {}).get("checkpoint_artifact_digest")
        if not isinstance(checkpoint, str):
            raise ValueError("resume is forbidden without a checkpoint artifact")  # noqa: TRY004 - absence is fail-closed
        with self.repository.engine.connect() as conn:
            registered = conn.execute(artifacts.select().with_only_columns(artifacts.c.digest).where(artifacts.c.digest == checkpoint)).scalar_one_or_none()
        if registered != checkpoint:
            raise ValueError("resume is forbidden because the checkpoint artifact is not registered")
        original = HarnessSpec.model_validate_json(json.dumps(dict(row["payload"] or {}).get("harness", {})))
        if (harness.adapter_identity, harness.adapter_digest, harness.effective_configuration_hash, harness.configuration) != (
            original.adapter_identity, original.adapter_digest, original.effective_configuration_hash, original.configuration,
        ):
            raise ValueError("resume harness does not match the original bound harness")
        provenance = dict(row["result_metadata"] or {}).get("checkpoint_provenance")
        if not isinstance(provenance, dict) or provenance.get("artifact_digest") != checkpoint or provenance.get("adapter_digest") != original.adapter_digest:
            raise ValueError("resume is forbidden without checkpoint provenance bound to the original harness")
        self.artifact_store.get_bytes(checkpoint)
        return self.retry(job_id)


class LeaseLost(Exception):
    pass


class CancellationRequested(Exception):
    pass


class UsageMismatch(Exception):
    pass


class MissingUsageEvidence(Exception):
    pass


class PartialTrace(Exception):
    pass


class MissingOutputEvidence(Exception):
    pass
