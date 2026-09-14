from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, and_, exists, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from .schema import (
    analysis_reports,
    annotation_adjudication_dimensions,
    annotation_adjudications,
    annotation_assignments,
    annotation_batches,
    annotations,
    artifacts,
    attempt_events,
    attempts,
    audit_events,
    decision_briefs,
    episodes,
    evaluations,
    evidence_receipt_artifacts,
    evidence_receipts,
    execution_event_cursors,
    executions,
    experiments,
    idempotency_records,
    jobs,
    price_catalog,
    projects,
    reproductions,
    study_packs,
    usage_ledger,
    users,
)


class ImmutableVersionConflict(ValueError):
    pass


class FrozenExperimentError(ValueError):
    pass


class ImmutableReceiptConflict(ValueError):
    pass


class ImmutableReviewConflict(ValueError):
    pass


class ImmutableAnalysisConflict(ValueError):
    pass


class ImmutableDecisionConflict(ValueError):
    pass


class ImmutableEvaluationConflict(ValueError):
    pass


_SEMVER = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _id() -> str:
    # Durable IDs may be embedded in strict protocol objects. Prefix UUID hex
    # so every new repository-generated identity satisfies Identifier.
    return f"x{uuid.uuid4().hex}"


def _require_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")


def _insert_on_conflict_do_nothing(
    conn: Connection,
    table: Any,
    values: Mapping[str, Any],
    *,
    index_elements: tuple[str, ...],
):
    if conn.dialect.name == "postgresql":
        statement = postgresql_insert(table)
    elif conn.dialect.name == "sqlite":
        statement = sqlite_insert(table)
    else:
        raise ValueError("conflict-safe persistence requires SQLite or PostgreSQL")
    return statement.values(**values).on_conflict_do_nothing(index_elements=index_elements)


def _frozen_timestamp(definition: Mapping[str, Any]) -> datetime:
    value = definition.get("frozen_at")
    if not isinstance(value, str):
        raise FrozenExperimentError(
            "frozen_definition requires a JSON frozen_at timestamp"
        )
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FrozenExperimentError(
            "frozen_definition frozen_at must be an ISO-8601 timestamp"
        ) from exc
    if timestamp.tzinfo is None:
        raise FrozenExperimentError(
            "frozen_definition frozen_at must be timezone-aware"
        )
    return timestamp.astimezone(UTC)


def append_attempt_event_in_transaction(
    conn: Connection,
    attempt_id: str,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    *,
    event_id: str | None = None,
) -> int:
    """Append an event while serializing the execution-wide cursor."""
    execution_id = conn.execute(
        select(episodes.c.execution_id)
        .select_from(attempts.join(episodes, attempts.c.episode_id == episodes.c.id))
        .where(attempts.c.id == attempt_id)
    ).scalar_one_or_none()
    if execution_id is None:
        raise ValueError(f"attempt {attempt_id} does not exist")
    if conn.dialect.name == "postgresql":
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:execution_id))"),
            {"execution_id": execution_id},
        )

    cursor = conn.execute(
        select(execution_event_cursors.c.last_sequence).where(
            execution_event_cursors.c.execution_id == execution_id
        )
    ).scalar_one_or_none()
    if cursor is None:
        execution_sequence = 1
        conn.execute(
            insert(execution_event_cursors).values(
                execution_id=execution_id, last_sequence=execution_sequence
            )
        )
    else:
        execution_sequence = int(cursor) + 1
        conn.execute(
            update(execution_event_cursors)
            .where(execution_event_cursors.c.execution_id == execution_id)
            .values(last_sequence=execution_sequence)
        )

    sequence = (
        int(
            conn.execute(
                select(func.coalesce(func.max(attempt_events.c.sequence), 0)).where(
                    attempt_events.c.attempt_id == attempt_id
                )
            ).scalar_one()
        )
        + 1
    )
    conn.execute(
        insert(attempt_events).values(
            id=event_id or _id(),
            attempt_id=attempt_id,
            execution_id=execution_id,
            sequence=sequence,
            execution_sequence=execution_sequence,
            event_type=event_type,
            payload=dict(payload or {}),
        )
    )
    return sequence


class ArenaRepository:
    """Small SQLAlchemy Core repository; callers own all service-level policy."""

    def __init__(self, engine: Engine):
        self.engine = engine

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            tx = None
            try:
                if immediate and self.engine.dialect.name == "sqlite":
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    tx = conn.begin()
                yield conn
                if tx is None:
                    conn.commit()
                else:
                    tx.commit()
            except BaseException:
                if tx is None:
                    conn.rollback()
                else:
                    tx.rollback()
                raise

    def create_project(
        self,
        name: str,
        *,
        project_id: str | None = None,
        description: str | None = None,
    ) -> str:
        project_id = project_id or _id()
        with self.transaction() as conn:
            conn.execute(
                insert(projects).values(
                    id=project_id, name=name, description=description
                )
            )
        return project_id

    def create_user(
        self,
        project_id: str,
        *,
        user_id: str | None = None,
        email: str | None = None,
        display_name: str | None = None,
    ) -> str:
        user_id = user_id or _id()
        with self.transaction() as conn:
            conn.execute(
                insert(users).values(
                    id=user_id,
                    project_id=project_id,
                    email=email,
                    display_name=display_name,
                )
            )
        return user_id

    def register_artifact(
        self,
        digest: str,
        *,
        size_bytes: int,
        storage_uri: str,
        media_type: str = "application/octet-stream",
        content_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        values = {
            "digest": digest,
            "size_bytes": size_bytes,
            "storage_uri": storage_uri,
            "media_type": media_type,
            "metadata_json": dict(content_metadata or {}),
        }
        with self.transaction() as conn:
            conn.execute(_insert_on_conflict_do_nothing(
                conn,
                artifacts,
                values,
                index_elements=("digest",),
            ))
            existing = conn.execute(select(
                artifacts.c.size_bytes,
                artifacts.c.storage_uri,
            ).where(artifacts.c.digest == digest)).mappings().one()
            if (
                existing["size_bytes"] != size_bytes
                or existing["storage_uri"] != storage_uri
            ):
                raise ImmutableVersionConflict(
                    f"artifact {digest} is already registered with different content location or size"
                )

    def reserve_execution_idempotency(
        self,
        conn: Connection,
        *,
        project_id: str,
        key: str,
        request_digest: str,
    ) -> Mapping[str, Any] | None:
        """Atomically claim an execution key or return its completed replay."""
        if conn.dialect.name == "postgresql":
            # SQLite's enclosing BEGIN IMMEDIATE already serializes writers.
            conn.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext(:project_id), hashtext(:key))"
                ),
                {"project_id": project_id, "key": key},
            )
        reservation_id = _id()
        inserted = conn.execute(_insert_on_conflict_do_nothing(
            conn,
            idempotency_records,
            {
                "id": reservation_id,
                "project_id": project_id,
                "key": key,
                "request_digest": request_digest,
                "response": {},
            },
            index_elements=("project_id", "key"),
        ).returning(idempotency_records.c.id))
        if inserted.scalar_one_or_none() == reservation_id:
            return None
        existing = conn.execute(select(
            idempotency_records.c.request_digest,
            idempotency_records.c.response,
        ).where(
            idempotency_records.c.project_id == project_id,
            idempotency_records.c.key == key,
        )).mappings().one()
        if existing["request_digest"] != request_digest:
            raise ValueError(
                "idempotency key was already used with a different request payload"
            )
        response = dict(existing["response"] or {})
        if not response:
            raise RuntimeError("idempotency reservation completed without a durable response")
        return response

    def complete_execution_idempotency(
        self,
        conn: Connection,
        *,
        project_id: str,
        key: str,
        request_digest: str,
        response: Mapping[str, Any],
    ) -> None:
        completed = conn.execute(update(idempotency_records).where(
            idempotency_records.c.project_id == project_id,
            idempotency_records.c.key == key,
            idempotency_records.c.request_digest == request_digest,
        ).values(response=dict(response)))
        if completed.rowcount != 1:
            raise RuntimeError("execution idempotency reservation was lost")

    def create_analysis_report(
        self, project_id: str, *, record: Mapping[str, Any]
    ) -> bool:
        """Persist an execution-bound report; only a byte-identical replay is safe."""
        values = dict(record)
        required = {
            "id",
            "project_id",
            "experiment_id",
            "execution_id",
            "spec_hash",
            "study_pack_hash",
            "configuration_digest",
            "input_digest",
            "report_digest",
            "artifact_digest",
        }
        if set(values) != required or values["project_id"] != project_id:
            raise ValueError("analysis record has invalid project-scoped fields")
        for field in (
            "spec_hash",
            "study_pack_hash",
            "configuration_digest",
            "input_digest",
            "report_digest",
            "artifact_digest",
        ):
            _require_digest(str(values[field]), field)
        with self.transaction(immediate=True) as conn:
            owned = conn.execute(
                select(executions.c.id)
                .join(experiments, executions.c.experiment_id == experiments.c.id)
                .where(
                    executions.c.id == values["execution_id"],
                    executions.c.experiment_id == values["experiment_id"],
                    experiments.c.project_id == project_id,
                )
            ).scalar_one_or_none()
            if owned is None:
                raise ValueError(
                    "analysis execution is not in the project and experiment"
                )
            registered = conn.execute(
                select(artifacts.c.digest).where(
                    artifacts.c.digest == values["artifact_digest"]
                )
            ).scalar_one_or_none()
            if registered is None:
                raise ValueError("analysis artifact must already be registered")
            existing = (
                conn.execute(
                    select(analysis_reports).where(
                        analysis_reports.c.execution_id == values["execution_id"]
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if all(existing[key] == value for key, value in values.items()):
                    return True
                raise ImmutableAnalysisConflict(
                    "execution already has a different immutable analysis report"
                )
            conn.execute(insert(analysis_reports).values(**values))
        return False

    def get_analysis_report(
        self, project_id: str, execution_id: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(analysis_reports).where(
                        analysis_reports.c.project_id == project_id,
                        analysis_reports.c.execution_id == execution_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def get_analysis_report_by_id(
        self, project_id: str, report_id: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(analysis_reports).where(
                        analysis_reports.c.project_id == project_id,
                        analysis_reports.c.id == report_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def create_decision_brief(
        self, project_id: str, *, record: Mapping[str, Any]
    ) -> bool:
        """Persist one report-bound brief; differing replays are conflicts."""
        values = dict(record)
        required = {
            "id", "project_id", "analysis_report_id", "experiment_id",
            "execution_id", "report_digest", "request_digest", "brief_hash",
            "ledger_hash", "brief_artifact_digest", "ledger_artifact_digest",
            "verdict", "claim_ceiling", "claim_refs",
        }
        if set(values) != required or values["project_id"] != project_id:
            raise ValueError("decision record has invalid project-scoped fields")
        for field in (
            "report_digest", "request_digest", "brief_hash", "ledger_hash",
            "brief_artifact_digest", "ledger_artifact_digest",
        ):
            _require_digest(str(values[field]), field)
        if values["verdict"] not in {"PASS", "HOLD", "REJECT"}:
            raise ValueError("decision record verdict is invalid")
        if not isinstance(values["claim_refs"], list):
            raise TypeError("decision record claim refs are invalid")
        with self.transaction(immediate=True) as conn:
            report = (
                conn.execute(
                    select(analysis_reports).where(
                        analysis_reports.c.id == values["analysis_report_id"],
                        analysis_reports.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
            if report is None or any(
                report[key] != values[key]
                for key in ("experiment_id", "execution_id", "report_digest")
            ):
                raise ValueError("decision report binding is invalid")
            registered = set(
                conn.execute(
                    select(artifacts.c.digest).where(
                        artifacts.c.digest.in_(
                            (values["brief_artifact_digest"], values["ledger_artifact_digest"])
                        )
                    )
                ).scalars()
            )
            if registered != {
                values["brief_artifact_digest"], values["ledger_artifact_digest"]
            }:
                raise ValueError("decision artifacts must already be registered")
            existing = (
                conn.execute(
                    select(decision_briefs).where(
                        decision_briefs.c.analysis_report_id == values["analysis_report_id"]
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if all(existing[key] == value for key, value in values.items()):
                    return True
                raise ImmutableDecisionConflict(
                    "analysis report already has different immutable decision content"
                )
            conn.execute(insert(decision_briefs).values(**values))
        return False

    def get_decision_brief(
        self, project_id: str, decision_id: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(decision_briefs).where(
                        decision_briefs.c.id == decision_id,
                        decision_briefs.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def analysis_execution_rows(
        self, project_id: str, experiment_id: str, execution_id: str
    ) -> tuple[Mapping[str, Any] | None, list[Mapping[str, Any]]]:
        """Return the immutable execution binding and all source rows in one scoped read."""
        with self.engine.connect() as conn:
            execution = (
                conn.execute(
                    select(
                        executions.c.id.label("execution_id"),
                        executions.c.status.label("execution_status"),
                        experiments.c.id.label("experiment_id"),
                        experiments.c.definition,
                        experiments.c.spec_hash,
                        experiments.c.study_pack_hash,
                        experiments.c.frozen_at,
                        experiments.c.owner_approval,
                        study_packs.c.content_digest.label("content_digest"),
                    )
                    .join(experiments, executions.c.experiment_id == experiments.c.id)
                    .join(
                        study_packs,
                        experiments.c.study_pack_id == study_packs.c.id,
                    )
                    .where(
                        executions.c.id == execution_id,
                        executions.c.experiment_id == experiment_id,
                        experiments.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
            if execution is None:
                return None, []
            rows = (
                conn.execute(
                    select(
                        attempts.c.id.label("attempt_id"),
                        attempts.c.episode_id.label("episode_id"),
                        attempts.c.ordinal.label("attempt_ordinal"),
                        attempts.c.status.label("attempt_status"),
                        attempts.c.request_metadata,
                        attempts.c.result_metadata,
                        episodes.c.scenario_id,
                        episodes.c.metadata_json.label("episode_metadata"),
                        episodes.c.ordinal.label("episode_ordinal"),
                        evaluations,
                    )
                    .select_from(
                        attempts.join(
                            episodes, attempts.c.episode_id == episodes.c.id
                        ).outerjoin(
                            evaluations,
                            evaluations.c.attempt_id == attempts.c.id,
                        )
                    )
                    .where(episodes.c.execution_id == execution_id)
                    .order_by(attempts.c.episode_id, attempts.c.ordinal, evaluations.c.id)
                )
                .mappings()
                .all()
            )
            usage = (
                conn.execute(
                    select(usage_ledger)
                    .where(usage_ledger.c.execution_id == execution_id)
                    .order_by(
                        usage_ledger.c.attempt_id,
                        usage_ledger.c.created_at,
                        usage_ledger.c.id,
                    )
                )
                .mappings()
                .all()
            )
        usage_by_attempt: dict[str, list[dict[str, Any]]] = {}
        for item in usage:
            if item["attempt_id"] is not None:
                usage_by_attempt.setdefault(str(item["attempt_id"]), []).append(
                    dict(item)
                )
        materialized = []
        for row in rows:
            item = dict(row)
            item["usage_rows"] = usage_by_attempt.get(str(item["attempt_id"]), [])
            materialized.append(item)
        return dict(execution), materialized

    def create_annotation_batch(
        self,
        project_id: str,
        *,
        batch: Mapping[str, Any],
        assignments: tuple[Mapping[str, Any], ...],
    ) -> bool:
        """Persist one immutable, project-scoped blind-review batch. Exact replays are safe."""
        batch_id = str(batch["id"])
        with self.transaction(immediate=True) as conn:
            if (
                conn.execute(
                    select(projects.c.id).where(projects.c.id == project_id)
                ).scalar_one_or_none()
                is None
            ):
                raise ValueError("project does not exist")
            existing = (
                conn.execute(
                    select(annotation_batches).where(
                        annotation_batches.c.id == batch_id
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                comparable = {key: existing[key] for key in batch}
                if comparable == dict(batch):
                    assignment_keys = tuple(assignments[0]) if assignments else ()
                    existing_assignments = [
                        {key: row[key] for key in assignment_keys}
                        for row in conn.execute(
                            select(annotation_assignments)
                            .where(annotation_assignments.c.batch_id == batch_id)
                            .order_by(annotation_assignments.c.id)
                        ).mappings()
                    ]
                    expected_assignments = sorted(
                        (dict(value) for value in assignments),
                        key=lambda value: str(value["id"]),
                    )
                    if existing_assignments == expected_assignments:
                        return True
                raise ImmutableReviewConflict(
                    "annotation batch id is already bound to different content"
                )
            existing_hash = conn.execute(
                select(annotation_batches.c.id).where(
                    annotation_batches.c.project_id == project_id,
                    annotation_batches.c.batch_hash == batch["batch_hash"],
                )
            ).scalar_one_or_none()
            if existing_hash is not None:
                raise ImmutableReviewConflict(
                    "annotation batch hash is already bound to another id"
                )
            conn.execute(insert(annotation_batches).values(**dict(batch)))
            conn.execute(
                insert(annotation_assignments), [dict(value) for value in assignments]
            )
        return False

    def get_annotation_batch(
        self, project_id: str, batch_id: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(annotation_batches).where(
                        annotation_batches.c.id == batch_id,
                        annotation_batches.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def review_assignments(
        self, project_id: str, batch_id: str
    ) -> list[Mapping[str, Any]]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(annotation_assignments)
                    .join(
                        annotation_batches,
                        annotation_assignments.c.batch_id == annotation_batches.c.id,
                    )
                    .where(
                        annotation_batches.c.project_id == project_id,
                        annotation_assignments.c.batch_id == batch_id,
                    )
                    .order_by(
                        annotation_assignments.c.item_id,
                        annotation_assignments.c.annotator_pseudonym,
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def review_annotations(
        self, project_id: str, batch_id: str
    ) -> list[Mapping[str, Any]]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(annotations)
                    .join(
                        annotation_batches,
                        annotations.c.batch_id == annotation_batches.c.id,
                    )
                    .where(
                        annotation_batches.c.project_id == project_id,
                        annotations.c.batch_id == batch_id,
                    )
                    .order_by(
                        annotations.c.item_id,
                        annotations.c.assignment_hash,
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def review_adjudications(
        self, project_id: str, batch_id: str
    ) -> list[Mapping[str, Any]]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(annotation_adjudications)
                    .join(
                        annotation_batches,
                        annotation_adjudications.c.batch_id == annotation_batches.c.id,
                    )
                    .where(
                        annotation_batches.c.project_id == project_id,
                        annotation_adjudications.c.batch_id == batch_id,
                    )
                    .order_by(
                        annotation_adjudications.c.item_id,
                    )
                )
                .mappings()
                .all()
            )
            dimensions = conn.execute(
                select(annotation_adjudication_dimensions)
                .join(
                    annotation_adjudications,
                    annotation_adjudication_dimensions.c.adjudication_id
                    == annotation_adjudications.c.id,
                )
                .join(
                    annotation_batches,
                    annotation_adjudications.c.batch_id == annotation_batches.c.id,
                )
                .where(
                    annotation_batches.c.project_id == project_id,
                    annotation_adjudications.c.batch_id == batch_id,
                )
                .order_by(
                    annotation_adjudication_dimensions.c.adjudication_id,
                    annotation_adjudication_dimensions.c.metric_id,
                )
            ).mappings().all()
        by_adjudication: dict[str, dict[str, float]] = {}
        for dimension in dimensions:
            by_adjudication.setdefault(str(dimension["adjudication_id"]), {})[
                str(dimension["metric_id"])
            ] = float(dimension["score"])
        return [
            {
                **dict(row),
                "dimension_scores": by_adjudication.get(str(row["id"]), {}),
                "final_score_semantics": "mean_summary_only",
            }
            for row in rows
        ]

    def review_assignment(
        self, project_id: str, batch_id: str, assignment_id: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(annotation_assignments)
                    .join(
                        annotation_batches,
                        annotation_assignments.c.batch_id == annotation_batches.c.id,
                    )
                    .where(
                        annotation_batches.c.project_id == project_id,
                        annotation_assignments.c.batch_id == batch_id,
                        annotation_assignments.c.id == assignment_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def submit_review_annotation(
        self,
        project_id: str,
        batch_id: str,
        assignment_id: str,
        record: Mapping[str, Any],
    ) -> bool:
        with self.transaction(immediate=True) as conn:
            assignment = (
                conn.execute(
                    select(annotation_assignments)
                    .join(
                        annotation_batches,
                        annotation_assignments.c.batch_id == annotation_batches.c.id,
                    )
                    .where(
                        annotation_batches.c.project_id == project_id,
                        annotation_assignments.c.batch_id == batch_id,
                        annotation_assignments.c.id == assignment_id,
                    )
                )
                .mappings()
                .first()
            )
            if assignment is None:
                raise ValueError("assignment is not in project batch")
            existing = (
                conn.execute(
                    select(annotations).where(
                        annotations.c.assignment_hash == assignment["assignment_hash"],
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                comparable = {key: existing[key] for key in record}
                if comparable == dict(record):
                    return True
                raise ImmutableReviewConflict(
                    "assignment already has a different immutable annotation"
                )
            conn.execute(insert(annotations).values(**dict(record)))
        return False

    def create_review_adjudication(
        self,
        project_id: str,
        batch_id: str,
        record: Mapping[str, Any],
        dimension_scores: Mapping[str, float],
    ) -> bool:
        with self.transaction(immediate=True) as conn:
            owned = conn.execute(
                select(annotation_batches.c.id).where(
                    annotation_batches.c.project_id == project_id,
                    annotation_batches.c.id == batch_id,
                )
            ).scalar_one_or_none()
            if owned is None:
                raise ValueError("batch is not in project")
            existing = (
                conn.execute(
                    select(annotation_adjudications).where(
                        annotation_adjudications.c.batch_id == batch_id,
                        annotation_adjudications.c.item_id == record["item_id"],
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                existing_dimensions = {
                    str(row["metric_id"]): float(row["score"])
                    for row in conn.execute(
                        select(annotation_adjudication_dimensions).where(
                            annotation_adjudication_dimensions.c.adjudication_id
                            == existing["id"]
                        )
                    ).mappings()
                }
                if (
                    all(existing[key] == value for key, value in record.items())
                    and existing_dimensions == dict(dimension_scores)
                ):
                    return True
                raise ImmutableReviewConflict(
                    "item already has a different immutable adjudication"
                )
            conn.execute(insert(annotation_adjudications).values(**dict(record)))
            conn.execute(
                insert(annotation_adjudication_dimensions),
                [
                    {
                        "adjudication_id": record["id"],
                        "metric_id": metric_id,
                        "score": score,
                    }
                    for metric_id, score in sorted(dimension_scores.items())
                ],
            )
        return False

    def attempt_evaluation_source(
        self, project_id: str, attempt_id: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(
                        attempts.c.id,
                        attempts.c.status,
                        attempts.c.result_metadata,
                        attempts.c.request_metadata,
                        episodes.c.execution_id,
                    )
                    .join(episodes, attempts.c.episode_id == episodes.c.id)
                    .join(
                        executions,
                        episodes.c.execution_id == executions.c.id,
                    )
                    .join(experiments, executions.c.experiment_id == experiments.c.id)
                    .where(
                        attempts.c.id == attempt_id,
                        experiments.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def review_attempt_evidence(
        self, project_id: str, attempt_id: str
    ) -> Mapping[str, Any] | None:
        """Return one project-owned attempt with its sole immutable evaluation row."""
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(
                        attempts.c.id.label("attempt_id"), attempts.c.result_metadata,
                        episodes.c.id.label("episode_id"),
                        evaluations.c.id.label("evaluation_id"), evaluations.c.evaluator,
                        evaluations.c.evaluator_version, evaluations.c.evaluator_digest,
                        evaluations.c.input_artifact_digest.label("evaluation_input_artifact_digest"),
                        evaluations.c.output_artifact_digest.label("evaluation_output_artifact_digest"),
                        evaluations.c.trace_artifact_digest.label("evaluation_trace_artifact_digest"),
                        evaluations.c.grader_plan, evaluations.c.result, evaluations.c.result_hash,
                        evaluations.c.result_artifact_digest,
                    )
                    .join(episodes, attempts.c.episode_id == episodes.c.id)
                    .join(executions, episodes.c.execution_id == executions.c.id)
                    .join(experiments, executions.c.experiment_id == experiments.c.id)
                    .outerjoin(evaluations, evaluations.c.attempt_id == attempts.c.id)
                    .where(attempts.c.id == attempt_id, experiments.c.project_id == project_id)
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def review_item_payload_matches(
        self, project_id: str, batch_id: str, item_id: str, digest: str
    ) -> bool:
        with self.engine.connect() as conn:
            matched = conn.execute(
                select(annotation_assignments.c.id)
                .join(annotation_batches, annotation_assignments.c.batch_id == annotation_batches.c.id)
                .where(
                    annotation_batches.c.project_id == project_id,
                    annotation_assignments.c.batch_id == batch_id,
                    annotation_assignments.c.item_id == item_id,
                    annotation_assignments.c.blind_payload_digest == digest,
                )
            ).scalars().first()
        return matched is not None

    def create_evaluation_record(
        self,
        project_id: str,
        *,
        record: Mapping[str, Any],
        lease_job_id: str | None = None,
        lease_owner: str | None = None,
        lease_token: str | None = None,
    ) -> bool:
        """Insert one immutable evaluator-owned row; exact replays are idempotent."""
        values = dict(record)
        if values.get("project_id") != project_id:
            raise ValueError("evaluation project binding is required")
        attempt_id = values.get("attempt_id")
        if not isinstance(attempt_id, str):
            raise TypeError("evaluation attempt binding is required")
        lease_values = (lease_job_id, lease_owner, lease_token)
        if any(value is not None for value in lease_values) and not all(lease_values):
            raise ValueError("evaluation lease fencing requires job, owner, and token")
        with self.transaction(immediate=True) as conn:
            if lease_job_id is not None:
                lease_query = select(jobs.c.id).where(
                    jobs.c.id == lease_job_id,
                    jobs.c.attempt_id == attempt_id,
                    jobs.c.kind == "evaluation",
                    jobs.c.status == "running",
                    jobs.c.lease_owner == lease_owner,
                    jobs.c.lease_token == lease_token,
                    jobs.c.lease_expires_at > datetime.now(UTC),
                )
                if conn.dialect.name == "postgresql":
                    lease_query = lease_query.with_for_update()
                if conn.execute(lease_query).scalar_one_or_none() is None:
                    raise ImmutableEvaluationConflict("evaluation lease is no longer current")
            owned = conn.execute(
                select(attempts.c.id)
                .join(episodes, attempts.c.episode_id == episodes.c.id)
                .join(executions, episodes.c.execution_id == executions.c.id)
                .join(experiments, executions.c.experiment_id == experiments.c.id)
                .where(attempts.c.id == attempt_id, experiments.c.project_id == project_id)
            ).scalar_one_or_none()
            if owned is None:
                raise ValueError("attempt is not in project")
            existing = conn.execute(
                select(evaluations).where(evaluations.c.attempt_id == attempt_id)
            ).mappings().first()
            if existing is not None:
                comparable = {key: existing[key] for key in values}
                if comparable == values:
                    return True
                raise ImmutableEvaluationConflict(
                    "attempt already has a different immutable evaluation"
                )
            conn.execute(insert(evaluations).values(**values))
        return False

    def reconciled_attempt_cost(self, attempt_id: str) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(usage_ledger)
                    .where(
                        usage_ledger.c.attempt_id == attempt_id,
                        usage_ledger.c.cost_status == "reconciled",
                    )
                    .order_by(
                        usage_ledger.c.created_at.desc(), usage_ledger.c.id.desc()
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def create_evidence_receipt(
        self,
        project_id: str,
        *,
        receipt_id: str,
        receipt_hash: str,
        manifest_hash: str,
        manifest_json: Mapping[str, Any],
        artifact_hashes: tuple[str, ...],
        evidence_type: str,
        claim_ceiling: str,
        execution_id: str | None = None,
    ) -> bool:
        """Persist an immutable receipt. Exact replays return True; conflicts fail closed."""
        _require_digest(receipt_hash, "receipt_hash")
        _require_digest(manifest_hash, "manifest_hash")
        if not artifact_hashes:
            raise ValueError("evidence receipt requires at least one artifact")
        for digest in artifact_hashes:
            _require_digest(digest, "artifact digest")
        values = {
            "id": receipt_id,
            "project_id": project_id,
            "execution_id": execution_id,
            "artifact_digest": artifact_hashes[0],
            "receipt_kind": evidence_type,
            "claims": [],
            "receipt_hash": receipt_hash,
            "manifest_hash": manifest_hash,
            "manifest_json": dict(manifest_json),
            "artifact_hashes": list(artifact_hashes),
            "claim_ceiling": claim_ceiling,
            "integrity_not_truth": True,
        }
        with self.transaction(immediate=True) as conn:
            if (
                conn.execute(
                    select(projects.c.id).where(projects.c.id == project_id)
                ).scalar_one_or_none()
                is None
            ):
                raise ValueError("project does not exist")
            if execution_id is not None:
                owned = conn.execute(
                    select(executions.c.id)
                    .join(experiments, executions.c.experiment_id == experiments.c.id)
                    .where(
                        executions.c.id == execution_id,
                        experiments.c.project_id == project_id,
                    )
                ).scalar_one_or_none()
                if owned is None:
                    raise ValueError("execution is not in project")
            registered = set(
                conn.execute(
                    select(artifacts.c.digest).where(
                        artifacts.c.digest.in_(artifact_hashes)
                    )
                ).scalars()
            )
            if registered != set(artifact_hashes):
                raise ValueError("all receipt artifacts must be registered")
            existing = (
                conn.execute(
                    select(evidence_receipts).where(
                        evidence_receipts.c.id == receipt_id
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                comparable = {key: existing[key] for key in values}
                if comparable == values:
                    existing_artifacts = tuple(
                        conn.execute(
                            select(evidence_receipt_artifacts.c.artifact_digest)
                            .where(
                                evidence_receipt_artifacts.c.receipt_id == receipt_id,
                            )
                            .order_by(evidence_receipt_artifacts.c.artifact_digest)
                        ).scalars()
                    )
                    if existing_artifacts == tuple(sorted(artifact_hashes)):
                        return True
                raise ImmutableReceiptConflict(
                    "evidence receipt id is already bound to different metadata"
                )
            existing_hash = conn.execute(
                select(evidence_receipts.c.id).where(
                    evidence_receipts.c.receipt_hash == receipt_hash
                )
            ).scalar_one_or_none()
            if existing_hash is not None:
                raise ImmutableReceiptConflict(
                    "evidence receipt hash is already bound to another receipt id"
                )
            conn.execute(insert(evidence_receipts).values(**values))
            conn.execute(
                insert(evidence_receipt_artifacts),
                [
                    {"receipt_id": receipt_id, "artifact_digest": digest}
                    for digest in sorted(artifact_hashes)
                ],
            )
        return False

    def get_evidence_receipt(
        self, project_id: str, receipt_id: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(evidence_receipts).where(
                        evidence_receipts.c.id == receipt_id,
                        evidence_receipts.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def get_execution_evidence_binding(
        self,
        project_id: str,
        execution_id: str,
    ) -> Mapping[str, Any] | None:
        """Return only the persisted frozen bindings required for receipt admission."""
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(
                        executions.c.id.label("execution_id"),
                        executions.c.status.label("execution_status"),
                        experiments.c.id.label("experiment_id"),
                        experiments.c.frozen_at,
                        experiments.c.spec_hash,
                        experiments.c.study_pack_hash,
                        experiments.c.definition,
                    )
                    .join(experiments, executions.c.experiment_id == experiments.c.id)
                    .where(
                        executions.c.id == execution_id,
                        experiments.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def derived_execution_evidence_source(
        self, project_id: str, execution_id: str,
    ) -> tuple[Mapping[str, Any] | None, list[Mapping[str, Any]], list[Mapping[str, Any]]]:
        """Return one project-scoped frozen execution and its persisted receipt inputs."""
        with self.engine.connect() as conn:
            execution = (
                conn.execute(
                    select(
                        executions.c.id.label("execution_id"),
                        executions.c.status.label("execution_status"),
                        experiments.c.id.label("experiment_id"),
                        experiments.c.definition,
                        experiments.c.spec_hash,
                        experiments.c.study_pack_hash,
                        experiments.c.frozen_at,
                    )
                    .join(experiments, executions.c.experiment_id == experiments.c.id)
                    .where(
                        executions.c.id == execution_id,
                        experiments.c.project_id == project_id,
                    )
                )
                .mappings()
                .first()
            )
            if execution is None:
                return None, [], []
            attempt_rows = (
                conn.execute(
                    select(
                        attempts.c.id.label("attempt_id"),
                        attempts.c.ordinal.label("attempt_ordinal"),
                        attempts.c.status.label("attempt_status"),
                        attempts.c.request_metadata,
                        attempts.c.result_metadata,
                        episodes.c.scenario_id,
                        episodes.c.metadata_json.label("episode_metadata"),
                    )
                    .join(episodes, attempts.c.episode_id == episodes.c.id)
                    .where(episodes.c.execution_id == execution_id)
                    .order_by(attempts.c.id)
                )
                .mappings()
                .all()
            )
            job_rows = (
                conn.execute(
                    select(jobs)
                    .where(jobs.c.execution_id == execution_id)
                    .order_by(jobs.c.attempt_id, jobs.c.id)
                )
                .mappings()
                .all()
            )
            evaluation_rows = (
                conn.execute(
                    select(evaluations)
                    .join(attempts, evaluations.c.attempt_id == attempts.c.id)
                    .join(episodes, attempts.c.episode_id == episodes.c.id)
                    .where(episodes.c.execution_id == execution_id)
                    .order_by(evaluations.c.attempt_id, evaluations.c.id)
                )
                .mappings()
                .all()
            )
            usage_rows = (
                conn.execute(
                    select(usage_ledger)
                    .where(usage_ledger.c.execution_id == execution_id)
                    .order_by(usage_ledger.c.attempt_id, usage_ledger.c.created_at, usage_ledger.c.id)
                )
                .mappings()
                .all()
            )
            price_rows = conn.execute(select(price_catalog).order_by(price_catalog.c.id)).mappings().all()

        jobs_by_attempt: dict[str, list[dict[str, Any]]] = {}
        for row in job_rows:
            if row["attempt_id"] is not None:
                jobs_by_attempt.setdefault(str(row["attempt_id"]), []).append(dict(row))
        evaluations_by_attempt: dict[str, list[dict[str, Any]]] = {}
        for row in evaluation_rows:
            evaluations_by_attempt.setdefault(str(row["attempt_id"]), []).append(dict(row))
        usage_by_attempt: dict[str, list[dict[str, Any]]] = {}
        for row in usage_rows:
            if row["attempt_id"] is not None:
                usage_by_attempt.setdefault(str(row["attempt_id"]), []).append(dict(row))
        materialized: list[Mapping[str, Any]] = []
        for row in attempt_rows:
            item = dict(row)
            attempt_id = str(item["attempt_id"])
            item["jobs"] = jobs_by_attempt.get(attempt_id, [])
            item["evaluations"] = evaluations_by_attempt.get(attempt_id, [])
            item["usage_rows"] = usage_by_attempt.get(attempt_id, [])
            materialized.append(item)
        return dict(execution), materialized, [dict(row) for row in price_rows]

    def evidence_artifacts(
        self, project_id: str, receipt_id: str
    ) -> dict[str, Mapping[str, Any]]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(artifacts)
                    .join(
                        evidence_receipt_artifacts,
                        artifacts.c.digest
                        == evidence_receipt_artifacts.c.artifact_digest,
                    )
                    .join(
                        evidence_receipts,
                        evidence_receipt_artifacts.c.receipt_id
                        == evidence_receipts.c.id,
                    )
                    .where(
                        evidence_receipts.c.id == receipt_id,
                        evidence_receipts.c.project_id == project_id,
                    )
                )
                .mappings()
                .all()
            )
        return {str(row["digest"]): dict(row) for row in rows}

    def create_reproduction(
        self,
        project_id: str,
        *,
        reproduction_id: str,
        reproduction_hash: str,
        original_receipt_id: str,
        reproduced_receipt_id: str,
        receipt_json: Mapping[str, Any],
        external_attestation: Mapping[str, Any] | None,
        claim_ceiling: str,
    ) -> bool:
        _require_digest(reproduction_hash, "reproduction_hash")
        values = {
            "id": reproduction_id,
            "project_id": project_id,
            "source_execution_id": None,
            "reproduction_execution_id": None,
            "status": "recorded_non_independent",
            "result": {},
            "original_evidence_receipt_id": original_receipt_id,
            "reproduced_evidence_receipt_id": reproduced_receipt_id,
            "reproduction_hash": reproduction_hash,
            "receipt_json": dict(receipt_json),
            "external_attestation": dict(external_attestation)
            if external_attestation
            else None,
            "claim_ceiling": claim_ceiling,
            "integrity_not_truth": True,
        }
        with self.transaction(immediate=True) as conn:
            owned = set(
                conn.execute(
                    select(evidence_receipts.c.id).where(
                        evidence_receipts.c.project_id == project_id,
                        evidence_receipts.c.id.in_(
                            (original_receipt_id, reproduced_receipt_id)
                        ),
                    )
                ).scalars()
            )
            if owned != {original_receipt_id, reproduced_receipt_id}:
                raise ValueError(
                    "reproduction evidence receipts are not available in project"
                )
            existing = (
                conn.execute(
                    select(reproductions).where(reproductions.c.id == reproduction_id)
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if all(existing[key] == value for key, value in values.items()):
                    return True
                raise ImmutableReceiptConflict(
                    "reproduction receipt id is already bound to different metadata"
                )
            existing_hash = conn.execute(
                select(reproductions.c.id).where(
                    reproductions.c.reproduction_hash == reproduction_hash
                )
            ).scalar_one_or_none()
            if existing_hash is not None:
                raise ImmutableReceiptConflict(
                    "reproduction hash is already bound to another receipt id"
                )
            conn.execute(insert(reproductions).values(**values))
        return False

    def create_study_pack_version(
        self,
        project_id: str,
        pack_key: str,
        version: str,
        content_digest: str,
        *,
        content_metadata: Mapping[str, Any] | None = None,
        study_pack_id: str | None = None,
    ) -> str:
        if not _SEMVER.fullmatch(version):
            raise ValueError(
                "study pack version must be a semantic version (for example, 1.0.0)"
            )
        study_pack_id = study_pack_id or _id()
        values = {
            "id": study_pack_id,
            "project_id": project_id,
            "pack_key": pack_key,
            "version": version,
            "content_digest": content_digest,
            "content_metadata": dict(content_metadata or {}),
        }
        try:
            with self.transaction() as conn:
                conn.execute(insert(study_packs).values(**values))
        except IntegrityError as exc:
            with self.engine.connect() as conn:
                existing = conn.execute(
                    select(study_packs.c.id).where(
                        study_packs.c.project_id == project_id,
                        study_packs.c.pack_key == pack_key,
                        study_packs.c.version == version,
                    )
                ).scalar_one_or_none()
            if existing is not None:
                raise ImmutableVersionConflict(
                    f"study pack {pack_key}@{version} already exists and is immutable"
                ) from exc
            raise
        return study_pack_id

    def get_study_pack_version(
        self, project_id: str, pack_key: str, version: str
    ) -> Mapping[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(study_packs).where(
                        study_packs.c.project_id == project_id,
                        study_packs.c.pack_key == pack_key,
                        study_packs.c.version == version,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def create_experiment(
        self,
        project_id: str,
        study_pack_id: str,
        name: str,
        *,
        protocol_version: str = "1.0",
        predecessor_id: str | None = None,
        owner_approval: str = "pending",
        definition: Mapping[str, Any] | None = None,
        experiment_id: str | None = None,
    ) -> str:
        if not protocol_version:
            raise ValueError("protocol_version is required")
        if owner_approval not in {"pending", "approved", "rejected"}:
            raise ValueError("owner_approval must be pending, approved, or rejected")
        experiment_id = experiment_id or _id()
        if predecessor_id == experiment_id:
            raise ValueError("an experiment cannot be its own predecessor")
        with self.transaction() as conn:
            pack_project_id = conn.execute(
                select(study_packs.c.project_id).where(
                    study_packs.c.id == study_pack_id
                )
            ).scalar_one_or_none()
            if pack_project_id != project_id:
                raise ValueError(
                    "study pack must exist and belong to the experiment project"
                )
            if predecessor_id is not None:
                predecessor_project_id = conn.execute(
                    select(experiments.c.project_id).where(
                        experiments.c.id == predecessor_id
                    )
                ).scalar_one_or_none()
                if predecessor_project_id != project_id:
                    raise ValueError(
                        "predecessor experiment must exist and belong to the experiment project"
                    )
            conn.execute(
                insert(experiments).values(
                    id=experiment_id,
                    project_id=project_id,
                    study_pack_id=study_pack_id,
                    name=name,
                    protocol_version=protocol_version,
                    predecessor_id=predecessor_id,
                    owner_approval=owner_approval,
                    definition=dict(definition or {}),
                )
            )
        return experiment_id

    def set_experiment_owner_approval(
        self, experiment_id: str, owner_approval: str
    ) -> None:
        if owner_approval not in {"pending", "approved", "rejected"}:
            raise ValueError("owner_approval must be pending, approved, or rejected")
        with self.transaction() as conn:
            result = conn.execute(
                update(experiments)
                .where(
                    experiments.c.id == experiment_id, experiments.c.frozen_at.is_(None)
                )
                .values(owner_approval=owner_approval)
            )
            if result.rowcount != 1:
                raise FrozenExperimentError(
                    f"experiment {experiment_id} is frozen or missing"
                )

    def update_experiment_definition(
        self, experiment_id: str, definition: Mapping[str, Any]
    ) -> None:
        with self.transaction() as conn:
            row = conn.execute(
                select(experiments.c.frozen_at).where(experiments.c.id == experiment_id)
            ).first()
            if row is None:
                raise KeyError(experiment_id)
            if row.frozen_at is not None:
                raise FrozenExperimentError(f"experiment {experiment_id} is frozen")
            conn.execute(
                update(experiments)
                .where(experiments.c.id == experiment_id)
                .values(definition=dict(definition))
            )

    def freeze_experiment(
        self,
        experiment_id: str,
        *,
        expected_definition: Mapping[str, Any],
        frozen_definition: Mapping[str, Any],
        spec_hash: str,
        study_pack_hash: str,
    ) -> None:
        _require_digest(spec_hash, "spec_hash")
        _require_digest(study_pack_hash, "study_pack_hash")
        expected = dict(expected_definition)
        definition = dict(frozen_definition)
        if definition.get("frozen") is not True:
            raise FrozenExperimentError("frozen_definition must have frozen=True")
        if definition.get("freeze_hash") != spec_hash:
            raise FrozenExperimentError(
                "frozen_definition freeze_hash must match spec_hash"
            )
        if definition.get("study_pack_hash") != study_pack_hash:
            raise FrozenExperimentError(
                "frozen_definition study_pack_hash must match study_pack_hash"
            )
        if definition.get("experiment_id") != experiment_id:
            raise FrozenExperimentError(
                "frozen_definition experiment_id must match experiment_id"
            )
        if definition.get("owner_approval") != "approved":
            raise FrozenExperimentError(
                "frozen_definition requires owner_approval='approved'"
            )
        frozen_at = _frozen_timestamp(definition)
        with self.transaction(immediate=True) as conn:
            statement = select(
                experiments.c.id,
                experiments.c.definition,
                experiments.c.spec_hash,
                experiments.c.study_pack_hash,
                experiments.c.frozen_at,
                experiments.c.owner_approval,
            ).where(experiments.c.id == experiment_id)
            if self.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            existing = conn.execute(statement).mappings().first()
            if existing is None:
                raise FrozenExperimentError(f"experiment {experiment_id} is missing")
            pack_digest = conn.execute(
                select(study_packs.c.content_digest)
                .join(experiments, experiments.c.study_pack_id == study_packs.c.id)
                .where(experiments.c.id == experiment_id)
            ).scalar_one_or_none()
            if pack_digest != study_pack_hash:
                raise FrozenExperimentError(
                    "study_pack_hash must match the referenced study pack content digest"
                )
            if existing["frozen_at"] is not None:
                if (
                    existing["definition"] == definition
                    and existing["spec_hash"] == spec_hash
                    and existing["study_pack_hash"] == study_pack_hash
                    and existing["owner_approval"] == "approved"
                ):
                    return
                raise FrozenExperimentError(
                    f"experiment {experiment_id} is already frozen with a different definition or hashes"
                )
            if existing["definition"] != expected:
                raise FrozenExperimentError(
                    "experiment definition changed before freeze"
                )
            result = conn.execute(
                update(experiments)
                .where(
                    experiments.c.id == experiment_id,
                    experiments.c.frozen_at.is_(None),
                    experiments.c.owner_approval == "approved",
                    experiments.c.spec_hash.is_(None),
                    experiments.c.study_pack_hash.is_(None),
                )
                .values(
                    definition=definition,
                    spec_hash=spec_hash,
                    study_pack_hash=study_pack_hash,
                    frozen_at=frozen_at,
                )
            )
            if result.rowcount != 1:
                raise FrozenExperimentError(
                    f"experiment {experiment_id} requires approved owner approval and unbound hashes"
                )

    def create_execution(
        self,
        experiment_id: str,
        *,
        execution_id: str | None = None,
        status: str = "queued",
        parameters: Mapping[str, Any] | None = None,
    ) -> str:
        execution_id = execution_id or _id()
        with self.transaction() as conn:
            frozen = conn.execute(
                select(experiments.c.frozen_at, experiments.c.spec_hash).where(
                    experiments.c.id == experiment_id
                )
            ).first()
            if frozen is None or frozen.frozen_at is None or frozen.spec_hash is None:
                raise FrozenExperimentError(
                    "execution requires a frozen experiment with a bound spec_hash"
                )
            conn.execute(
                insert(executions).values(
                    id=execution_id,
                    experiment_id=experiment_id,
                    status=status,
                    parameters=dict(parameters or {}),
                )
            )
        return execution_id

    def create_episode(
        self,
        execution_id: str,
        ordinal: int,
        *,
        episode_id: str | None = None,
        scenario_id: str | None = None,
    ) -> str:
        episode_id = episode_id or _id()
        with self.transaction() as conn:
            conn.execute(
                insert(episodes).values(
                    id=episode_id,
                    execution_id=execution_id,
                    ordinal=ordinal,
                    scenario_id=scenario_id,
                )
            )
        return episode_id

    def create_attempt(
        self, episode_id: str, ordinal: int, *, attempt_id: str | None = None
    ) -> str:
        attempt_id = attempt_id or _id()
        with self.transaction() as conn:
            conn.execute(
                insert(attempts).values(
                    id=attempt_id, episode_id=episode_id, ordinal=ordinal
                )
            )
        return attempt_id

    def append_attempt_event(
        self,
        attempt_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        event_id: str | None = None,
    ) -> int:
        with self.transaction(immediate=True) as conn:
            sequence = append_attempt_event_in_transaction(
                conn, attempt_id, event_type, payload, event_id=event_id
            )
        return sequence

    def list_attempt_events(self, attempt_id: str) -> list[Mapping[str, Any]]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(attempt_events)
                    .where(attempt_events.c.attempt_id == attempt_id)
                    .order_by(attempt_events.c.sequence)
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def list_execution_events_after(
        self, execution_id: str, cursor: int
    ) -> list[Mapping[str, Any]]:
        events, _ = self.list_execution_events_with_status_after(execution_id, cursor)
        return events

    def list_execution_events_with_status_after(
        self,
        execution_id: str,
        cursor: int,
    ) -> tuple[list[Mapping[str, Any]], str | None]:
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError("cursor must be a nonnegative integer")
        with self.engine.connect() as conn:
            invalid_event = exists(
                select(1)
                .select_from(
                    attempt_events.join(
                        attempts, attempt_events.c.attempt_id == attempts.c.id
                    ).join(
                        episodes,
                        attempts.c.episode_id == episodes.c.id,
                    )
                )
                .where(
                    or_(
                        attempt_events.c.execution_id == execution_id,
                        episodes.c.execution_id == execution_id,
                    ),
                    episodes.c.execution_id != attempt_events.c.execution_id,
                )
            )
            rows = (
                conn.execute(
                    select(
                        attempt_events,
                        executions.c.status.label("execution_status"),
                        invalid_event.label("invalid_event"),
                    )
                    .select_from(
                        executions.outerjoin(
                            attempt_events,
                            and_(
                                attempt_events.c.execution_id == executions.c.id,
                                attempt_events.c.execution_sequence > cursor,
                            ),
                        )
                    )
                    .where(executions.c.id == execution_id)
                    .order_by(attempt_events.c.execution_sequence)
                )
                .mappings()
                .all()
            )
        if not rows:
            return [], None
        if bool(rows[0]["invalid_event"]):
            raise ValueError("execution event integrity mismatch")
        columns = tuple(attempt_events.c.keys())
        events = [
            {column: row[column] for column in columns}
            for row in rows
            if row["id"] is not None
        ]
        return events, str(rows[0]["execution_status"])

    def record_legacy_import(
        self,
        project_id: str,
        artifact_digest: str,
        *,
        source_format: str,
        observed_fields: list[str],
    ) -> str:
        event_id = _id()
        payload = {
            "classification": "legacy_local_unverified",
            "artifact_digest": artifact_digest,
            "source_format": source_format,
            "observed_fields": sorted(observed_fields),
            "evidence_claims": [],
        }
        with self.transaction() as conn:
            conn.execute(
                insert(audit_events).values(
                    id=event_id,
                    project_id=project_id,
                    event_type="legacy_imported",
                    payload=payload,
                )
            )
        return event_id
