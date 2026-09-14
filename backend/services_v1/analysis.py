"""Fail-closed durable admission for Analysis v1.

The public boundary supplies identifiers and a frozen configuration only.  It
never accepts an outcome, trace, evaluation, cost, or usage value from a
caller: those values are re-read from the execution's durable records.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from adapters_v1 import ProviderUsage
from analysis_v1 import (
    AnalysisInput,
    AnalysisReport,
    AttemptRecord,
    CostStatus,
    build_analysis_report,
)
from artifacts_v1 import ArtifactIntegrityError, ArtifactStore
from persistence_v1 import ArenaRepository, ImmutableAnalysisConflict
from persistence_v1.schema import (
    analysis_reports,
    artifacts,
    executions,
    experiments,
    study_packs,
)
from protocol_v1 import AttemptEnvelope, EvaluationRecord, ExperimentSpec
from protocol_v1.canonical import canonical_json, sha256_bytes
from protocol_v1.canonical import sha256 as canonical_hash


class AnalysisError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_CONFIG_KEYS = frozenset(
    {
        "registered_factors",
        "primary_main_effects",
        "secondary_interactions",
        "gates",
        "options",
    }
)
_EXTENSION = "org.scaffold-arena.analysis-v1"
_TERMINAL_ANALYSABLE = "completed"
_TERMINAL_ATTEMPT_STATUSES = frozenset(
    {"completed", "failed", "timed_out", "cancelled", "incomplete"}
)
_IMMUTABLE_ENVELOPE_FIELDS = (
    "attempt_id",
    "episode_id",
    "ordinal",
    "provider_model",
    "provider",
    "endpoint_id",
    "pinned_endpoint_digest",
    "harness_id",
    "factor_assignments",
    "budget",
    "provenance",
    "request_hash",
    "queued_at",
)


class AnalysisService:
    """Build and store one immutable report for a frozen completed execution."""

    def __init__(
        self,
        repository: ArenaRepository,
        artifact_store: ArtifactStore,
        *,
        personal_project_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def resolve_project(self, project_id: str | None) -> str:
        resolved = project_id or self.personal_project_id
        if not resolved:
            raise AnalysisError(
                "project_context_required", "An explicit project context is required."
            )
        with self.repository.engine.connect() as conn:
            known = conn.execute(
                select(artifacts.c.digest).select_from(artifacts).limit(1)
            ).first()  # force an initialized durable store
            del known
            from persistence_v1.schema import projects

            exists = conn.execute(
                select(projects.c.id).where(projects.c.id == resolved)
            ).scalar_one_or_none()
        if exists is None:
            raise AnalysisError(
                "unknown_project",
                "The supplied project does not exist.",
                status_code=404,
            )
        return resolved

    def analyze(
        self, payload: Mapping[str, Any], *, project_id: str | None
    ) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        experiment_id, execution_id, configuration = self._request(payload)
        execution, source_rows = self.repository.analysis_execution_rows(
            project_id, experiment_id, execution_id
        )
        if execution is None:
            raise AnalysisError(
                "execution_not_found",
                "The execution was not found in this project and experiment.",
                status_code=404,
            )
        frozen_configuration = self._frozen_configuration(execution, experiment_id)
        if canonical_json(configuration) != canonical_json(frozen_configuration):
            raise AnalysisError(
                "analysis_configuration_mismatch",
                "Analysis configuration must exactly match the preregistered frozen configuration.",
                status_code=409,
            )
        if execution["execution_status"] != _TERMINAL_ANALYSABLE:
            raise AnalysisError(
                "execution_incomplete",
                "Analysis requires a completed immutable execution.",
                status_code=409,
            )
        try:
            attempts = self._attempts(experiment_id, source_rows)
            analysis_input = AnalysisInput.model_validate_json(
                canonical_json(
                    {
                        "experiment_id": experiment_id,
                        "attempts": attempts,
                        **configuration,
                    }
                )
            )
            report = build_analysis_report(analysis_input)
        except AnalysisError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise AnalysisError(
                "analysis_hold",
                "Persisted evidence is incomplete, ambiguous, or incompatible with the preregistered analysis.",
                status_code=409,
            ) from exc

        report_bytes = canonical_json(report.model_dump(mode="json"))
        report_digest = sha256_bytes(report_bytes)
        artifact_digest = self.artifact_store.put_bytes(
            report_bytes, media_type="application/json"
        )
        if artifact_digest != report_digest:
            raise AnalysisError(
                "artifact_integrity_error",
                "The report artifact digest does not match its canonical bytes.",
                status_code=409,
            )
        self.repository.register_artifact(
            artifact_digest,
            size_bytes=len(report_bytes),
            storage_uri=self.artifact_store.uri_for(artifact_digest),
            media_type="application/json",
            content_metadata={
                "format": "analysis-report-v1",
                "report_digest": report_digest,
            },
        )
        configuration_digest = canonical_hash(configuration)
        input_digest = canonical_hash(analysis_input.model_dump(mode="json"))
        record = {
            "id": sha256(
                f"{project_id}:{experiment_id}:{execution_id}".encode()
            ).hexdigest(),
            "project_id": project_id,
            "experiment_id": experiment_id,
            "execution_id": execution_id,
            "spec_hash": str(execution["spec_hash"]),
            "study_pack_hash": str(execution["study_pack_hash"]),
            "configuration_digest": configuration_digest,
            "input_digest": input_digest,
            "report_digest": report_digest,
            "artifact_digest": artifact_digest,
        }
        try:
            replay = self.repository.create_analysis_report(project_id, record=record)
        except ImmutableAnalysisConflict as exc:
            raise AnalysisError(
                "analysis_conflict",
                "This execution is already bound to different analysis content.",
                status_code=409,
            ) from exc
        except ValueError as exc:
            raise AnalysisError(
                "analysis_binding_invalid",
                "The analysis report cannot be bound to this execution.",
                status_code=409,
            ) from exc
        return {
            "verdict": "PASS"
            if report.adequacy.claim_level != "DESCRIPTIVE_ONLY"
            else "HOLD",
            "execution_id": execution_id,
            "experiment_id": experiment_id,
            "report_digest": report_digest,
            "artifact_digest": artifact_digest,
            "artifact_ref": f"sha256:{artifact_digest}",
            "adequacy": report.adequacy.model_dump(mode="json"),
            "claim_ceiling": report.adequacy.claim_level,
            "idempotent_replay": replay,
            "integrity_not_truth": True,
        }

    def list_reports(
        self,
        *,
        project_id: str | None,
        experiment_id: str | None = None,
        execution_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return verified, redacted immutable report summaries only."""
        project_id = self.resolve_project(project_id)
        limit, offset = self._page(limit, offset)
        statement = select(analysis_reports).where(
            analysis_reports.c.project_id == project_id
        )
        if experiment_id is not None:
            statement = statement.where(analysis_reports.c.experiment_id == experiment_id)
        if execution_id is not None:
            statement = statement.where(analysis_reports.c.execution_id == execution_id)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(
                statement.order_by(
                    analysis_reports.c.created_at, analysis_reports.c.id
                )
                .offset(offset)
                .limit(limit + 1)
            ).mappings().all()
        page = rows[:limit]
        summaries = [self._summary(self._verified_report(project_id, row)) for row in page]
        return {
            "analysis_reports": summaries,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": offset + limit if len(rows) > limit else None,
            },
            "integrity_not_truth": True,
            "claim_ceiling": "report-specific; inspect a verified report for its adequacy ceiling",
        }

    def report(self, report_digest: str, *, project_id: str | None) -> dict[str, Any]:
        """Return one canonical report after re-verifying artifact and bindings."""
        project_id = self.resolve_project(project_id)
        with self.repository.engine.connect() as conn:
            row = conn.execute(
                select(analysis_reports).where(
                    analysis_reports.c.project_id == project_id,
                    analysis_reports.c.report_digest == report_digest,
                ).order_by(analysis_reports.c.created_at, analysis_reports.c.id)
            ).mappings().first()
        if row is None:
            raise AnalysisError(
                "analysis_report_not_found",
                "The immutable analysis report was not found in this project.",
                status_code=404,
            )
        verified = self._verified_report(project_id, row)
        report = verified["report"]
        binding = verified["binding"]
        return {
            "report": report.model_dump(mode="json"),
            "binding": binding,
            "report_digest": binding["report_digest"],
            "artifact_digest": binding["artifact_digest"],
            "artifact_ref": f"sha256:{binding['artifact_digest']}",
            "source_digests": {
                "spec_hash": binding["spec_hash"],
                "study_pack_hash": binding["study_pack_hash"],
                "configuration_digest": binding["configuration_digest"],
                "input_digest": binding["input_digest"],
            },
            "adequacy": report.adequacy.model_dump(mode="json"),
            "claim_ceiling": report.adequacy.claim_level,
            "integrity_not_truth": True,
        }

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise AnalysisError("invalid_limit", "The list limit must be an integer from 1 to 100.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise AnalysisError("invalid_offset", "The list offset must be a nonnegative integer.")
        return limit, offset

    def _verified_report(
        self, project_id: str, row: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Fail closed unless bytes, canonical report, and durable bindings agree."""
        binding = {
            key: str(row[key])
            for key in (
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
            )
        }
        try:
            with self.repository.engine.connect() as conn:
                source = conn.execute(
                    select(
                        executions.c.id.label("execution_id"),
                        experiments.c.id.label("experiment_id"),
                        experiments.c.project_id,
                        experiments.c.spec_hash,
                        experiments.c.study_pack_hash,
                        study_packs.c.content_digest,
                        artifacts.c.size_bytes,
                        artifacts.c.media_type,
                        artifacts.c.metadata_json,
                    )
                    .join(experiments, executions.c.experiment_id == experiments.c.id)
                    .join(study_packs, experiments.c.study_pack_id == study_packs.c.id)
                    .join(artifacts, artifacts.c.digest == binding["artifact_digest"])
                    .where(
                        executions.c.id == binding["execution_id"],
                        experiments.c.project_id == project_id,
                    )
                ).mappings().first()
            if source is None:
                raise ValueError("missing durable source binding")
            metadata = source["metadata_json"]
            if (
                source["execution_id"] != binding["execution_id"]
                or source["experiment_id"] != binding["experiment_id"]
                or source["project_id"] != project_id
                or source["spec_hash"] != binding["spec_hash"]
                or source["study_pack_hash"] != binding["study_pack_hash"]
                or source["content_digest"] != binding["study_pack_hash"]
                or not isinstance(metadata, Mapping)
                or metadata.get("format") != "analysis-report-v1"
                or metadata.get("report_digest") != binding["report_digest"]
                or source["media_type"] != "application/json"
            ):
                raise ValueError("mismatched durable analysis binding")
            content = self.artifact_store.get_bytes(binding["artifact_digest"])
            report = AnalysisReport.model_validate_json(content)
            if (
                len(content) != source["size_bytes"]
                or sha256_bytes(content) != binding["artifact_digest"]
                or sha256_bytes(content) != binding["report_digest"]
                or canonical_json(report.model_dump(mode="json")) != content
                or canonical_hash(
                    report.model_dump(mode="json", exclude={"canonical_hash"})
                )
                != report.canonical_hash
                or report.experiment_id != binding["experiment_id"]
            ):
                raise ValueError("analysis report bytes or canonical hash mismatch")
        except (
            ArtifactIntegrityError,
            FileNotFoundError,
            OSError,
            ValidationError,
            ValueError,
        ) as exc:
            raise AnalysisError(
                "analysis_report_integrity_error",
                "The stored analysis report artifact or its durable bindings cannot be verified.",
                status_code=409,
            ) from exc
        return {"report": report, "binding": binding, "created_at": row["created_at"]}

    @staticmethod
    def _summary(verified: Mapping[str, Any]) -> dict[str, Any]:
        report = verified["report"]
        binding = verified["binding"]
        return {
            "report_digest": binding["report_digest"],
            "artifact_digest": binding["artifact_digest"],
            "artifact_ref": f"sha256:{binding['artifact_digest']}",
            "experiment_id": binding["experiment_id"],
            "execution_id": binding["execution_id"],
            "created_at": verified["created_at"],
            "adequacy": report.adequacy.model_dump(mode="json"),
            "claim_ceiling": report.adequacy.claim_level,
            "integrity_not_truth": True,
        }

    def _request(
        self, payload: Mapping[str, Any]
    ) -> tuple[str, str, Mapping[str, Any]]:
        if set(payload) != {"experiment_id", "execution_id", "analysis_config"}:
            raise AnalysisError(
                "invalid_analysis_request",
                "Use exactly experiment_id, execution_id, and analysis_config; evidence fields are not accepted.",
            )
        experiment_id, execution_id, configuration = (
            payload.get("experiment_id"),
            payload.get("execution_id"),
            payload.get("analysis_config"),
        )
        if (
            not isinstance(experiment_id, str)
            or not isinstance(execution_id, str)
            or not isinstance(configuration, Mapping)
        ):
            raise AnalysisError(
                "invalid_analysis_request",
                "Experiment and execution identifiers and an analysis configuration are required.",
            )
        if set(configuration) != _CONFIG_KEYS:
            raise AnalysisError(
                "invalid_analysis_config",
                "The preregistered analysis configuration has unexpected or missing fields.",
            )
        for family in ("primary_main_effects", "secondary_interactions"):
            for effect in configuration.get(family, ()):
                if not isinstance(effect, Mapping) or "raw_p_value" not in effect:
                    continue
                raise AnalysisError(
                    "caller_p_value_forbidden",
                    "Effect p-values are derived from persisted paired observations; raw_p_value is forbidden.",
                )
        return experiment_id, execution_id, dict(configuration)

    def _frozen_configuration(
        self, execution: Mapping[str, Any], experiment_id: str
    ) -> Mapping[str, Any]:
        if not all(
            isinstance(execution.get(key), str) and len(str(execution[key])) == 64
            for key in ("spec_hash", "study_pack_hash", "content_digest")
        ):
            raise AnalysisError(
                "frozen_binding_missing",
                "The execution lacks immutable frozen hashes.",
                status_code=409,
            )
        if (
            execution["study_pack_hash"] != execution["content_digest"]
            or execution.get("frozen_at") is None
            or execution.get("owner_approval") != "approved"
        ):
            raise AnalysisError(
                "frozen_binding_mismatch",
                "The execution does not bind to an approved frozen experiment.",
                status_code=409,
            )
        try:
            spec = ExperimentSpec.model_validate_json(
                canonical_json(dict(execution["definition"] or {}))
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise AnalysisError(
                "frozen_binding_invalid",
                "The persisted frozen experiment definition is invalid.",
                status_code=409,
            ) from exc
        if not (
            spec.frozen
            and spec.experiment_id == experiment_id
            and spec.freeze_hash == execution["spec_hash"]
            and spec.study_pack_hash == execution["study_pack_hash"]
        ):
            raise AnalysisError(
                "frozen_binding_mismatch",
                "The persisted experiment definition does not match its frozen hashes.",
                status_code=409,
            )
        config = spec.extensions.get(_EXTENSION)
        if not isinstance(config, Mapping) or set(config) != _CONFIG_KEYS:
            raise AnalysisError(
                "analysis_not_preregistered",
                "The frozen experiment has no valid preregistered Analysis v1 configuration.",
                status_code=409,
            )
        # JSON canonicalization rejects untrusted Python objects from a malformed DB row.
        try:
            return dict(__import__("json").loads(canonical_json(dict(config))))
        except (TypeError, ValueError) as exc:
            raise AnalysisError(
                "analysis_not_preregistered",
                "The frozen analysis configuration is not canonical JSON.",
                status_code=409,
            ) from exc

    def _attempts(
        self, experiment_id: str, rows: list[Mapping[str, Any]]
    ) -> tuple[AttemptRecord, ...]:
        if not rows:
            raise AnalysisError(
                "analysis_no_attempts",
                "The execution has no durable attempts.",
                status_code=409,
            )
        grouped: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in rows:
            episode_id = row.get("episode_id")
            if not isinstance(episode_id, str) or not episode_id:
                raise AnalysisError(
                    "episode_binding_missing",
                    "An analysis attempt lacks its durable episode binding.",
                    status_code=409,
                )
            grouped[episode_id][str(row["attempt_id"])].append(row)
        records: list[AttemptRecord] = []
        for episode_id, attempts_by_id in sorted(grouped.items()):
            records.append(self._episode(experiment_id, episode_id, attempts_by_id))
        return tuple(records)

    def _episode(
        self,
        experiment_id: str,
        episode_id: str,
        attempts_by_id: Mapping[str, list[Mapping[str, Any]]],
    ) -> AttemptRecord:
        ordered = sorted(
            attempts_by_id.items(), key=lambda item: int(item[1][0]["attempt_ordinal"])
        )
        if any(
            isinstance(rows[0].get("attempt_ordinal"), bool)
            or not isinstance(rows[0].get("attempt_ordinal"), int)
            or rows[0]["attempt_ordinal"] != index
            for index, (_attempt_id, rows) in enumerate(ordered)
        ):
            raise AnalysisError(
                "retry_chain_invalid",
                f"Episode {episode_id} does not have one contiguous ordinal chain.",
                status_code=409,
            )
        constituent_ids = tuple(attempt_id for attempt_id, _rows in ordered)
        for index, (attempt_id, evidence_rows) in enumerate(ordered):
            request = dict(evidence_rows[0]["request_metadata"] or {})
            predecessor = request.get("retry_of_attempt_id")
            if index == 0:
                if predecessor is not None:
                    raise AnalysisError(
                        "retry_chain_invalid",
                        f"Episode {episode_id} has a retry predecessor before its first attempt.",
                        status_code=409,
                    )
                continue
            if predecessor != constituent_ids[index - 1]:
                raise AnalysisError(
                    "retry_chain_invalid",
                    f"Episode {episode_id} retry attempt {attempt_id} is not bound to its ordinal predecessor.",
                    status_code=409,
                )
        if len(ordered) == 1:
            attempt_id, evidence_rows = ordered[0]
            record = self._attempt(experiment_id, attempt_id, evidence_rows)
            return record.model_copy(
                update={
                    "episode_id": episode_id,
                    "constituent_attempt_ids": constituent_ids,
                    "continuous_outcomes": self._episode_metrics(record, 0),
                }
            )

        constituents: list[
            tuple[Mapping[str, Any], AttemptEnvelope | None, dict[str, Any]]
        ] = []
        for attempt_id, evidence_rows in ordered[:-1]:
            first, terminal, metadata = self._retry_constituent(attempt_id, evidence_rows)
            classification = metadata.get("failure_classification")
            if classification not in {
                "transient",
                "transient_adapter",
                "transient_provider",
            }:
                raise AnalysisError(
                    "retry_classification_invalid",
                    f"Episode {episode_id} retries a non-transient attempt {attempt_id}.",
                    status_code=409,
                )
            if first["attempt_status"] == "completed":
                raise AnalysisError(
                    "retry_chain_invalid",
                    f"Episode {episode_id} retries a completed attempt {attempt_id}.",
                    status_code=409,
                )
            constituents.append((first, terminal, metadata))
        final_id, final_rows = ordered[-1]
        final = self._attempt(experiment_id, final_id, final_rows)
        final_first = final_rows[0]
        _queued, final_terminal, final_metadata = self._envelopes(final_id, final_first)
        constituents.append((final_first, final_terminal, final_metadata))

        costs = [
            self._cost(str(first["attempt_id"]), list(first.get("usage_rows") or []))
            for first, _terminal, _metadata in constituents
        ]
        all_terminal_envelopes = all(
            terminal is not None for _first, terminal, _metadata in constituents
        )
        all_reconciled = all_terminal_envelopes and all(
            status is CostStatus.RECONCILED for status, *_ in costs
        )
        cost = sum(amount or 0.0 for _status, amount, _usage, _price in costs)
        usage_refs = tuple(ref for _status, _cost, ref, _price in costs if ref)
        price_refs = tuple(ref for _status, _cost, _usage, ref in costs if ref)
        latency = sum(
            (terminal.completed_at - terminal.started_at).total_seconds()
            for _first, terminal, _metadata in constituents
            if terminal is not None
            and terminal.completed_at is not None
            and terminal.started_at is not None
        )
        if any(
            terminal is None
            or terminal.completed_at is None
            or terminal.started_at is None
            for _first, terminal, _metadata in constituents
        ):
            latency_value: float | None = None
        else:
            latency_value = latency
        return final.model_copy(
            update={
                "episode_id": episode_id,
                "constituent_attempt_ids": constituent_ids,
                "continuous_outcomes": self._episode_metrics(final, len(ordered) - 1),
                "trace_complete": all(
                    metadata.get("trace_complete") is True
                    for _first, _terminal, metadata in constituents
                ),
                "manipulation_pass": all(
                    metadata.get("manipulation_pass") is True
                    for _first, _terminal, metadata in constituents
                ),
                "cost_status": CostStatus.RECONCILED if all_reconciled else CostStatus.UNKNOWN,
                "cost_usd": cost if all_reconciled else None,
                "provider_usage_ref": "|".join(usage_refs) if all_reconciled else None,
                "price_reference": "|".join(price_refs) if all_reconciled else None,
                "latency_seconds": latency_value,
            }
        )

    @staticmethod
    def _episode_metrics(final: AttemptRecord, retry_count: int) -> tuple[tuple[str, float], ...]:
        required = {"infrastructure_retry_count", "recovered_transient_failure"}
        present = {name for name, _value in final.continuous_outcomes}
        if required & present:
            raise AnalysisError(
                "evaluator_evidence_invalid",
                "Evaluator deterministic metrics may not overwrite retry-derived metrics.",
                status_code=409,
            )
        return final.continuous_outcomes + (
            ("infrastructure_retry_count", float(retry_count)),
            ("recovered_transient_failure", float(retry_count > 0 and final.success)),
        )

    def _retry_constituent(
        self, attempt_id: str, rows: list[Mapping[str, Any]]
    ) -> tuple[Mapping[str, Any], AttemptEnvelope | None, dict[str, Any]]:
        first = rows[0]
        if first["attempt_status"] not in _TERMINAL_ATTEMPT_STATUSES:
            raise AnalysisError(
                "attempt_incomplete",
                f"Attempt {attempt_id} is not terminal.",
                status_code=409,
            )
        if any(
            any(
                row[key] != first[key]
                for key in (
                    "episode_id", "request_metadata", "result_metadata", "scenario_id",
                    "episode_metadata", "attempt_ordinal", "attempt_status",
                )
            )
            for row in rows[1:]
        ):
            raise AnalysisError(
                "attempt_binding_ambiguous",
                f"Attempt {attempt_id} has inconsistent joined evidence.",
                status_code=409,
            )
        if sum(row.get("id") is not None for row in rows) > 1:
            raise AnalysisError(
                "retry_evaluation_ambiguous",
                f"Retry attempt {attempt_id} has ambiguous evaluator evidence.",
                status_code=409,
            )
        request_metadata = dict(first["request_metadata"] or {})
        queued = self._parse_envelope(
            attempt_id, request_metadata.get("envelope"), source="queued request"
        )
        if queued.attempt_id != attempt_id or queued.status != "queued":
            raise AnalysisError(
                "attempt_binding_invalid",
                f"Attempt {attempt_id} does not retain its immutable queued request envelope.",
                status_code=409,
            )
        metadata = dict(first["result_metadata"] or {})
        if metadata.get("terminal_envelope") is None:
            return first, None, metadata
        _queued, terminal, metadata = self._envelopes(attempt_id, first)
        if terminal.status != first["attempt_status"]:
            raise AnalysisError(
                "attempt_terminal_binding_mismatch",
                f"Attempt {attempt_id} terminal envelope disagrees with its persisted status.",
                status_code=409,
            )
        self._require_terminal_output_binding(attempt_id, terminal, metadata, {})
        self._require_usage_observation_binding(attempt_id, terminal, metadata)
        return first, terminal, metadata

    def _attempt(
        self, experiment_id: str, attempt_id: str, rows: list[Mapping[str, Any]]
    ) -> AttemptRecord:
        first = rows[0]
        if first["attempt_status"] not in _TERMINAL_ATTEMPT_STATUSES:
            raise AnalysisError(
                "attempt_incomplete",
                f"Attempt {attempt_id} is not terminal.",
                status_code=409,
            )
        if any(
            any(
                row[key] != first[key]
                for key in (
                    "episode_id",
                    "request_metadata",
                    "result_metadata",
                    "scenario_id",
                    "episode_metadata",
                    "attempt_ordinal",
                    "attempt_status",
                )
            )
            for row in rows[1:]
        ):
            raise AnalysisError(
                "attempt_binding_ambiguous",
                f"Attempt {attempt_id} has inconsistent joined evidence.",
                status_code=409,
            )
        evaluations = [row for row in rows if row.get("id") is not None]
        if len(evaluations) != 1:
            raise AnalysisError(
                "evaluator_evidence_missing",
                f"Attempt {attempt_id} requires exactly one durable evaluator record.",
                status_code=409,
            )
        evaluation = evaluations[0]
        _queued_envelope, terminal_envelope, result_metadata = self._envelopes(
            attempt_id, first
        )
        if terminal_envelope.status != first["attempt_status"]:
            raise AnalysisError(
                "attempt_terminal_binding_mismatch",
                f"Attempt {attempt_id} terminal envelope disagrees with its persisted status.",
                status_code=409,
            )
        self._require_evaluation_artifacts(
            attempt_id, first, evaluation, terminal_status=terminal_envelope.status
        )
        self._require_terminal_output_binding(
            attempt_id, terminal_envelope, result_metadata, evaluation
        )
        self._require_usage_observation_binding(
            attempt_id, terminal_envelope, result_metadata
        )
        result = self._evaluator_result(
            attempt_id, str(first["episode_id"]), evaluation
        )
        quality_only = (
            terminal_envelope.status == "incomplete"
            and terminal_envelope.response_hash is not None
            and "provider_cost_identity_claims_hold_for_incomplete_adapter_evidence"
            in tuple(dict(result or {}).get("exclusions", ()))
        )
        outcome = (
            dict(result or {}).get("outcome") if isinstance(result, Mapping) else None
        )
        if not isinstance(outcome, Mapping):
            raise AnalysisError(
                "evaluator_evidence_missing",
                f"Attempt {attempt_id} has no persisted evaluator outcome.",
                status_code=409,
            )
        mission = outcome.get("mission_success")
        auditability = outcome.get("auditability")
        severe = outcome.get("severe_failures", ())
        deterministic = outcome.get("deterministic", {})
        if (
            isinstance(mission, bool)
            or not isinstance(mission, (int, float))
            or not 0 <= float(mission) <= 1
            or isinstance(auditability, bool)
            or not isinstance(auditability, (int, float))
            or not 0 <= float(auditability) <= 1
            or not isinstance(severe, (list, tuple))
            or not all(isinstance(item, str) and item for item in severe)
            or not isinstance(deterministic, Mapping)
            or (
                terminal_envelope.status != "completed"
                and not quality_only
                and (not severe or float(mission) >= 1.0)
            )
        ):
            raise AnalysisError(
                "evaluator_evidence_invalid",
                f"Attempt {attempt_id} has invalid persisted evaluator outcomes.",
                status_code=409,
            )
        metrics: list[tuple[str, float]] = []
        for key, value in deterministic.items():
            if (
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
            ):
                raise AnalysisError(
                    "evaluator_evidence_invalid",
                    f"Attempt {attempt_id} has invalid deterministic metric evidence.",
                    status_code=409,
                )
            metrics.append((key, float(value)))
        metadata = dict(first["episode_metadata"] or {})
        required_metadata = (
            "scenario_variant",
            "scenario_pair_id",
            "scenario_cluster_id",
            "repetition_index",
            "analysis_pair_id",
        )
        if any(key not in metadata for key in required_metadata):
            raise AnalysisError(
                "legacy_analysis_binding",
                f"Attempt {attempt_id} lacks the explicit durable analysis-unit binding.",
                status_code=409,
            )
        variant = metadata["scenario_variant"]
        scenario_pair_id = metadata["scenario_pair_id"]
        cluster = metadata["scenario_cluster_id"]
        repetition_index = metadata["repetition_index"]
        analysis_pair_id = metadata["analysis_pair_id"]
        if (
            variant not in {"clean", "stress"}
            or not isinstance(scenario_pair_id, str)
            or not scenario_pair_id
            or not isinstance(cluster, str)
            or not cluster
            or isinstance(repetition_index, bool)
            or not isinstance(repetition_index, int)
            or repetition_index < 0
            or not isinstance(analysis_pair_id, str)
            or len(analysis_pair_id) != 64
            or any(
                character not in "0123456789abcdef" for character in analysis_pair_id
            )
            or not isinstance(first["scenario_id"], str)
            or not first["scenario_id"]
        ):
            raise AnalysisError(
                "analysis_binding_invalid",
                f"Attempt {attempt_id} has an invalid durable analysis-unit binding.",
                status_code=409,
            )
        usage_status, cost, usage_ref, price_ref = self._cost(
            attempt_id, list(first.get("usage_rows") or [])
        )
        trace_complete = result_metadata.get("trace_complete") is True
        manipulation_pass = bool(result_metadata.get("manipulation_pass", False))
        held_out = bool(metadata.get("held_out", False))
        independent = bool(dict(result).get("evaluator_independent", False))
        if not independent:
            raise AnalysisError(
                "evaluator_independence_missing",
                f"Attempt {attempt_id} lacks persisted independent-evaluator evidence.",
                status_code=409,
            )
        return AttemptRecord(
            attempt_id=attempt_id,
            experiment_id=experiment_id,
            task_id=str(first["scenario_id"]),
            task_cluster_id=cluster,
            scaffold_id=terminal_envelope.harness_id,
            pair_id=analysis_pair_id,
            repeat_index=repetition_index + 1,
            variant=variant,
            factor_levels=tuple(
                {"factor_id": key, "level": value}
                for key, value in sorted(terminal_envelope.factor_assignments.items())
            ),
            success=(
                terminal_envelope.status == "completed"
                and float(mission) >= 1.0
                and not severe
            ),
            continuous_outcomes=tuple(metrics),
            severe_failures=tuple(sorted(set(severe))),
            auditability=float(auditability),
            trace_complete=trace_complete,
            manipulation_pass=manipulation_pass,
            evaluator_independent=True,
            held_out=held_out,
            cost_status=usage_status,
            cost_usd=cost,
            provider_usage_ref=usage_ref,
            price_reference=price_ref,
            latency_seconds=self._latency(outcome),
        )

    def _evaluator_result(
        self,
        attempt_id: str,
        episode_id: str,
        evaluation: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = evaluation.get("result")
        if not isinstance(result, Mapping):
            raise AnalysisError(
                "evaluator_evidence_missing",
                f"Attempt {attempt_id} has no persisted evaluator result.",
                status_code=409,
            )
        result = dict(result)
        if "record" not in result:
            allowed_legacy_keys = {"evaluator_independent", "exclusions", "outcome"}
            if (
                set(result) - allowed_legacy_keys
                or "outcome" not in result
                or evaluation.get("evaluator") == "arena-evaluator"
            ):
                raise AnalysisError(
                    "evaluator_evidence_invalid",
                    f"Attempt {attempt_id} has an untyped evaluator result shape.",
                    status_code=409,
                )
            return result

        durable_key_sets = (
            {
                "record",
                "grader_results",
                "qualitative_claims_eligible",
                "exclusions",
                "claim_limitations",
                "evaluator_independent",
                "independence_scope",
                "external_independence",
            },
            {
                "record",
                "grader_results",
                "exclusions",
                "adapter_terminal_label",
                "evaluator_independent",
                "independence_scope",
                "external_independence",
            },
        )
        if (
            evaluation.get("evaluator") != "arena-evaluator"
            or set(result) not in durable_key_sets
        ):
            raise AnalysisError(
                "evaluator_evidence_invalid",
                f"Attempt {attempt_id} has an unrecognized durable evaluator envelope.",
                status_code=409,
            )
        artifact_digest = evaluation.get("result_artifact_digest")
        result_hash = evaluation.get("result_hash")
        if not isinstance(artifact_digest, str) or not isinstance(result_hash, str):
            raise AnalysisError(
                "evaluator_evidence_missing",
                f"Attempt {attempt_id} lacks a durable evaluator result artifact.",
                status_code=409,
            )
        try:
            stored = self.artifact_store.get_bytes(artifact_digest)
        except Exception as exc:
            raise AnalysisError(
                "evaluator_artifact_unavailable",
                f"Attempt {attempt_id} evaluator result artifact cannot be re-read.",
                status_code=409,
            ) from exc
        if (
            sha256_bytes(stored) != result_hash
            or stored != canonical_json(result)
        ):
            raise AnalysisError(
                "evaluator_evidence_invalid",
                f"Attempt {attempt_id} evaluator result artifact does not match its durable record.",
                status_code=409,
            )
        try:
            record = EvaluationRecord.model_validate_json(canonical_json(result["record"]))
        except (KeyError, TypeError, ValidationError, ValueError) as exc:
            raise AnalysisError(
                "evaluator_evidence_invalid",
                f"Attempt {attempt_id} durable evaluator record is invalid.",
                status_code=409,
            ) from exc
        if (
            record.evaluation_id != evaluation.get("id")
            or record.episode_id != episode_id
            or record.evaluator_version != evaluation.get("evaluator_version")
            or record.trace_hash != evaluation.get("trace_artifact_digest")
        ):
            raise AnalysisError(
                "evaluator_evidence_invalid",
                f"Attempt {attempt_id} durable evaluator record is not bound to its attempt.",
                status_code=409,
            )
        return {**result, "outcome": record.outcome.model_dump(mode="json")}

    @staticmethod
    def _parse_envelope(
        attempt_id: str, value: Any, *, source: str
    ) -> AttemptEnvelope:
        try:
            return AttemptEnvelope.model_validate_json(canonical_json(value))
        except (ValidationError, ValueError, TypeError) as exc:
            raise AnalysisError(
                "attempt_binding_invalid",
                f"Attempt {attempt_id} has an invalid {source} envelope.",
                status_code=409,
            ) from exc

    def _envelopes(
        self, attempt_id: str, attempt: Mapping[str, Any]
    ) -> tuple[AttemptEnvelope, AttemptEnvelope, dict[str, Any]]:
        request_metadata = dict(attempt["request_metadata"] or {})
        result_metadata = dict(attempt["result_metadata"] or {})
        queued = self._parse_envelope(
            attempt_id, request_metadata.get("envelope"), source="queued request"
        )
        if queued.attempt_id != attempt_id or queued.status != "queued":
            raise AnalysisError(
                "attempt_binding_invalid",
                f"Attempt {attempt_id} does not retain its immutable queued request envelope.",
                status_code=409,
            )
        terminal_data = result_metadata.get("terminal_envelope")
        if terminal_data is None:
            raise AnalysisError(
                "legacy_terminal_binding",
                f"Attempt {attempt_id} lacks the worker-produced terminal envelope binding.",
                status_code=409,
            )
        terminal = self._parse_envelope(
            attempt_id, terminal_data, source="terminal result"
        )
        if (
            terminal.status not in _TERMINAL_ATTEMPT_STATUSES
            or terminal.attempt_id != attempt_id
        ):
            raise AnalysisError(
                "attempt_terminal_binding_invalid",
                f"Attempt {attempt_id} does not have a valid terminal envelope.",
                status_code=409,
            )
        for field in _IMMUTABLE_ENVELOPE_FIELDS:
            if getattr(queued, field) != getattr(terminal, field):
                raise AnalysisError(
                    "attempt_terminal_binding_mismatch",
                    f"Attempt {attempt_id} terminal envelope changed immutable field {field}.",
                    status_code=409,
                )
        return queued, terminal, result_metadata

    def _require_terminal_output_binding(
        self,
        attempt_id: str,
        terminal: AttemptEnvelope,
        result_metadata: Mapping[str, Any],
        evaluation: Mapping[str, Any],
    ) -> None:
        output_digest = result_metadata.get("output_artifact_digest")
        response_hash = result_metadata.get("response_hash")
        observed_output = terminal.status == "completed" or (
            terminal.status == "incomplete" and terminal.response_hash is not None
        )
        if not observed_output:
            if (
                output_digest is not None
                or response_hash is not None
                or terminal.response_hash is not None
                or evaluation.get("output_artifact_digest") is not None
            ):
                raise AnalysisError(
                    "attempt_terminal_output_mismatch",
                    f"Attempt {attempt_id} has output evidence for a non-completed terminal result.",
                    status_code=409,
                )
            return
        if (
            not isinstance(output_digest, str)
            or len(output_digest) != 64
            or terminal.response_hash != output_digest
            or response_hash != output_digest
            or evaluation.get("output_artifact_digest") != output_digest
        ):
            raise AnalysisError(
                "attempt_terminal_output_mismatch",
                f"Attempt {attempt_id} terminal response hash is not bound to its persisted output artifact.",
                status_code=409,
            )

    def _require_usage_observation_binding(
        self,
        attempt_id: str,
        terminal: AttemptEnvelope,
        result_metadata: Mapping[str, Any],
    ) -> None:
        usage_data = result_metadata.get("usage")
        if usage_data is None:
            return
        try:
            usage = ProviderUsage.model_validate_json(canonical_json(usage_data))
        except (ValidationError, ValueError, TypeError) as exc:
            raise AnalysisError(
                "usage_evidence_invalid",
                f"Attempt {attempt_id} has invalid persisted provider usage observations.",
                status_code=409,
            ) from exc
        if (
            terminal.observed_provider_version != usage.observed_provider_version
            or terminal.observed_endpoint_digest != usage.observed_endpoint_digest
        ):
            raise AnalysisError(
                "attempt_terminal_usage_mismatch",
                f"Attempt {attempt_id} terminal endpoint observations disagree with persisted usage.",
                status_code=409,
            )

    def _require_evaluation_artifacts(
        self,
        attempt_id: str,
        attempt: Mapping[str, Any],
        evaluation: Mapping[str, Any],
        *,
        terminal_status: str,
    ) -> None:
        required = (
            evaluation.get("input_artifact_digest"),
            evaluation.get("output_artifact_digest"),
            evaluation.get("trace_artifact_digest"),
        )
        metadata = dict(attempt["result_metadata"] or {})
        expected = (
            metadata.get("input_artifact_digest"),
            metadata.get("output_artifact_digest"),
            metadata.get("trace_artifact_digest"),
        )
        required_for_status = (
            required
            if terminal_status == "completed"
            else tuple(value for value in required if value is not None)
        )
        if required != expected or not all(
            isinstance(value, str) and len(value) == 64
            for value in required_for_status
        ):
            raise AnalysisError(
                "evaluator_artifact_binding_missing",
                f"Attempt {attempt_id} evaluator artifacts do not exactly match the persisted attempt artifacts.",
                status_code=409,
            )
        if (
            not isinstance(evaluation.get("evaluator"), str)
            or not isinstance(evaluation.get("evaluator_version"), str)
            or not isinstance(evaluation.get("evaluator_digest"), str)
            or not isinstance(evaluation.get("result_hash"), str)
        ):
            raise AnalysisError(
                "evaluator_evidence_missing",
                f"Attempt {attempt_id} evaluator identity/hash evidence is incomplete.",
                status_code=409,
            )
        with self.repository.engine.connect() as conn:
            found = set(
                conn.execute(
                    select(artifacts.c.digest).where(
                        artifacts.c.digest.in_(required_for_status)
                    )
                ).scalars()
            )
        if found != set(required_for_status):
            raise AnalysisError(
                "evaluator_artifact_unregistered",
                f"Attempt {attempt_id} evaluator artifacts are not registered.",
                status_code=409,
            )
        try:
            for digest in required_for_status:
                self.artifact_store.get_bytes(str(digest))
        except Exception as exc:
            raise AnalysisError(
                "evaluator_artifact_unavailable",
                f"Attempt {attempt_id} evaluator artifacts cannot be re-read.",
                status_code=409,
            ) from exc

    @staticmethod
    def _latency(outcome: Mapping[str, Any]) -> float | None:
        value = outcome.get("latency_seconds")
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise AnalysisError(
                "evaluator_evidence_invalid",
                "Persisted latency evidence is invalid.",
                status_code=409,
            )
        return float(value)

    @staticmethod
    def _cost(
        attempt_id: str, rows: list[Mapping[str, Any]]
    ) -> tuple[CostStatus, float | None, str | None, str | None]:
        if not rows:
            return CostStatus.UNKNOWN, None, None, None
        row = rows[-1]
        if row.get("cost_status") != "reconciled":
            return CostStatus.UNKNOWN, None, None, None
        cost, usage, price = (
            row.get("actual_cost_usd"),
            row.get("provider_usage_digest"),
            row.get("price_catalog_revision"),
        )
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or cost < 0
            or not isinstance(usage, str)
            or len(usage) != 64
            or not isinstance(price, str)
            or not price
        ):
            raise AnalysisError(
                "usage_evidence_invalid",
                f"Attempt {attempt_id} has incomplete reconciled usage evidence.",
                status_code=409,
            )
        return CostStatus.RECONCILED, float(cost), f"usage:{usage}", f"price:{price}"
