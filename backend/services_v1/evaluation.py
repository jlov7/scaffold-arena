"""Durable, evaluator-owned reconstruction of one captured attempt."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from adapters_v1 import AttemptInput
from artifacts_v1 import ArtifactStore
from evaluation_v1 import (
    EvaluationContext,
    TrustedGraderRegistry,
    compile_grader_plan,
    evaluate_attempt,
    reconciled_cost_status,
)
from persistence_v1 import ArenaRepository, ImmutableEvaluationConflict
from persistence_v1.jobs import JobLease, JobLeaseRepository
from persistence_v1.schema import (
    artifacts,
    attempts,
    episodes,
    executions,
    experiments,
    jobs,
    study_packs,
)
from protocol_v1 import EvaluationRecord, OutcomeVector, StudyPack, TraceEvent
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes

from .execution import ExecutionError
from .registry import ProtocolRegistryService, RegistryError


class EvaluationError(ExecutionError):
    """Fail-closed evaluation error; no evaluator input is accepted from callers."""


_TERMINAL = frozenset({"completed", "failed", "timed_out", "cancelled", "incomplete"})
_EVALUATOR_ID = "arena-evaluator"
_EVALUATOR_VERSION = "evaluation-v1"
_EVALUATOR_DIGEST = sha256({"evaluator": _EVALUATOR_ID, "version": _EVALUATOR_VERSION})


class DurableEvaluationService:
    """Loads only project-owned, hash-checked evidence and persists one result."""

    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore,
                 registry: TrustedGraderRegistry) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.registry = registry
        self.jobs = JobLeaseRepository(repository)

    def enqueue(self, project_id: str, attempt_id: str) -> str:
        """Idempotently create the sole evaluation job for a captured terminal attempt."""
        source = self._source(project_id, attempt_id)
        metadata = self._metadata(source)
        terminal = str(metadata.get("terminal_outcome") or source["status"])
        if terminal not in _TERMINAL or not metadata.get("captured_adapter_terminal"):
            raise EvaluationError("attempt_not_captured", "Evaluation requires a captured terminal attempt.", status_code=409)
        with self.repository.transaction(immediate=True) as conn:
            existing = conn.execute(select(jobs.c.id).where(
                jobs.c.attempt_id == attempt_id, jobs.c.kind == "evaluation",
            )).scalar_one_or_none()
            if existing is not None:
                return str(existing)
        try:
            return self.jobs.enqueue(
                str(source["execution_id"]), attempt_id=attempt_id, kind="evaluation", payload={},
                job_id=f"ev-{sha256({'attempt_id': attempt_id, 'kind': 'evaluation'})[:60]}",
            )
        except IntegrityError:
            with self.repository.engine.connect() as conn:
                existing = conn.execute(select(jobs.c.id).where(
                    jobs.c.attempt_id == attempt_id, jobs.c.kind == "evaluation",
                )).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            raise

    enqueue_evaluation_job = enqueue

    def evaluate(self, project_id: str, attempt_id: str, *, lease: JobLease | None = None) -> dict[str, Any]:
        source = self._source(project_id, attempt_id)
        _spec, pack = self._frozen_pack(source)
        metadata = self._metadata(source)
        input_value = self._input(source, metadata, pack)
        status = str(metadata.get("terminal_outcome") or source["status"])
        events, trace_digest = self._trace(source, metadata, input_value, status=status)
        terminal = self._terminal(source, metadata, input_value)
        try:
            plan = compile_grader_plan(pack, input_value.scenario.scenario_id, self.registry)
        except (LookupError, TypeError, ValueError) as exc:
            raise EvaluationError("grader_plan_hold", "The frozen grader plan cannot be trusted or completed.", status_code=409) from exc
        context = self._context(metadata, events, terminal, input_value)
        cost_status, cost_usd = self._cost(metadata)
        budget_limit_usd = self._budget_limit(source, terminal)
        observed_output = status == "completed" or (
            status == "incomplete" and terminal.response_hash is not None
        )
        if observed_output:
            output_digest, output = self._output(metadata, terminal)
            try:
                evaluated = evaluate_attempt(
                    attempt=terminal, output=output, context=context, plan=plan,
                    registry=self.registry, trace_hash=trace_digest,
                    evaluation_id=f"evaluation-{attempt_id}", cost_usd=cost_usd,
                    budget_limit_usd=budget_limit_usd,
                    latency_seconds=self._latency(terminal), tool_calls=self._tool_calls(metadata),
                )
            except (LookupError, TypeError, ValueError) as exc:
                raise EvaluationError("evaluation_hold", "Captured evidence cannot satisfy the trusted evaluator.", status_code=409) from exc
            record = evaluated.record
            exclusions = list(evaluated.exclusions)
            claim_limitations = list(metadata.get("limitations") or [])
            if status == "incomplete":
                exclusions.append("provider_cost_identity_claims_hold_for_incomplete_adapter_evidence")
                claim_limitations.append("quality_scored_from_bound_output_only")
            result = {
                "record": record.model_dump(mode="json"),
                "grader_results": [item.__dict__ for item in evaluated.results],
                "qualitative_claims_eligible": evaluated.qualitative_claims_eligible,
                "exclusions": exclusions,
                "claim_limitations": sorted(set(claim_limitations)),
                "evaluator_independent": True,
                "independence_scope": "harness-separation-only",
                "external_independence": False,
            }
        else:
            output_digest = None
            record, result = self._terminal_failure(
                attempt_id, str(source["episode_id"]), status, trace_digest, bool(events), plan.deterministic_weight,
                cost_status, cost_usd, terminal, budget_limit_usd,
            )
        result_bytes = canonical_json(result)
        result_hash = sha256_bytes(result_bytes)
        result_artifact_digest = self._persist_result_artifact(attempt_id, result_bytes)
        row = {
            "id": f"evaluation-{attempt_id}", "attempt_id": attempt_id, "project_id": project_id,
            "evaluator": _EVALUATOR_ID, "evaluator_version": _EVALUATOR_VERSION,
            "evaluator_digest": _EVALUATOR_DIGEST, "score": record.outcome.mission_success,
            "result": result, "input_artifact_digest": str(metadata["input_artifact_digest"]),
            "output_artifact_digest": output_digest, "trace_artifact_digest": trace_digest,
            "grader_plan": plan.model_dump(mode="json"), "result_hash": result_hash,
            "result_artifact_digest": result_artifact_digest,
            "cost_status": cost_status, "cost_usd": cost_usd,
            "exclusion_state": "qualitative_excluded" if result.get("exclusions") else "none",
            "adjudication_state": None,
        }
        try:
            replay = self.repository.create_evaluation_record(
                project_id,
                record=row,
                lease_job_id=None if lease is None else lease.id,
                lease_owner=None if lease is None else lease.owner,
                lease_token=None if lease is None else lease.token,
            )
        except ImmutableEvaluationConflict as exc:
            if lease is not None:
                raise EvaluationError("evaluation_lease_lost", "The evaluator lease is no longer current.", status_code=409) from exc
            raise EvaluationError("evaluation_conflict", "Captured evidence conflicts with its immutable evaluation.", status_code=409) from exc
        return {"evaluation_id": row["id"], "replay": replay, "result_hash": result_hash,
                "record": result["record"]}

    def _source(self, project_id: str, attempt_id: str) -> Mapping[str, Any]:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(
                attempts.c.id.label("attempt_id"), attempts.c.status, attempts.c.request_metadata,
                attempts.c.result_metadata,
                episodes.c.id.label("episode_id"), episodes.c.scenario_id, executions.c.id.label("execution_id"),
                executions.c.parameters.label("execution_parameters"),
                executions.c.experiment_id, experiments.c.project_id, experiments.c.definition,
                experiments.c.frozen_at, experiments.c.spec_hash, experiments.c.study_pack_hash,
                experiments.c.owner_approval,
                study_packs.c.pack_key.label("study_pack_id"),
                study_packs.c.content_digest,
            ).join(episodes, attempts.c.episode_id == episodes.c.id)
             .join(executions, episodes.c.execution_id == executions.c.id)
             .join(experiments, executions.c.experiment_id == experiments.c.id)
             .join(study_packs, experiments.c.study_pack_id == study_packs.c.id)
             .where(attempts.c.id == attempt_id, experiments.c.project_id == project_id)).mappings().first()
        if row is None:
            raise EvaluationError("attempt_not_found", "The requested attempt is not in this project.", status_code=404)
        return dict(row)

    @staticmethod
    def _metadata(source: Mapping[str, Any]) -> Mapping[str, Any]:
        metadata = source.get("result_metadata")
        if not isinstance(metadata, Mapping):
            raise EvaluationError("invalid_attempt_evidence", "Attempt evidence metadata is invalid.", status_code=409)
        return metadata

    def _frozen_pack(self, source: Mapping[str, Any]) -> tuple[Any, StudyPack]:
        try:
            from protocol_v1 import ExperimentSpec
            definition = dict(source["definition"] or {})
            spec = ExperimentSpec.model_validate_json(canonical_json(definition))
            frozen_at = source["frozen_at"]
            if not (spec.experiment_id == source["experiment_id"] and spec.study_pack_id == source["study_pack_id"]
                    and spec.frozen and spec.owner_approval == "approved" and frozen_at is not None
                    and spec.frozen_at is not None
                    and self._as_utc(spec.frozen_at) == self._as_utc(frozen_at)
                    and spec.freeze_hash == source["spec_hash"]
                    and spec.study_pack_hash == source["study_pack_hash"] == source["content_digest"]):
                raise ValueError("frozen bindings disagree")
            content = self._artifact(str(source["content_digest"]))
            files = ProtocolRegistryService._decode_bundle(content)
            pack = StudyPack.model_validate_json(files["study-pack.json"])
            if canonical_json(pack.model_dump(mode="json")) != files["study-pack.json"]:
                raise ValueError("study pack is not canonical")
            return spec, pack
        except (ValidationError, ValueError, TypeError, OSError, RegistryError, KeyError) as exc:
            raise EvaluationError("frozen_evidence_hold", "Frozen experiment or StudyPack custody cannot be reverified.", status_code=409) from exc

    def _artifact(self, digest: str) -> bytes:
        with self.repository.engine.connect() as conn:
            registered = conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none()
        if registered is None:
            raise EvaluationError("artifact_not_registered", "Required evidence artifact is not registered.", status_code=409)
        try:
            content = self.artifact_store.get_bytes(digest)
        except (OSError, ValueError) as exc:
            raise EvaluationError("artifact_unavailable", "Required evidence artifact cannot be read.", status_code=409) from exc
        if sha256_bytes(content) != digest:
            raise EvaluationError("artifact_tampered", "Required evidence artifact digest does not match content.", status_code=409)
        return content

    @staticmethod
    def _as_utc(value: Any) -> Any:
        if not hasattr(value, "tzinfo"):
            return value
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _input(self, source: Mapping[str, Any], metadata: Mapping[str, Any], pack: StudyPack) -> AttemptInput:
        digest = metadata.get("input_artifact_digest")
        if not isinstance(digest, str):
            raise EvaluationError("input_missing", "Captured attempt input is required.", status_code=409)
        try:
            content = self._artifact(digest)
            value = AttemptInput.model_validate_json(content)
            if canonical_json(value.model_dump(mode="json")) != content:
                raise ValueError("attempt input is not canonical")
            if value.attempt.attempt_id != source["attempt_id"] or value.attempt.episode_id != source["episode_id"]:
                raise ValueError("attempt binding mismatch")
            if value.scenario.scenario_id != source["scenario_id"]:
                raise ValueError("scenario binding mismatch")
            if value.scenario.scenario_id not in {item.scenario_id for item in pack.scenarios}:
                raise ValueError("scenario does not belong to frozen pack")
            return value
        except (ValidationError, ValueError, TypeError) as exc:
            raise EvaluationError("input_invalid", "Captured AttemptInput cannot be revalidated.", status_code=409) from exc

    def _trace(self, source: Mapping[str, Any], metadata: Mapping[str, Any], input_value: AttemptInput,
               *, status: str) -> tuple[tuple[TraceEvent, ...], str]:
        digest = metadata.get("trace_artifact_digest")
        if metadata.get("trace_complete") is not True or not isinstance(digest, str):
            raise EvaluationError("trace_incomplete", "Evaluation never reconstructs a partial trace.", status_code=409)
        try:
            content = self._artifact(digest)
            raw = json.loads(content)
            if not isinstance(raw, list):
                raise TypeError("trace must be a list")
            events = tuple(TraceEvent.model_validate_json(canonical_json(item)) for item in raw)
            canonical = canonical_json([event.model_dump(mode="json") for event in events])
            if canonical != content or (status == "completed" and not events):
                raise ValueError("trace is noncanonical or completed attempt has no events")
            previous = -1
            for event in events:
                if event.attempt_id != source["attempt_id"] or event.episode_id != source["episode_id"] or event.sequence <= previous:
                    raise ValueError("trace continuity failure")
                previous = event.sequence
            return events, digest
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise EvaluationError("trace_invalid", "Captured trace cannot be revalidated.", status_code=409) from exc

    def _terminal(self, source: Mapping[str, Any], metadata: Mapping[str, Any], input_value: AttemptInput) -> Any:
        raw = metadata.get("terminal_envelope")
        try:
            from protocol_v1 import AttemptEnvelope
            terminal = AttemptEnvelope.model_validate_json(canonical_json(raw))
            if terminal.attempt_id != source["attempt_id"] or terminal.episode_id != source["episode_id"]:
                raise ValueError("terminal attempt mismatch")
            if terminal.status != source["status"]:
                raise ValueError("stored attempt status differs from terminal evidence")
            immutable = (
                "attempt_id", "episode_id", "ordinal", "provider_model", "provider", "endpoint_id",
                "pinned_endpoint_digest", "harness_id", "factor_assignments", "budget", "provenance",
                "request_hash", "queued_at",
            )
            if any(getattr(terminal, key) != getattr(input_value.attempt, key) for key in immutable):
                raise ValueError("terminal immutable attempt fields differ from canonical input")
            if terminal.status != metadata.get("terminal_outcome"):
                raise ValueError("terminal status mismatch")
            if terminal.response_hash != metadata.get("response_hash"):
                raise ValueError("terminal response hash mismatch")
            return terminal
        except (ValidationError, ValueError, TypeError) as exc:
            raise EvaluationError("terminal_invalid", "Captured terminal envelope cannot be revalidated.", status_code=409) from exc

    def _output(self, metadata: Mapping[str, Any], terminal: Any) -> tuple[str, str]:
        digest = metadata.get("output_artifact_digest")
        if not isinstance(digest, str) or terminal.response_hash != digest:
            raise EvaluationError("output_binding_invalid", "Observed output digest must equal terminal response hash.", status_code=409)
        try:
            return digest, self._artifact(digest).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvaluationError("output_not_utf8", "Completed canonical output must be UTF-8.", status_code=409) from exc

    def _context(self, metadata: Mapping[str, Any], events: tuple[TraceEvent, ...], terminal: Any, input_value: AttemptInput) -> EvaluationContext:
        factors: dict[str, str | int | bool] = {}
        state_refs: dict[str, Any] = {}
        oracle_digest = metadata.get("state_oracle_artifact_digest")
        if oracle_digest is not None:
            if not isinstance(oracle_digest, str):
                raise EvaluationError("oracle_invalid", "State oracle reference is invalid.", status_code=409)
            try:
                oracle = json.loads(self._artifact(oracle_digest))
                if not isinstance(oracle, Mapping) or not isinstance(oracle.get("evidence"), Mapping):
                    raise TypeError("oracle evidence missing")
                state_refs.update(dict(oracle["evidence"]))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise EvaluationError("oracle_invalid", "State oracle evidence cannot be revalidated.", status_code=409) from exc
        manipulation = metadata.get("manipulation_artifact_digest")
        if manipulation is not None:
            if not isinstance(manipulation, str):
                raise EvaluationError("manipulation_invalid", "Manipulation evidence reference is invalid.", status_code=409)
            try:
                artifact = json.loads(self._artifact(manipulation))
                fidelity = [{"sequence": event.sequence, "payload": event.payload} for event in events if event.payload.get("event") == "factor_fidelity"]
                if (not isinstance(artifact, Mapping) or artifact.get("attempt_id") != terminal.attempt_id
                        or artifact.get("factor_assignments") != terminal.factor_assignments
                        or artifact.get("fidelity") != fidelity
                        or artifact.get("manipulation_pass") != metadata.get("manipulation_pass")):
                    raise ValueError("manipulation evidence mismatch")
                if artifact["manipulation_pass"] is True:
                    factors = dict(terminal.factor_assignments)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise EvaluationError("manipulation_invalid", "Manipulation evidence does not match trace-derived facts.", status_code=409) from exc
        artifact_ids = metadata.get("artifact_ids")
        if isinstance(artifact_ids, Mapping) and "context-renderer-receipt" in artifact_ids:
            receipt_digest = artifact_ids.get("context-renderer-receipt")
            request_events = [event for event in events if event.event_type == "request"]
            if not isinstance(receipt_digest, str) or len(request_events) != 1:
                raise EvaluationError("context_delivery_invalid", "Context delivery evidence is incomplete.", status_code=409)
            request_digest = request_events[0].payload.get("request_digest")
            if not isinstance(request_digest, str):
                raise EvaluationError("context_delivery_invalid", "Observed request digest is unavailable.", status_code=409)
            try:
                from adapters_v1.controls import execution_controls_for
                controls = execution_controls_for(input_value)
                receipt = json.loads(self._artifact(receipt_digest))
                state_refs["context_renderer_receipt"] = receipt
                state_refs["observed_request_digest"] = request_digest
                state_refs["frozen_request_binding"] = {"model": terminal.provider_model, "options": {"temperature": controls.temperature, "top_p": controls.top_p, "num_predict": controls.max_output_tokens, "seed": controls.seed, "num_ctx": controls.max_context_tokens}}
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise EvaluationError("context_delivery_invalid", "Context delivery receipt cannot be revalidated.", status_code=409) from exc
        # Trace payload is controlled by the harness and is never source provenance.
        return EvaluationContext(factor_assignments=factors, state_refs=state_refs)

    @staticmethod
    def _cost(metadata: Mapping[str, Any]) -> tuple[str, float | None]:
        status = metadata.get("cost_status")
        value = metadata.get("cost_usd")
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
        if status == "reconciled" and numeric:
            return "reconciled", float(value)
        if status not in {"unknown", "reserved", "mismatch", "reconciled"}:
            return "unknown", None
        return "unknown", None

    @staticmethod
    def _budget_limit(source: Mapping[str, Any], terminal: Any) -> float | None:
        """Recover only an attempt limit corroborated by its execution envelope."""
        try:
            from protocol_v1 import AttemptEnvelope, BudgetSpec

            request = source.get("request_metadata")
            execution = source.get("execution_parameters")
            if not isinstance(request, Mapping) or not isinstance(execution, Mapping):
                return None
            persisted_attempt = AttemptEnvelope.model_validate_json(
                canonical_json(request.get("envelope"))
            )
            envelope = execution.get("budget_envelope")
            if not isinstance(envelope, Mapping):
                return None
            execution_attempt = BudgetSpec.model_validate_json(
                canonical_json(envelope.get("attempt"))
            )
            if (
                persisted_attempt.attempt_id != source["attempt_id"]
                or persisted_attempt.episode_id != source["episode_id"]
                or persisted_attempt.budget != terminal.budget
                or execution_attempt != terminal.budget
            ):
                return None
            return execution_attempt.max_cost_usd
        except (ValidationError, ValueError, TypeError):
            return None

    @staticmethod
    def _tool_calls(metadata: Mapping[str, Any]) -> int:
        usage = metadata.get("usage")
        return int(usage.get("tool_calls", 0)) if isinstance(usage, Mapping) and isinstance(usage.get("tool_calls"), int) and usage["tool_calls"] >= 0 else 0

    @staticmethod
    def _latency(terminal: Any) -> float | None:
        if terminal.started_at is None or terminal.completed_at is None:
            return None
        return max(0.0, (terminal.completed_at - terminal.started_at).total_seconds())

    @staticmethod
    def _terminal_failure(attempt_id: str, episode_id: str, status: str, trace_hash: str, trace_has_events: bool,
                          deterministic_weight: float, cost_status: str, cost_usd: float | None,
                          terminal: Any, budget_limit_usd: float | None) -> tuple[EvaluationRecord, dict[str, Any]]:
        raw_label = f"adapter_terminal:{status}"
        outcome = OutcomeVector(
            protocol_version="1.0", episode_id=episode_id, mission_success=0.0,
            severe_failures=(f"adapter-terminal-{status.replace('_', '-')}",), consistency=0.0,
            cost_status=reconciled_cost_status(
                cost_usd if cost_status == "reconciled" else None, budget_limit_usd
            ),
            cost_usd=cost_usd, latency_seconds=DurableEvaluationService._latency(terminal),
            tool_calls=0, auditability=1.0 if trace_has_events else 0.0, deterministic={}, model_judged={}, human={},
        )
        record = EvaluationRecord(
            protocol_version="1.0", evaluation_id=f"evaluation-{attempt_id}", episode_id=episode_id,
            outcome=outcome, deterministic_weight=deterministic_weight,
            evaluator_version=_EVALUATOR_VERSION, trace_hash=trace_hash,
        )
        return record, {
            "record": record.model_dump(mode="json"), "grader_results": [], "exclusions": [],
            "adapter_terminal_label": raw_label,
            "evaluator_independent": True,
            "independence_scope": "harness-separation-only",
            "external_independence": False,
        }

    def _persist_result_artifact(self, attempt_id: str, content: bytes) -> str:
        digest = self.artifact_store.put_bytes(
            content, media_type="application/vnd.scaffold-arena.evaluation+json",
            metadata={"artifact_role": "evaluation", "attempt_id": attempt_id},
        )
        persisted = self.artifact_store.get_bytes(digest)
        if persisted != content or sha256_bytes(persisted) != digest:
            raise EvaluationError("result_artifact_invalid", "Evaluator result artifact cannot be re-read.", status_code=409)
        self.repository.register_artifact(
            digest, size_bytes=len(persisted), storage_uri=self.artifact_store.uri_for(digest),
            media_type="application/vnd.scaffold-arena.evaluation+json",
            content_metadata={"artifact_role": "evaluation", "attempt_id": attempt_id},
        )
        return digest
