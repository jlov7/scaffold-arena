"""Durable, non-provider-running control surface for protocol-v1 executions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import func, select, update

from artifacts_v1 import ArtifactStore
from execution_v1.controller import ExperimentController
from persistence_v1 import ArenaRepository, FrozenExperimentError
from persistence_v1.jobs import TERMINAL_JOB_STATUSES, JobLeaseRepository
from persistence_v1.schema import (
    artifacts,
    attempt_events,
    attempts,
    episodes,
    executions,
    experiments,
    jobs,
    study_packs,
)
from protocol_v1 import ExecutionProvenance, ExperimentSpec, HarnessSpec, StudyPack
from protocol_v1.canonical import canonical_json, sha256_bytes

from .registry import ProtocolRegistryService, RegistryError


class ExecutionError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ResumeService(Protocol):
    """Narrow bridge to a separately managed DurableWorker-like service."""

    def resume(self, job_id: str, harness: HarnessSpec) -> tuple[str, str]: ...


@dataclass(frozen=True)
class PersistedExecutionEvent:
    cursor: int
    event_id: str
    attempt_id: str
    attempt_sequence: int
    event_type: str
    payload: Mapping[str, Any]
    created_at: datetime


_CREDENTIAL_KEYS = frozenset({
    "api_key", "authorization", "bearer_token", "credential", "credentials", "password", "refresh_token", "secret",
    "access_token", "client_secret", "private_key",
})
_TERMINAL_EXECUTION_STATUSES = frozenset({"completed", "failed", "cancelled"})


class ExecutionService:
    """Durable control only. It never starts workers, adapters, or providers."""

    def __init__(
        self,
        repository: ArenaRepository,
        artifact_store: ArtifactStore,
        *,
        personal_project_id: str | None = None,
        adapter_registry: Any | None = None,
        resume_service: ResumeService | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id
        self.adapter_registry = adapter_registry
        self.resume_service = resume_service
        self.jobs = JobLeaseRepository(repository)

    def resolve_project(self, project_id: str | None) -> str:
        project_id = project_id or self.personal_project_id
        if not project_id:
            raise ExecutionError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            from persistence_v1.schema import projects

            exists = conn.execute(select(projects.c.id).where(projects.c.id == project_id)).scalar_one_or_none()
        if exists is None:
            raise ExecutionError("unknown_project", "The supplied project does not exist.", status_code=404)
        return project_id

    def create_execution(
        self, experiment_id: str, raw_provenance: Mapping[str, Any], *, project_id: str | None, request_key: str | None,
    ) -> dict[str, Any]:
        if not request_key:
            raise ExecutionError("idempotency_key_required", "Idempotency-Key is required.")
        project_id = self.resolve_project(project_id)
        spec, pack = self._load_frozen_experiment(project_id, experiment_id)
        report = self._preflight(project_id, experiment_id, spec=spec)
        if report["verdict"] != "PASS":
            raise ExecutionError("preflight_hold", "Execution is blocked by the stored preflight report.", status_code=409)
        try:
            provenance = ExecutionProvenance.model_validate_json(canonical_json(dict(raw_provenance)))
        except (ValidationError, ValueError, TypeError) as exc:
            raise ExecutionError("invalid_provenance", "An explicit valid ExecutionProvenance body is required.") from exc
        harnesses = {harness.harness_id: harness for harness in pack.harnesses}
        scenarios = {scenario.scenario_id: scenario for scenario in pack.scenarios}
        scenario_metadata = {scenario.scenario_id: {"cluster_id": scenario.cluster_id} for scenario in pack.scenarios}
        controller = ExperimentController(
            self.repository,
            harnesses=harnesses,
            scenario_specs=scenarios,
            scenario_metadata=scenario_metadata,
        )
        try:
            created = controller.create_execution(
                project_id, spec, request_key=request_key, provenance=provenance,
                request_payload={"experiment_id": experiment_id}, harnesses=harnesses,
            )
        except FrozenExperimentError as exc:
            raise ExecutionError("frozen_state_mismatch", "The stored frozen experiment cannot be executed.", status_code=409) from exc
        except ValueError as exc:
            raise ExecutionError("execution_rejected", "The stored protocol bindings rejected execution creation.", status_code=409) from exc
        return {
            "execution_id": created.execution_id, "expected_attempts": len(created.job_ids), "job_ids": list(created.job_ids),
            "idempotent_replay": created.idempotent, "provider_execution_started_by_request": False,
            "claim_ceiling": "durable dispatch created only; no provider execution or outcome evidence",
        }

    def list_executions(
        self, *, project_id: str | None, experiment_id: str | None = None, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        limit, offset = self._page(limit, offset)
        statement = select(executions, experiments.c.project_id).join(
            experiments, executions.c.experiment_id == experiments.c.id,
        ).where(experiments.c.project_id == project_id)
        if experiment_id is not None:
            statement = statement.where(executions.c.experiment_id == experiment_id)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(statement.order_by(executions.c.created_at, executions.c.id).offset(offset).limit(limit + 1)).mappings().all()
        page = rows[:limit]
        return {
            "executions": [self._execution_summary(row) for row in page],
            "pagination": {"limit": limit, "offset": offset, "next_offset": offset + limit if len(rows) > limit else None},
            "claim_ceiling": "durable execution status only; no provider execution or outcome correctness claim",
        }

    def execution(self, execution_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        row = self._execution_row(project_id, execution_id, required=True)
        assert row is not None
        with self.repository.engine.connect() as conn:
            attempt_rows = conn.execute(select(
                attempts.c.id, attempts.c.status, attempts.c.ordinal, attempts.c.created_at,
                episodes.c.id.label("episode_id"), episodes.c.ordinal.label("episode_ordinal"), episodes.c.scenario_id,
            ).join(episodes, attempts.c.episode_id == episodes.c.id).where(
                episodes.c.execution_id == execution_id,
            ).order_by(episodes.c.ordinal, attempts.c.ordinal, attempts.c.id)).mappings().all()
            job_rows = conn.execute(select(
                jobs.c.id, jobs.c.attempt_id, jobs.c.kind, jobs.c.status, jobs.c.attempt_count,
                jobs.c.available_at, jobs.c.cancel_requested_at, jobs.c.created_at,
            ).where(jobs.c.execution_id == execution_id).order_by(jobs.c.created_at, jobs.c.id)).mappings().all()
        attempts_summary = [{
            "attempt_id": item["id"], "episode_id": item["episode_id"], "episode_ordinal": item["episode_ordinal"],
            "scenario_id": item["scenario_id"], "ordinal": item["ordinal"], "status": item["status"], "created_at": item["created_at"],
        } for item in attempt_rows]
        jobs_summary = [{
            "job_id": item["id"], "attempt_id": item["attempt_id"], "kind": item["kind"], "status": item["status"],
            "attempt_count": item["attempt_count"], "available_at": item["available_at"],
            "cancel_requested_at": item["cancel_requested_at"], "created_at": item["created_at"],
        } for item in job_rows]
        return {
            **self._execution_summary(row),
            "attempts": attempts_summary,
            "jobs": jobs_summary,
            "counts": {"attempts": len(attempts_summary), "jobs": len(jobs_summary)},
            "claim_ceiling": "durable execution status only; no provider execution or outcome correctness claim",
        }

    def events(self, execution_id: str, *, project_id: str | None, cursor: str | None) -> tuple[list[PersistedExecutionEvent], str | None]:
        project_id = self.resolve_project(project_id)
        self._execution_row(project_id, execution_id, required=True)
        cursor_value = self._parse_cursor(cursor) if cursor else 0
        result: list[PersistedExecutionEvent] = []
        try:
            rows, status = self.repository.list_execution_events_with_status_after(execution_id, cursor_value)
        except ValueError as exc:
            raise ExecutionError("event_integrity_mismatch", "Execution event integrity could not be verified.", status_code=409) from exc
        for row in rows:
            result.append(PersistedExecutionEvent(
                cursor=int(row["execution_sequence"]), event_id=str(row["id"]), attempt_id=str(row["attempt_id"]),
                attempt_sequence=int(row["sequence"]), event_type=str(row["event_type"]),
                payload=self._redact(dict(row["payload"] or {})), created_at=self._as_utc(row["created_at"]),
            ))
        return result, str(status) if status in _TERMINAL_EXECUTION_STATUSES else None

    def cancel(self, execution_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        before = self._execution_row(project_id, execution_id, required=True)
        with self.repository.engine.connect() as conn:
            job_ids = list(conn.execute(select(jobs.c.id).where(
                jobs.c.execution_id == execution_id, jobs.c.status.not_in(TERMINAL_JOB_STATUSES),
            )).scalars())
            running_before = int(conn.execute(select(func.count()).select_from(jobs).where(
                jobs.c.execution_id == execution_id, jobs.c.status == "running",
            )).scalar_one())
        requested = sum(1 for job_id in job_ids if self.jobs.request_cancel(str(job_id)))
        self._refresh_execution_terminal(execution_id)
        current = self._execution_row(project_id, execution_id, required=True)
        return {
            "execution_id": execution_id, "status": current["status"], "cancellation_requested_jobs": requested,
            "already_terminal": before["status"] in _TERMINAL_EXECUTION_STATUSES,
            "running_jobs_before_request": running_before, "provider_execution_started_by_request": False,
        }

    def resume(self, execution_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        self._execution_row(project_id, execution_id, required=True)
        if self.resume_service is None:
            raise ExecutionError("resume_unavailable", "Resume requires an explicitly injected durable resume service.", status_code=409)
        with self.repository.engine.connect() as conn:
            candidates = conn.execute(select(jobs).where(
                jobs.c.execution_id == execution_id, jobs.c.status == "failed", jobs.c.attempt_id.is_not(None),
            ).order_by(jobs.c.created_at, jobs.c.id)).mappings().all()
        if len(candidates) != 1:
            raise ExecutionError("resume_target_required", "Resume requires exactly one failed attempt job.", status_code=409)
        job = dict(candidates[0])
        try:
            harness = HarnessSpec.model_validate(dict(job["payload"] or {}).get("harness", {}))
        except ValidationError as exc:
            raise ExecutionError("resume_harness_invalid", "The persisted harness binding is invalid.", status_code=409) from exc
        self._validate_resume_checkpoint(str(job["attempt_id"]), harness)
        try:
            attempt_id, job_id = self.resume_service.resume(str(job["id"]), harness)
        except (KeyError, ValueError, OSError) as exc:
            raise ExecutionError("resume_hold", "The persisted checkpoint cannot be resumed safely.", status_code=409) from exc
        return {
            "execution_id": execution_id, "attempt_id": attempt_id, "job_id": job_id, "provider_execution_started_by_request": False,
            "claim_ceiling": "resume job enqueued only; no provider execution or outcome evidence",
        }

    def attempt(self, attempt_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(attempts, episodes.c.execution_id, executions.c.status.label("execution_status")).join(
                episodes, attempts.c.episode_id == episodes.c.id,
            ).join(executions, episodes.c.execution_id == executions.c.id).join(
                experiments, executions.c.experiment_id == experiments.c.id,
            ).where(attempts.c.id == attempt_id, experiments.c.project_id == project_id)).mappings().first()
        if row is None:
            raise ExecutionError("attempt_not_found", "The requested attempt was not found.", status_code=404)
        envelope = dict(row["request_metadata"] or {}).get("envelope", {})
        request = {key: envelope.get(key) for key in ("harness_id", "provider", "provider_model", "endpoint_id", "status", "request_hash")} if isinstance(envelope, dict) else {}
        return {
            "attempt_id": row["id"], "execution_id": row["execution_id"], "status": row["status"],
            "execution_status": row["execution_status"], "ordinal": row["ordinal"], "request": self._redact(request),
            "result": self._redact(dict(row["result_metadata"] or {})),
        }

    def trace(self, attempt_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        with self.repository.engine.connect() as conn:
            owned = conn.execute(select(attempts.c.id).join(episodes, attempts.c.episode_id == episodes.c.id).join(
                executions, episodes.c.execution_id == executions.c.id,
            ).join(experiments, executions.c.experiment_id == experiments.c.id).where(
                attempts.c.id == attempt_id, experiments.c.project_id == project_id,
            )).scalar_one_or_none()
            rows = conn.execute(select(attempt_events).where(attempt_events.c.attempt_id == attempt_id).order_by(
                attempt_events.c.sequence, attempt_events.c.id,
            )).mappings().all() if owned else []
        if owned is None:
            raise ExecutionError("attempt_not_found", "The requested attempt was not found.", status_code=404)
        return {"attempt_id": attempt_id, "events": [
            {"event_id": row["id"], "sequence": row["sequence"], "event_type": row["event_type"],
             "payload": self._redact(dict(row["payload"] or {})), "created_at": row["created_at"]}
            for row in rows
        ]}

    def _preflight(self, project_id: str, experiment_id: str, *, spec: ExperimentSpec) -> dict[str, Any]:
        try:
            report = ProtocolRegistryService(
                self.repository, self.artifact_store, personal_project_id=project_id, adapter_registry=self.adapter_registry,
            ).preflight(
                experiment_id, project_id=project_id,
            )
        except RegistryError as exc:
            raise ExecutionError("preflight_hold", "The stored experiment cannot pass execution preflight.", status_code=409) from exc
        if spec.claim_bearing and self.adapter_registry is None:
            report = dict(report)
            report["verdict"] = "HOLD"
            report["blockers"] = list(report.get("blockers", [])) + [{
                "code": "trusted_adapter_registry_required", "scope": "execution",
                "message": "Claim-bearing execution requires an injected trusted adapter registry.",
            }]
        return report

    def _load_frozen_experiment(self, project_id: str, experiment_id: str) -> tuple[ExperimentSpec, StudyPack]:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(experiments, study_packs.c.content_digest).join(
                study_packs, experiments.c.study_pack_id == study_packs.c.id,
            ).where(experiments.c.id == experiment_id, experiments.c.project_id == project_id)).mappings().first()
        if row is None:
            raise ExecutionError("experiment_not_found", "The requested experiment was not found.", status_code=404)
        try:
            spec = ExperimentSpec.model_validate_json(canonical_json(dict(row["definition"] or {})))
        except (ValidationError, ValueError, TypeError) as exc:
            raise ExecutionError("frozen_state_mismatch", "The stored experiment definition is invalid.", status_code=409) from exc
        frozen_at = self._as_utc(row["frozen_at"]) if row["frozen_at"] is not None else None
        if not (
            spec.frozen and spec.owner_approval == "approved" and frozen_at is not None and spec.frozen_at is not None
            and self._as_utc(spec.frozen_at) == frozen_at and spec.freeze_hash == row["spec_hash"]
            and spec.study_pack_hash == row["study_pack_hash"] == row["content_digest"]
        ):
            raise ExecutionError("frozen_state_mismatch", "The stored frozen bindings do not agree.", status_code=409)
        try:
            content = self.artifact_store.get_bytes(str(row["content_digest"]))
            if sha256_bytes(content) != row["content_digest"]:
                raise ValueError("digest mismatch")
            files = ProtocolRegistryService._decode_bundle(content)
            pack = StudyPack.model_validate_json(files["study-pack.json"])
            if canonical_json(pack.model_dump(mode="json")) != files["study-pack.json"]:
                raise ValueError("noncanonical manifest")
        except (OSError, RegistryError, ValidationError, ValueError, TypeError) as exc:
            raise ExecutionError("study_pack_unavailable", "The exact frozen study pack cannot be revalidated.", status_code=409) from exc
        if not set(spec.scenario_ids).issubset({item.scenario_id for item in pack.scenarios}) or not set(spec.harness_ids).issubset({item.harness_id for item in pack.harnesses}):
            raise ExecutionError("cross_pack_reference", "The frozen experiment references unavailable pack content.", status_code=409)
        return spec, pack

    def _execution_row(self, project_id: str, execution_id: str, *, required: bool) -> Mapping[str, Any] | None:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(executions).join(experiments, executions.c.experiment_id == experiments.c.id).where(
                executions.c.id == execution_id, experiments.c.project_id == project_id,
            )).mappings().first()
        if row is None and required:
            raise ExecutionError("execution_not_found", "The requested execution was not found.", status_code=404)
        return dict(row) if row else None

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ExecutionError("invalid_limit", "The list limit must be an integer from 1 to 100.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ExecutionError("invalid_offset", "The list offset must be a nonnegative integer.")
        return limit, offset

    @staticmethod
    def _execution_summary(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "execution_id": row["id"], "experiment_id": row["experiment_id"], "status": row["status"],
            "started_at": row["started_at"], "completed_at": row["completed_at"], "created_at": row["created_at"],
        }

    def _execution_terminal_marker(self, project_id: str, execution_id: str) -> str | None:
        row = self._execution_row(project_id, execution_id, required=True)
        return str(row["status"]) if row and row["status"] in _TERMINAL_EXECUTION_STATUSES else None

    def _refresh_execution_terminal(self, execution_id: str) -> None:
        with self.repository.transaction(immediate=True) as conn:
            statuses = set(conn.execute(select(jobs.c.status).where(jobs.c.execution_id == execution_id)).scalars())
            if statuses and statuses.issubset(TERMINAL_JOB_STATUSES):
                status = "completed" if statuses == {"completed"} else "cancelled" if statuses == {"cancelled"} else "failed"
                conn.execute(update(executions).where(executions.c.id == execution_id).values(status=status, completed_at=datetime.now(UTC)))

    def _validate_resume_checkpoint(self, attempt_id: str, harness: HarnessSpec) -> None:
        if not harness.capabilities.checkpoint:
            raise ExecutionError("resume_hold", "Resume is forbidden because the harness has no checkpoint capability.", status_code=409)
        with self.repository.engine.connect() as conn:
            result = conn.execute(select(attempts.c.result_metadata).where(attempts.c.id == attempt_id)).scalar_one_or_none()
        checkpoint = dict(result or {}).get("checkpoint_artifact_digest")
        if not isinstance(checkpoint, str):
            raise ExecutionError("resume_hold", "Resume is forbidden without a checkpoint artifact.", status_code=409)
        with self.repository.engine.connect() as conn:
            registered = conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == checkpoint)).scalar_one_or_none()
        if registered != checkpoint:
            raise ExecutionError("resume_hold", "Resume checkpoint is not registered.", status_code=409)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _parse_cursor(cursor: str) -> int:
        try:
            value = int(cursor)
            if value < 0:
                raise ValueError
            return value
        except ValueError as exc:
            raise ExecutionError("invalid_cursor", "The event cursor must be a nonnegative integer.") from exc

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): "[REDACTED]" if cls._is_credential_key(str(key)) else cls._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [cls._redact(item) for item in value]
        return value

    @staticmethod
    def _is_credential_key(key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        return normalized in _CREDENTIAL_KEYS or normalized.endswith(("_secret", "_password"))
