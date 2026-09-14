"""Control-complete experiment expansion for protocol-v1 executions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from adapters_v1 import AttemptExecutionControls, AttemptInput
from persistence_v1.schema import (
    attempts,
    episodes,
    executions,
    jobs,
)
from protocol_v1.canonical import canonical_json
from protocol_v1.models import (
    AttemptEnvelope,
    ExecutionProvenance,
    ExperimentSpec,
    HarnessSpec,
)
from sqlalchemy import insert

from .controller import (
    ExecutionCreated,
    _hash,
    _id,
)
from .controller import ExperimentController as _BaseExperimentController


class ExperimentController(_BaseExperimentController):
    """Expand frozen experiments into attempts with executable controls."""

    def create_execution(
        self,
        project_id: str,
        spec: ExperimentSpec,
        *,
        request_key: str,
        provenance: ExecutionProvenance,
        request_payload: Mapping[str, Any] | None = None,
        harnesses: Mapping[str, HarnessSpec] | None = None,
    ) -> ExecutionCreated:
        if not request_key:
            raise ValueError("request_key is required")
        spec = self._validate_frozen(project_id, spec)
        if spec.budgets is None:
            raise ValueError("a durable execution requires declared attempt budgets")
        resolved_harnesses = dict(self.harnesses)
        resolved_harnesses.update(harnesses or {})
        missing = set(spec.harness_ids) - set(resolved_harnesses)
        if missing:
            raise ValueError(
                f"harness specifications are required for execution: {sorted(missing)}"
            )
        scenarios = self._resolve_scenarios(spec)
        if not isinstance(provenance, ExecutionProvenance):
            raise TypeError("an explicit immutable ExecutionProvenance is required")
        harness_bindings = {
            harness_id: resolved_harnesses[harness_id].model_dump(mode="json")
            for harness_id in sorted(spec.harness_ids)
        }
        digest = _hash(
            {
                "freeze_hash": spec.freeze_hash,
                "payload": dict(request_payload or {}),
                "provenance": provenance.model_dump(mode="json"),
                "harness_bindings": harness_bindings,
            }
        )
        with self.repository.transaction(immediate=True) as conn:
            response = self.repository.reserve_execution_idempotency(
                conn,
                project_id=project_id,
                key=request_key,
                request_digest=digest,
            )
            if response is not None:
                return ExecutionCreated(
                    execution_id=str(response["execution_id"]),
                    episode_ids=tuple(response["episode_ids"]),
                    job_ids=tuple(response["job_ids"]),
                    idempotent=True,
                )

            aggregate_started_at = datetime.now(UTC)
            aggregate_deadline_at = (
                aggregate_started_at
                + timedelta(seconds=spec.aggregate_budget.max_wall_time_seconds)
                if spec.aggregate_budget is not None
                else None
            )
            aggregate_payload = (
                {
                    **spec.aggregate_budget.model_dump(mode="json"),
                    "deadline_at": aggregate_deadline_at.isoformat(),
                }
                if spec.aggregate_budget is not None
                and aggregate_deadline_at is not None
                else None
            )
            execution_id = _id()
            conn.execute(
                insert(executions).values(
                    id=execution_id,
                    experiment_id=spec.experiment_id,
                    status="queued",
                    parameters={
                        "freeze_hash": spec.freeze_hash,
                        "request_payload": dict(request_payload or {}),
                        "provenance": provenance.model_dump(mode="json"),
                        "budget_envelope": {
                            "attempt": spec.budgets.model_dump(mode="json"),
                            "aggregate": (
                                spec.aggregate_budget.model_dump(mode="json")
                                if spec.aggregate_budget
                                else None
                            ),
                        },
                        "harness_bindings_hash": _hash(harness_bindings),
                        "aggregate_started_at": aggregate_started_at.isoformat(),
                        "aggregate_deadline_at": (
                            aggregate_deadline_at.isoformat()
                            if aggregate_deadline_at is not None
                            else None
                        ),
                    },
                )
            )
            episode_ids: list[str] = []
            job_ids: list[str] = []
            matrix = self._matrix(spec, scenarios)
            for ordinal, unit in enumerate(matrix):
                episode_id, attempt_id, job_id = _id(), _id(), _id()
                episode_ids.append(episode_id)
                job_ids.append(job_id)
                harness = resolved_harnesses[str(unit["harness_id"])]
                controls = AttemptExecutionControls.from_experiment(
                    spec,
                    seed=int(unit["seed"]),
                    harness=harness,
                )
                envelope = self._envelope(
                    spec,
                    unit,
                    episode_id,
                    attempt_id,
                    provenance,
                )
                envelope["request_hash"] = _hash(
                    {
                        "base_request_hash": envelope["request_hash"],
                        "execution_controls_digest": controls.digest,
                    }
                )
                canonical_envelope = AttemptEnvelope.model_validate_json(
                    canonical_json(envelope)
                )
                bound_input = AttemptInput.bind(
                    scenarios[str(unit["scenario_id"])],
                    canonical_envelope,
                    execution_controls=controls,
                )
                conn.execute(
                    insert(episodes).values(
                        id=episode_id,
                        execution_id=execution_id,
                        ordinal=ordinal,
                        scenario_id=unit["scenario_id"],
                        metadata_json={
                            key: value
                            for key, value in unit.items()
                            if key != "scenario_id"
                        },
                    )
                )
                conn.execute(
                    insert(attempts).values(
                        id=attempt_id,
                        episode_id=episode_id,
                        ordinal=0,
                        status="queued",
                        request_metadata={
                            "envelope": canonical_envelope.model_dump(mode="json"),
                            "treatment_id": unit["treatment_id"],
                            "execution_controls_digest": controls.digest,
                        },
                    )
                )
                conn.execute(
                    insert(jobs).values(
                        id=job_id,
                        execution_id=execution_id,
                        attempt_id=attempt_id,
                        kind="attempt",
                        status="queued",
                        attempt_count=0,
                        available_at=aggregate_started_at,
                        payload={
                            "attempt_input": bound_input.model_dump(mode="json"),
                            "harness": harness.model_dump(mode="json"),
                            "aggregate_budget": aggregate_payload,
                        },
                        # Leasing orders by created_at then ID. SQLite's
                        # default timestamp has second precision, which would
                        # randomize tied cells by UUID instead of frozen order.
                        **({"created_at": aggregate_started_at + timedelta(microseconds=ordinal)}
                           if "org.scaffold-arena.context-handoff-schedule-v1" in spec.extensions else {}),
                    )
                )
            response = {
                "execution_id": execution_id,
                "episode_ids": episode_ids,
                "job_ids": job_ids,
            }
            self.repository.complete_execution_idempotency(
                conn,
                project_id=project_id,
                key=request_key,
                request_digest=digest,
                response=response,
            )
        return ExecutionCreated(
            execution_id,
            tuple(episode_ids),
            tuple(job_ids),
        )

    start = create_execution
