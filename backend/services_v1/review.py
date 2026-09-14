"""Staged, blind review admission over persisted attempt artifacts only."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from adapters_v1 import AttemptInput
from artifacts_v1 import ArtifactIntegrityError, ArtifactStore
from persistence_v1 import ArenaRepository, ImmutableReviewConflict
from persistence_v1.schema import annotation_batches, artifacts, projects
from protocol_v1 import TraceEvent
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from review_v1 import (
    AdjudicationSubmission,
    AnnotationBatch,
    AnnotationItem,
    AnnotationSubmission,
    HumanRubric,
)


class ReviewError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_BLIND_FORBIDDEN = frozenset({"treatment", "harness", "factor", "scaffold", "adapter", "control_plane", "controlplane"})
_CALLER_EVIDENCE_FORBIDDEN = frozenset({"blind_payload", "input_artifact", "output_artifact", "trace_artifact", "raw_input", "raw_output", "raw_trace"})
_CLAIM_CEILING = "durable blind-review protocol completion only; reviewer identity, human validation, and independent validation remain unverified"


class ReviewService:
    """This service never accepts adapters, workers, control-plane handles, or reviewer identities."""

    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def resolve_project(self, project_id: str | None) -> str:
        value = project_id or self.personal_project_id
        if not value:
            raise ReviewError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            exists = conn.execute(select(projects.c.id).where(projects.c.id == value)).scalar_one_or_none()
        if exists is None:
            raise ReviewError("unknown_project", "The supplied project does not exist.", status_code=404)
        return value

    def create_annotation_batch(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        self._reject_caller_evidence(payload)
        self._reject_blind_leaks(payload)
        try:
            request = AnnotationBatch.model_validate_json(canonical_json(dict(payload)))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ReviewError("invalid_annotation_batch", "The batch may contain only blind assignments and items.") from exc
        if request.grader_plan.human_calibration_receipt is not None:
            raise ReviewError("self_asserted_human_validation", "A submitted grader plan cannot self-assert a HumanCalibrationReceipt.", status_code=409)
        request_json = request.model_dump(mode="json")
        assignments: list[dict[str, Any]] = []
        for item in request.items:
            blind_payload_digest = self._blind_payload_digest(project_id, item, request)
            for pseudonym in request.annotator_pseudonyms:
                assignment_hash = sha256({"batch": request.batch_id, "item": item.item_id, "attempt": item.attempt_id, "pseudonym": pseudonym, "payload": blind_payload_digest})
                assignments.append({
                    "id": assignment_hash, "batch_id": request.batch_id, "item_id": item.item_id,
                    "attempt_id": item.attempt_id, "annotator_pseudonym": pseudonym,
                    "blind_payload_digest": blind_payload_digest, "assignment_hash": assignment_hash,
                    "identity_state": "identity_unverified",
                })
        batch = {
            "id": request.batch_id, "project_id": project_id, "batch_hash": sha256(request_json),
            "protocol_hash": request.protocol_hash, "evaluator": request.evaluator.evaluator_id,
            "evaluator_version": request.evaluator.version, "evaluator_digest": request.evaluator.digest,
            "grader_plan": request.grader_plan.model_dump(mode="json"), "request_json": request_json,
        }
        try:
            replay = self.repository.create_annotation_batch(project_id, batch=batch, assignments=tuple(sorted(assignments, key=lambda value: value["id"])))
        except ImmutableReviewConflict as exc:
            raise ReviewError("annotation_batch_conflict", "The batch identifier is already bound to different content.", status_code=409) from exc
        return {**self._summary(project_id, request.batch_id), "idempotent_replay": replay}

    def batch_view(self, batch_id: str, pseudonym: str | None, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        batch = self._batch(project_id, batch_id)
        if not pseudonym:
            raise ReviewError("pseudonym_required", "A reviewer pseudonym is required for a blind batch view.")
        assignments = [row for row in self.repository.review_assignments(project_id, batch_id) if row["annotator_pseudonym"] == pseudonym]
        summary = self._summary(project_id, batch_id)
        return {
            "batch_id": batch["id"], "protocol_hash": batch["protocol_hash"], "status": summary["status"],
            "conflicted_dimensions": summary["conflicted_dimensions"],
            "identity_state": "identity_unverified", "assignments": [self._blind_assignment(row) for row in assignments],
            "claim_ceiling": _CLAIM_CEILING,
        }

    def list_annotation_batches(
        self,
        *,
        project_id: str | None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return project-owned, blind-safe batch summaries without reading payload bytes."""
        project_id = self.resolve_project(project_id)
        limit, offset = self._page(limit, offset)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(
                select(annotation_batches)
                .where(annotation_batches.c.project_id == project_id)
                .order_by(annotation_batches.c.created_at, annotation_batches.c.id)
            ).mappings().all()
        summaries = [self._list_summary(project_id, row) for row in rows]
        if status is not None:
            summaries = [item for item in summaries if item["status"] == status]
        page = summaries[offset : offset + limit]
        return {
            "annotation_batches": page,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": offset + limit if len(summaries) > offset + limit else None,
            },
            "identity_state": "identity_unverified",
            "claim_ceiling": _CLAIM_CEILING,
        }

    def assignment_view(self, batch_id: str, assignment_id: str, pseudonym: str | None, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        if not pseudonym:
            raise ReviewError("pseudonym_required", "A reviewer pseudonym is required for a blind assignment view.")
        assignment = self.repository.review_assignment(project_id, batch_id, assignment_id)
        if assignment is None or assignment["annotator_pseudonym"] != pseudonym:
            raise ReviewError("assignment_not_found", "The blind assignment was not found.", status_code=404)
        content = self._read_registered_artifact(str(assignment["blind_payload_digest"]))
        try:
            blind_payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewError("blind_payload_invalid", "The blinded assignment payload cannot be read safely.", status_code=409) from exc
        if not isinstance(blind_payload, Mapping) or canonical_json(dict(blind_payload)) != content:
            raise ReviewError("blind_payload_invalid", "The blinded assignment payload is not canonical.", status_code=409)
        self._reject_blind_leaks(blind_payload)
        return {
            **self._blind_assignment(assignment), "blinded_content": blind_payload,
            "identity_state": "identity_unverified", "claim_ceiling": _CLAIM_CEILING,
        }

    def submit_annotation(self, batch_id: str, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        try:
            submission = AnnotationSubmission.model_validate_json(canonical_json(dict(payload)))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ReviewError("invalid_annotation", "Use exactly assignment_id, annotator_pseudonym, and per-dimension scores.") from exc
        assignment = self.repository.review_assignment(project_id, batch_id, submission.assignment_id)
        if assignment is None or assignment["annotator_pseudonym"] != submission.annotator_pseudonym:
            raise ReviewError("assignment_not_found", "The assignment does not belong to this pseudonym in this project batch.", status_code=404)
        rubric = self._rubric(self._batch(project_id, batch_id))
        scores = self._exact_dimension_scores(submission.dimension_scores, rubric, "annotation")
        summary_score = self._mean_score(scores)
        record = {
            "id": sha256({"assignment": assignment["assignment_hash"], "dimension_scores": scores}),
            "attempt_id": assignment["attempt_id"], "user_id": None, "kind": "blind_human_annotation",
            "body": {
                "blind": True,
                "identity_state": "identity_unverified",
                "rubric_digest": rubric.digest,
                "dimension_scores": scores,
                "score_summary": {"kind": "mean_summary_only", "value": summary_score},
            }, "project_id": project_id,
            "batch_id": batch_id, "item_id": assignment["item_id"], "annotator_pseudonym": submission.annotator_pseudonym,
            "assignment_hash": assignment["assignment_hash"], "score": summary_score,
        }
        try:
            replay = self.repository.submit_review_annotation(project_id, batch_id, submission.assignment_id, record)
        except ImmutableReviewConflict as exc:
            raise ReviewError("annotation_conflict", "This assignment already has a different immutable score.", status_code=409) from exc
        return {**self._summary(project_id, batch_id), "idempotent_replay": replay}

    def submit_adjudication(self, batch_id: str, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        try:
            submission = AdjudicationSubmission.model_validate_json(canonical_json(dict(payload)))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ReviewError("invalid_adjudication", "Use exactly item_id, adjudicator_pseudonym, per-dimension final scores, decision, rationale, and evidence_artifact_digest.") from exc
        summary = self._summary(project_id, batch_id)
        conflicted_dimensions = summary["conflicted_dimensions"].get(submission.item_id, [])
        if not conflicted_dimensions:
            raise ReviewError("adjudication_not_required", "Adjudication is permitted only after complete conflicting annotations.", status_code=409)
        rubric = self._rubric(self._batch(project_id, batch_id))
        final_scores = self._exact_dimension_scores(
            submission.final_scores, rubric, "adjudication", expected=set(conflicted_dimensions),
        )
        if not self.repository.review_item_payload_matches(
            project_id, batch_id, submission.item_id, submission.evidence_artifact_digest,
        ):
            raise ReviewError("adjudication_evidence_unbound", "Adjudication evidence must be the blinded artifact bound to this project batch item.", status_code=409)
        self._read_registered_artifact(submission.evidence_artifact_digest)
        record = {
            "id": sha256({"batch": batch_id, "item": submission.item_id, "kind": "adjudication", "final_scores": final_scores}), "batch_id": batch_id,
            "item_id": submission.item_id, "adjudicator_pseudonym": submission.adjudicator_pseudonym,
            "final_score": self._mean_score(final_scores), "decision": submission.decision, "rationale": submission.rationale,
            "evidence_ref": submission.evidence_artifact_digest,
        }
        try:
            replay = self.repository.create_review_adjudication(project_id, batch_id, record, final_scores)
        except ImmutableReviewConflict as exc:
            raise ReviewError("adjudication_conflict", "This item already has a different immutable adjudication.", status_code=409) from exc
        return {**self._summary(project_id, batch_id), "idempotent_replay": replay}

    def _summary(self, project_id: str, batch_id: str) -> dict[str, Any]:
        batch = self._batch(project_id, batch_id)
        rubric = self._rubric(batch)
        dimension_ids = {dimension.metric_id for dimension in rubric.dimensions}
        assignments = self.repository.review_assignments(project_id, batch_id)
        annotations = self.repository.review_annotations(project_id, batch_id)
        adjudications = self.repository.review_adjudications(project_id, batch_id)
        scores = {
            str(row["assignment_hash"]): self._stored_dimension_scores(row, rubric)
            for row in annotations
        }
        by_item: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for assignment in assignments:
            by_item[str(assignment["item_id"])].append(assignment)
        conflicted: dict[str, list[str]] = {}
        incomplete: list[str] = []
        adjudicated = {
            str(row["item_id"]): set(row["dimension_scores"])
            for row in adjudications
        }
        for item_id, item_assignments in by_item.items():
            item_scores = [
                scores[str(row["assignment_hash"])]
                for row in item_assignments
                if str(row["assignment_hash"]) in scores
            ]
            if len(item_scores) != len(item_assignments):
                incomplete.append(item_id)
                continue
            disputed = sorted(
                metric_id
                for metric_id in dimension_ids
                if max(score[metric_id] for score in item_scores)
                - min(score[metric_id] for score in item_scores) > 0.20
            )
            if disputed:
                conflicted[item_id] = disputed
        unresolved = {
            item_id: dimensions
            for item_id, dimensions in conflicted.items()
            if not set(dimensions) <= adjudicated.get(item_id, set())
        }
        status = "PENDING" if not annotations else "IN_REVIEW" if incomplete else "NEEDS_ADJUDICATION" if unresolved else "COMPLETE"
        completion = {
            "batch_hash": batch["batch_hash"],
            "assignments": [{"assignment_hash": row["assignment_hash"], "item_id": row["item_id"]} for row in assignments],
            "annotations": [
                {"assignment_hash": row["assignment_hash"], "dimension_scores": scores[str(row["assignment_hash"])]}
                for row in assignments
                if str(row["assignment_hash"]) in scores
            ],
            "adjudications": [
                {"item_id": row["item_id"], "id": row["id"], "dimension_scores": row["dimension_scores"]}
                for row in adjudications
            ],
        }
        return {
            "batch_id": batch_id, "status": status, "assignment_count": len(assignments), "submitted_annotation_count": len(annotations),
            "conflicted_items": sorted(conflicted), "conflicted_dimensions": conflicted,
            "incomplete_items": sorted(incomplete), "protocol_completion_digest": sha256(completion),
            "protocol_complete": status == "COMPLETE", "identity_state": "identity_unverified", "human_calibration_receipt": None,
            "human_validated": False, "independently_validated": False, "claim_ceiling": _CLAIM_CEILING,
        }

    def _list_summary(self, project_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        """Revalidate stored batch metadata before emitting a redacted summary."""
        batch_id = str(row["id"])
        try:
            request = AnnotationBatch.model_validate_json(canonical_json(row["request_json"]))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ReviewError(
                "annotation_batch_integrity_error",
                "A stored annotation batch cannot be revalidated safely.",
                status_code=409,
            ) from exc
        if (
            request.batch_id != batch_id
            or sha256(request.model_dump(mode="json")) != row["batch_hash"]
            or request.protocol_hash != row["protocol_hash"]
            or request.evaluator.evaluator_id != row["evaluator"]
            or request.evaluator.version != row["evaluator_version"]
            or request.evaluator.digest != row["evaluator_digest"]
        ):
            raise ReviewError(
                "annotation_batch_integrity_error",
                "A stored annotation batch is not bound to its canonical metadata.",
                status_code=409,
            )
        summary = self._summary(project_id, batch_id)
        return {
            "batch_id": batch_id,
            "created_at": row["created_at"],
            "protocol_hash": row["protocol_hash"],
            "evaluator": {
                "evaluator_id": row["evaluator"],
                "version": row["evaluator_version"],
                "digest": row["evaluator_digest"],
            },
            "status": summary["status"],
            "assignment_count": summary["assignment_count"],
            "submitted_annotation_count": summary["submitted_annotation_count"],
            "conflicted_items": summary["conflicted_items"],
            "incomplete_items": summary["incomplete_items"],
            "protocol_complete": summary["protocol_complete"],
            "identity_state": "identity_unverified",
            "claim_ceiling": _CLAIM_CEILING,
        }

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ReviewError("invalid_limit", "The list limit must be an integer from 1 to 100.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ReviewError("invalid_offset", "The list offset must be a nonnegative integer.")
        return limit, offset

    def _batch(self, project_id: str, batch_id: str) -> Mapping[str, Any]:
        batch = self.repository.get_annotation_batch(project_id, batch_id)
        if batch is None:
            raise ReviewError("annotation_batch_not_found", "The annotation batch was not found.", status_code=404)
        return batch

    @staticmethod
    def _rubric(batch: Mapping[str, Any]) -> HumanRubric:
        request = batch.get("request_json")
        if not isinstance(request, Mapping):
            raise ReviewError("rubric_invalid", "The immutable batch rubric cannot be read.", status_code=409)
        try:
            return HumanRubric.model_validate_json(canonical_json(request.get("rubric")))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ReviewError("rubric_invalid", "The immutable batch rubric cannot be revalidated.", status_code=409) from exc

    @staticmethod
    def _exact_dimension_scores(
        values: Mapping[str, float],
        rubric: HumanRubric,
        kind: str,
        *,
        expected: set[str] | None = None,
    ) -> dict[str, float]:
        expected_ids = expected if expected is not None else {
            dimension.metric_id for dimension in rubric.dimensions
        }
        supplied = set(values)
        if supplied != expected_ids:
            required = "conflicted rubric dimensions" if expected is not None else "rubric dimensions"
            raise ReviewError(
                "dimension_scores_mismatch",
                f"{kind.capitalize()} scores must include exactly the {required}.",
            )
        normalized = {metric_id: float(values[metric_id]) for metric_id in sorted(expected_ids)}
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in normalized.values()):
            raise ReviewError("dimension_scores_mismatch", f"{kind.capitalize()} scores must be finite values in [0, 1].")
        return normalized

    @staticmethod
    def _stored_dimension_scores(row: Mapping[str, Any], rubric: HumanRubric) -> dict[str, float]:
        body = row.get("body")
        values = body.get("dimension_scores") if isinstance(body, Mapping) else None
        if not isinstance(values, Mapping) or body.get("rubric_digest") != rubric.digest:
            raise ReviewError("annotation_invalid", "A persisted annotation is not bound to the immutable rubric.", status_code=409)
        return ReviewService._exact_dimension_scores(values, rubric, "persisted annotation")

    @staticmethod
    def _mean_score(scores: Mapping[str, float]) -> float:
        return sum(scores.values()) / len(scores)

    def _blind_payload_digest(self, project_id: str, item: AnnotationItem, request: AnnotationBatch) -> str:
        source = self.repository.review_attempt_evidence(project_id, item.attempt_id)
        if source is None:
            raise ReviewError("attempt_not_found", "The requested attempt is not in this project.", status_code=404)
        metadata = source.get("result_metadata")
        if not isinstance(metadata, Mapping):
            raise ReviewError("attempt_evidence_invalid", "Persisted attempt evidence metadata is invalid.", status_code=409)
        evaluation_id = source.get("evaluation_id")
        if not isinstance(evaluation_id, str):
            raise ReviewError("evaluation_missing", "A durable immutable evaluation is required before human review.", status_code=409)
        input_digest, output_digest, trace_digest = (
            metadata.get("input_artifact_digest"), metadata.get("output_artifact_digest"), metadata.get("trace_artifact_digest"),
        )
        if not all(isinstance(digest, str) and len(digest) == 64 for digest in (input_digest, output_digest, trace_digest)):
            raise ReviewError("attempt_evidence_invalid", "Persisted attempt input, output, and trace artifacts are required.", status_code=409)
        if (source.get("evaluation_input_artifact_digest"), source.get("evaluation_output_artifact_digest"), source.get("evaluation_trace_artifact_digest")) != (input_digest, output_digest, trace_digest):
            raise ReviewError("evaluation_artifact_mismatch", "The immutable evaluation does not bind this attempt's input, output, and trace evidence.", status_code=409)
        if (
            source.get("evaluator") != request.evaluator.evaluator_id
            or source.get("evaluator_version") != request.evaluator.version
            or source.get("evaluator_digest") != request.evaluator.digest
            or canonical_json(source.get("grader_plan")) != canonical_json(request.grader_plan.model_dump(mode="json"))
        ):
            raise ReviewError("evaluation_metadata_mismatch", "The submitted rubric and evaluator must exactly match the immutable evaluation.", status_code=409)
        result_digest, result_hash = source.get("result_artifact_digest"), source.get("result_hash")
        if not isinstance(result_digest, str) or not isinstance(result_hash, str):
            raise ReviewError("evaluation_incomplete", "The immutable evaluation lacks its result artifact binding.", status_code=409)
        result = self._read_registered_artifact(result_digest)
        if sha256_bytes(result) != result_hash or canonical_json(source.get("result")) != result:
            raise ReviewError("evaluation_artifact_mismatch", "The immutable evaluation result artifact cannot be reverified.", status_code=409)
        input_bytes = self._read_registered_artifact(input_digest)
        output_bytes = self._read_registered_artifact(output_digest)
        trace_bytes = self._read_registered_artifact(trace_digest)
        try:
            attempt_input = AttemptInput.model_validate_json(input_bytes)
            if canonical_json(attempt_input.model_dump(mode="json")) != input_bytes:
                raise ValueError("attempt input is not canonical")
            raw_trace = json.loads(trace_bytes)
            if not isinstance(raw_trace, list):
                raise TypeError("trace is not a list")
            trace = tuple(TraceEvent.model_validate_json(canonical_json(event)) for event in raw_trace)
            if canonical_json([event.model_dump(mode="json") for event in trace]) != trace_bytes:
                raise ValueError("trace is not canonical")
            if attempt_input.attempt.attempt_id != item.attempt_id or attempt_input.attempt.episode_id != source.get("episode_id"):
                raise ValueError("attempt input binding mismatch")
            if any(event.attempt_id != item.attempt_id or event.episode_id != source.get("episode_id") for event in trace):
                raise ValueError("trace binding mismatch")
            output = output_bytes.decode("utf-8")
        except (UnicodeDecodeError, ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReviewError("attempt_evidence_invalid", "Persisted attempt evidence cannot be reconstructed safely.", status_code=409) from exc
        if sha256_bytes(output_bytes) != output_digest:
            raise ReviewError("attempt_evidence_invalid", "Persisted output bytes do not match the immutable output digest.", status_code=409)
        blind_payload: dict[str, Any] = {
            "schema": "scaffold-arena.blinded-review.v1",
            "task": {"title": attempt_input.scenario.title, "prompt": attempt_input.scenario.prompt, "source_label": attempt_input.scenario.source_label},
            "output": output,
            "trace_summary": {
                "event_count": len(trace),
                "event_types": sorted({event.event_type for event in trace}),
            },
            "rubric": request.rubric.model_dump(mode="json"),
        }
        self._reject_blind_leaks(blind_payload)
        content = canonical_json(blind_payload)
        digest = self.artifact_store.put_bytes(
            content, media_type="application/vnd.scaffold-arena.blinded-review+json",
            metadata={"artifact_role": "blinded_review"},
        )
        persisted = self._read_artifact_bytes(digest)
        if persisted != content or sha256_bytes(persisted) != digest:
            raise ReviewError("blind_payload_invalid", "The blinded assignment payload cannot be durably re-read.", status_code=409)
        self.repository.register_artifact(
            digest, size_bytes=len(persisted), storage_uri=self.artifact_store.uri_for(digest),
            media_type="application/vnd.scaffold-arena.blinded-review+json",
            content_metadata={"artifact_role": "blinded_review"},
        )
        return digest

    def _read_registered_artifact(self, digest: str) -> bytes:
        with self.repository.engine.connect() as conn:
            found = conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none()
        if found is None:
            raise ReviewError("artifact_not_registered", "Every review artifact must already be durably registered.", status_code=409)
        return self._read_artifact_bytes(digest)

    def _read_artifact_bytes(self, digest: str) -> bytes:
        try:
            content = self.artifact_store.get_bytes(digest)
        except (ArtifactIntegrityError, OSError, ValueError) as exc:
            raise ReviewError("artifact_tampered", "Required review artifact cannot be read with its registered digest.", status_code=409) from exc
        if sha256_bytes(content) != digest:
            raise ReviewError("artifact_tampered", "Required review artifact bytes do not match their digest.", status_code=409)
        return content

    @staticmethod
    def _blind_assignment(row: Mapping[str, Any]) -> dict[str, Any]:
        return {"assignment_id": row["id"], "item_id": row["item_id"], "blind_payload_digest": row["blind_payload_digest"]}

    @staticmethod
    def _reject_blind_leaks(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if any(token in str(key).casefold() for token in _BLIND_FORBIDDEN):
                    raise ReviewError("blindness_leak", "Treatment, harness, factor, scaffold, adapter, and control-plane fields are forbidden.")
                ReviewService._reject_blind_leaks(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                ReviewService._reject_blind_leaks(child)
        elif isinstance(value, str):
            try:
                embedded = json.loads(value)
            except json.JSONDecodeError:
                return
            if isinstance(embedded, (Mapping, list, tuple)):
                ReviewService._reject_blind_leaks(embedded)

    @staticmethod
    def _reject_caller_evidence(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if any(token in str(key).casefold() for token in _CALLER_EVIDENCE_FORBIDDEN):
                    raise ReviewError("caller_evidence_forbidden", "Blind payloads and attempt artifact fields are derived only from durable project evidence.")
                ReviewService._reject_caller_evidence(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                ReviewService._reject_caller_evidence(child)
