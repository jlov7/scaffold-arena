"""Experiment expansion and durable dispatch creation (without provider work)."""

from __future__ import annotations

import random
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import insert, select

from adapters_v1.models import AttemptInput
from persistence_v1 import ArenaRepository, FrozenExperimentError
from persistence_v1.schema import (
    attempts,
    episodes,
    executions,
    experiments,
    jobs,
    study_packs,
)
from protocol_v1.canonical import canonical_json, sha256
from protocol_v1.design import expand_design, treatment_id
from protocol_v1.models import (
    AttemptEnvelope,
    ExecutionProvenance,
    ExperimentSpec,
    HarnessSpec,
    ScenarioSpec,
)


def _id() -> str:
    # Protocol identifiers must start with a lower-case letter.
    return f"x{uuid.uuid4().hex}"


def _hash(value: Any) -> str:
    return sha256(value)


@dataclass(frozen=True)
class ExecutionCreated:
    execution_id: str
    episode_ids: tuple[str, ...]
    job_ids: tuple[str, ...]
    idempotent: bool = False


class ExperimentController:
    """Creates a reproducible execution graph. It has no adapter or network access."""

    def __init__(
        self,
        repository: ArenaRepository,
        *,
        harnesses: Mapping[str, HarnessSpec] | None = None,
        scenario_specs: Mapping[str, ScenarioSpec] | None = None,
        scenario_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    ):
        self.repository = repository
        self.harnesses = dict(harnesses or {})
        self.scenario_specs = dict(scenario_specs or {})
        self.scenario_metadata = {
            key: dict(value) for key, value in (scenario_metadata or {}).items()
        }

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
        """Expand the frozen spec and enqueue jobs in one transaction.

        ``request_key`` is scoped to ``project_id``; the exact request digest
        must match to replay a response.
        """
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
        digest = _hash(
            {
                "freeze_hash": spec.freeze_hash,
                "payload": dict(request_payload or {}),
                "provenance": provenance.model_dump(mode="json"),
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
            execution_id = _id()
            aggregate_deadline_at = (
                datetime.now(UTC) + timedelta(seconds=spec.aggregate_budget.max_wall_time_seconds)
                if spec.aggregate_budget is not None
                else None
            )
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
                envelope = self._envelope(
                    spec, unit, episode_id, attempt_id, provenance
                )
                input = AttemptInput.bind(
                    scenarios[unit["scenario_id"]],
                    AttemptEnvelope.model_validate_json(canonical_json(envelope)),
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
                            "envelope": envelope,
                            "treatment_id": unit["treatment_id"],
                        },
                    )
                )
                harness = resolved_harnesses[unit["harness_id"]]
                conn.execute(
                    insert(jobs).values(
                        id=job_id,
                        execution_id=execution_id,
                        attempt_id=attempt_id,
                        kind="attempt",
                        status="queued",
                        attempt_count=0,
                        available_at=datetime.now(UTC),
                        payload={
                            "attempt_input": input.model_dump(mode="json"),
                            "harness": harness.model_dump(mode="json"),
                            "aggregate_budget": (
                                {
                                    **spec.aggregate_budget.model_dump(mode="json"),
                                    "deadline_at": aggregate_deadline_at.isoformat(),
                                }
                                if spec.aggregate_budget and aggregate_deadline_at is not None
                                else None
                            ),
                        },
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
        return ExecutionCreated(execution_id, tuple(episode_ids), tuple(job_ids))

    # Short aliases make this service convenient for non-HTTP callers.
    start = create_execution

    def _validate_frozen(self, project_id: str, spec: ExperimentSpec) -> ExperimentSpec:
        if (
            not spec.frozen
            or spec.owner_approval != "approved"
            or not spec.freeze_hash
            or not spec.study_pack_hash
        ):
            raise FrozenExperimentError(
                "execution accepts only an approved frozen ExperimentSpec with bound hashes"
            )
        try:
            canonical_spec = ExperimentSpec.model_validate_json(
                canonical_json(spec.model_dump(mode="json"))
            )
        except (TypeError, ValueError) as exc:
            raise FrozenExperimentError(
                "supplied frozen experiment is not canonical"
            ) from exc
        payload = canonical_spec.model_dump(
            mode="json", exclude={"frozen", "freeze_hash", "frozen_at"}
        )
        payload["study_pack_hash"] = canonical_spec.study_pack_hash
        expected_hash = _hash(
            {
                "protocol_version": "1.0",
                "study_pack_hash": canonical_spec.study_pack_hash,
                "experiment": payload,
            }
        )
        if canonical_spec.freeze_hash != expected_hash:
            raise FrozenExperimentError(
                "supplied frozen experiment content does not match its freeze hash"
            )
        with self.repository.engine.connect() as conn:
            row = conn.execute(
                select(
                    experiments.c.project_id,
                    experiments.c.owner_approval,
                    experiments.c.frozen_at,
                    experiments.c.spec_hash,
                    experiments.c.study_pack_hash,
                    study_packs.c.content_digest,
                )
                .join(study_packs, study_packs.c.id == experiments.c.study_pack_id)
                .where(experiments.c.id == spec.experiment_id)
            ).first()
        if (
            row is None
            or row.project_id != project_id
            or row.owner_approval != "approved"
            or row.frozen_at is None
        ):
            raise FrozenExperimentError(
                "experiment is not an approved frozen project experiment"
            )
        if (
            row.spec_hash != canonical_spec.freeze_hash
            or row.study_pack_hash != canonical_spec.study_pack_hash
            or row.content_digest != canonical_spec.study_pack_hash
        ):
            raise FrozenExperimentError(
                "experiment frozen hashes do not match the supplied spec and study pack"
            )
        return canonical_spec

    def _matrix(
        self, spec: ExperimentSpec, scenarios: Mapping[str, ScenarioSpec]
    ) -> list[dict[str, Any]]:
        treatments = expand_design(spec)
        endpoints = spec.model_endpoints or ()
        endpoint_values = endpoints or (None,)
        units: list[dict[str, Any]] = []
        for scenario_id in spec.scenario_ids:
            scenario = scenarios[scenario_id]
            comparison_key = scenario.pair_id or scenario.scenario_id
            cluster_id = scenario.cluster_id or scenario.scenario_id
            for harness_id in spec.harness_ids:
                for endpoint in endpoint_values:
                    for treatment in treatments:
                        for repetition in range(spec.repetitions):
                            analysis_pair_id = _hash(
                                {
                                    "freeze_hash": spec.freeze_hash,
                                    "scenario_comparison_key": comparison_key,
                                    "harness_id": harness_id,
                                    "endpoint_id": endpoint.endpoint_id
                                    if endpoint
                                    else None,
                                    "endpoint_digest": endpoint.endpoint_digest
                                    if endpoint
                                    else None,
                                    "provider": endpoint.provider
                                    if endpoint
                                    else "recorded",
                                    "provider_model": endpoint.model
                                    if endpoint
                                    else "recorded",
                                    "repetition_index": repetition,
                                }
                            )
                            units.append(
                                {
                                    "scenario_id": scenario_id,
                                    "harness_id": harness_id,
                                    "provider": endpoint.provider
                                    if endpoint
                                    else "recorded",
                                    "provider_model": endpoint.model
                                    if endpoint
                                    else "recorded",
                                    "endpoint_id": endpoint.endpoint_id
                                    if endpoint
                                    else None,
                                    "endpoint_digest": endpoint.endpoint_digest
                                    if endpoint
                                    else None,
                                    "treatment": dict(treatment),
                                    "treatment_id": treatment_id(treatment),
                                    "repetition": repetition,
                                    "scenario_variant": scenario.variant,
                                    "scenario_pair_id": comparison_key,
                                    "scenario_cluster_id": cluster_id,
                                    "repetition_index": repetition,
                                    "analysis_pair_id": analysis_pair_id,
                                }
                            )
        # A stable canonical pre-sort eliminates incidental input ordering. The
        # declared seed then defines the sole randomization source.
        units.sort(key=lambda value: _hash(value))
        schedule = spec.extensions.get("org.scaffold-arena.context-handoff-schedule-v1")
        if schedule is not None:
            # The optional extension is narrowly scoped to this frozen context
            # study.  It replaces neither expansion nor durable lifecycle.
            from .context_handoff_schedule import apply_frozen_context_schedule
            scheduled = apply_frozen_context_schedule(units, schedule, randomization_seed=spec.randomization_seed)
            for unit in scheduled:
                unit["blocks"] = self._block_values(spec, unit)
            return scheduled
        rng = random.Random(spec.randomization_seed)
        rng.shuffle(units)
        for index, unit in enumerate(units):
            unit["seed"] = int(
                _hash(
                    {"seed": spec.randomization_seed, "ordinal": index, "unit": unit}
                )[:16],
                16,
            ) % (2**31)
            unit["blocks"] = self._block_values(spec, unit)
        return units

    def _resolve_scenarios(self, spec: ExperimentSpec) -> dict[str, ScenarioSpec]:
        missing = set(spec.scenario_ids) - set(self.scenario_specs)
        if missing:
            raise ValueError(
                f"scenario specifications are required for execution: {sorted(missing)}"
            )
        resolved: dict[str, ScenarioSpec] = {}
        for scenario_id in spec.scenario_ids:
            scenario = self.scenario_specs[scenario_id]
            if not isinstance(scenario, ScenarioSpec):
                raise TypeError(
                    "scenario specifications must be exact ScenarioSpec instances"
                )
            if scenario.scenario_id != scenario_id:
                raise ValueError(
                    "scenario specification key does not match scenario_id"
                )
            # Snapshot through strict validation before any durable dispatch.
            resolved[scenario_id] = ScenarioSpec.model_validate_json(
                canonical_json(scenario.model_dump(mode="json"))
            )
        return resolved

    def _block_values(
        self, spec: ExperimentSpec, unit: Mapping[str, Any]
    ) -> dict[str, str]:
        lookup = {
            "scenario": "scenario_id",
            "harness": "harness_id",
            "model": "provider_model",
        }
        values: dict[str, str] = {}
        for block in spec.randomization_blocks:
            field = lookup.get(block.unit)
            if field is not None and str(unit[field]) in block.values:
                values[block.block_id] = str(unit[field])
            elif block.unit == "cluster":
                cluster_id = self.scenario_metadata.get(
                    str(unit["scenario_id"]), {}
                ).get("cluster_id")
                if not isinstance(cluster_id, str) or cluster_id not in block.values:
                    raise ValueError(
                        "declared cluster randomization block cannot be resolved from scenario metadata"
                    )
                values[block.block_id] = cluster_id
        return values

    @staticmethod
    def _envelope(
        spec: ExperimentSpec,
        unit: Mapping[str, Any],
        episode_id: str,
        attempt_id: str,
        provenance: ExecutionProvenance,
    ) -> dict[str, Any]:
        request_hash = _hash(
            {
                "freeze_hash": spec.freeze_hash,
                "episode_id": episode_id,
                "attempt_id": attempt_id,
                "unit": dict(unit),
                "provenance": provenance.model_dump(mode="json"),
            }
        )
        return AttemptEnvelope(
            attempt_id=attempt_id,
            episode_id=episode_id,
            ordinal=1,
            provider_model=str(unit["provider_model"]),
            provider=str(unit["provider"]),
            endpoint_id=unit["endpoint_id"],
            pinned_endpoint_digest=unit["endpoint_digest"],
            harness_id=str(unit["harness_id"]),
            factor_assignments=dict(unit["treatment"]),
            budget=spec.budgets,
            provenance=provenance,
            request_hash=request_hash,
            status="queued",
            queued_at=datetime.now(UTC),
        ).model_dump(mode="json")
