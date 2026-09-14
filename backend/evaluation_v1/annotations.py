from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from protocol_v1.canonical import sha256

from .models import HumanCalibrationReceipt


@dataclass(frozen=True)
class BlindAssignment:
    assignment_id: str
    item_id: str
    annotator_pseudonym: str
    blind_payload_ref: str


@dataclass(frozen=True)
class Annotation:
    item_id: str
    annotator_pseudonym: str
    score: float


@dataclass(frozen=True)
class AdjudicationRecord:
    item_id: str
    adjudicator_pseudonym: str
    final_score: float
    decision: str
    rationale: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if (
            not self.item_id
            or not self.adjudicator_pseudonym
            or not self.decision
            or not self.rationale
            or not self.evidence_ref
        ):
            raise ValueError(
                "adjudication needs item, pseudonym, decision, rationale, and evidence reference"
            )
        if not 0.0 <= self.final_score <= 1.0:
            raise ValueError("adjudication final_score must be in [0, 1]")


@dataclass(frozen=True)
class AgreementSummary:
    item_id: str
    annotator_count: int
    score_range: float
    conflict: bool


@dataclass(frozen=True)
class AnnotationCompletion:
    summaries: tuple[AgreementSummary, ...]
    unresolved_conflicts: tuple[str, ...]
    receipt: HumanCalibrationReceipt | None
    protocol_complete: bool
    completion_digest: str


def assign_blindly(
    item_ids: Iterable[str],
    annotator_pseudonyms: Iterable[str],
    *,
    payload_refs: dict[str, str],
    seed: str,
) -> tuple[BlindAssignment, ...]:
    items, annotators = sorted(set(item_ids)), sorted(set(annotator_pseudonyms))
    if len(annotators) < 3:
        raise ValueError(
            "at least three independent pseudonymous annotators are required"
        )
    if any(not item or item not in payload_refs for item in items):
        raise ValueError("every selected item needs a blind payload reference")
    assignments = []
    for item in items:
        # The keyed digest creates repeatable, opaque rotation while exposing no treatment identity.
        ordered = sorted(
            annotators,
            key=lambda annotator: sha256(
                {"seed": seed, "item": item, "annotator": annotator}
            ),
        )
        for annotator in ordered:
            assignments.append(
                BlindAssignment(
                    sha256({"seed": seed, "item": item, "annotator": annotator})[:24],
                    item,
                    annotator,
                    payload_refs[item],
                )
            )
    return tuple(assignments)


def complete_annotations(
    assignments: Iterable[BlindAssignment],
    annotations: Iterable[Annotation],
    *,
    adjudications: Iterable[AdjudicationRecord] = (),
) -> AnnotationCompletion:
    assignments, annotations, adjudications = (
        tuple(assignments),
        tuple(annotations),
        tuple(adjudications),
    )
    expected = {
        (assignment.item_id, assignment.annotator_pseudonym)
        for assignment in assignments
    }
    if len(expected) != len(assignments):
        raise ValueError("duplicate annotator assignment is not independent")
    received = {
        (annotation.item_id, annotation.annotator_pseudonym): annotation
        for annotation in annotations
    }
    if not expected:
        raise ValueError("no assignments")
    if set(received) != expected:
        raise ValueError(
            "annotations must exactly cover blind assignments; no fake completion"
        )
    if len(received) != len(annotations):
        raise ValueError("duplicate annotations are not independent completion")
    if any(not 0.0 <= annotation.score <= 1.0 for annotation in received.values()):
        raise ValueError("annotation scores must be in [0, 1]")
    summaries = []
    conflicts = []
    for item in sorted({item for item, _ in expected}):
        scores = [
            annotation.score
            for (annotation_item, _), annotation in received.items()
            if annotation_item == item
        ]
        annotators = {
            annotator
            for annotation_item, annotator in expected
            if annotation_item == item
        }
        if len(annotators) < 3:
            raise ValueError("each selected item needs three independent annotators")
        score_range = max(scores) - min(scores)
        conflict = score_range > 0.20
        summaries.append(AgreementSummary(item, len(annotators), score_range, conflict))
        if conflict:
            conflicts.append(item)
    adjudication_by_item = {record.item_id: record for record in adjudications}
    if len(adjudication_by_item) != len(adjudications):
        raise ValueError("each conflicted item may have one explicit adjudication")
    conflict_set = set(conflicts)
    if adjudication_by_item and set(adjudication_by_item) != conflict_set:
        raise ValueError(
            "adjudications must exactly cover conflicts and cannot rubber-stamp non-conflicts"
        )
    protocol_complete = not conflicts or set(adjudication_by_item) == conflict_set
    completion_digest = sha256(
        {
            "assignments": [assignment.__dict__ for assignment in assignments],
            "annotations": [annotation.__dict__ for annotation in annotations],
            "adjudications": [record.__dict__ for record in adjudications],
            "protocol_complete": protocol_complete,
        }
    )
    unresolved = () if protocol_complete else tuple(conflicts)
    # Completion of a pseudonymous protocol is not authenticated human
    # calibration. A separate authority-bound workflow must mint the receipt.
    return AnnotationCompletion(tuple(summaries), unresolved, None, protocol_complete, completion_digest)
