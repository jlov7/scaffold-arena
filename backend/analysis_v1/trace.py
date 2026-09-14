"""Trace normalization, semantic alignment, and diagnostic divergence analysis.

The alignment layer is deliberately content-aware but epistemically narrow:
matching payload hashes show that the persisted observations were byte-identical,
not that either event was correct.  Divergence remains diagnostic unless a
separate preregistered counterfactual design satisfies every causal gate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class SemanticAnchor(StrEnum):
    START = "start"
    REQUEST = "request"
    MODEL_RESPONSE = "model_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATE_CHANGE = "state_change"
    CHECKPOINT = "checkpoint"
    RETRY = "retry"
    FINAL = "final"
    ERROR = "error"


_DIGEST = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    anchor: SemanticAnchor
    sequence: int
    timestamp: datetime | None = None
    monotonic_ms: float | None = None
    evidence_ref: str | None = None
    observation_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if self.timestamp is not None and (
            self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None
        ):
            raise ValueError("timestamp must be timezone-aware when supplied")
        if self.monotonic_ms is not None and self.monotonic_ms < 0:
            raise ValueError("monotonic_ms cannot be negative")
        if self.evidence_ref is not None and not self.evidence_ref:
            raise ValueError("evidence_ref must be non-empty when supplied")
        if self.observation_digest is not None and _DIGEST.fullmatch(self.observation_digest) is None:
            raise ValueError("observation_digest must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class NormalizedTraceEvent:
    event_id: str
    anchor: SemanticAnchor
    ordinal: int
    relative_ms: float | None
    evidence_ref: str | None
    observation_digest: str | None = None


AlignmentStatus = Literal[
    "MATCH",
    "CONTENT_DIFFERENCE",
    "LEFT_ONLY",
    "RIGHT_ONLY",
]


@dataclass(frozen=True)
class AnchorAlignment:
    left_ordinal: int | None
    right_ordinal: int | None
    anchor: SemanticAnchor
    status: AlignmentStatus


@dataclass(frozen=True)
class AlignmentResult:
    alignments: tuple[AnchorAlignment, ...]
    matched_anchors: int
    left_only: int
    right_only: int
    clock_skew_tolerant: bool
    content_differences: int = 0
    exact_observation_matches: int = 0


@dataclass(frozen=True)
class DivergenceResult:
    found: bool
    left_ordinal: int | None
    right_ordinal: int | None
    confidence: float | None
    reason: str
    evidence_refs: tuple[str, ...]
    diagnostic_only: bool
    causal_label: str


def normalize_trace(events: Sequence[TraceEvent]) -> tuple[NormalizedTraceEvent, ...]:
    """Order by the durable sequence and express time relative to the first event.

    Wall-clock and monotonic timestamps are orientation aids only. Alignment
    never depends on absolute clock equality, so cross-host clock skew cannot
    manufacture a semantic divergence.
    """

    if not events:
        return ()
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("event_id values must be unique within a trace")
    ordered = tuple(sorted(events, key=lambda item: (item.sequence, item.event_id)))
    if len({event.sequence for event in ordered}) != len(ordered):
        raise ValueError("trace sequence values must be unique")
    monotonic_origin = next(
        (item.monotonic_ms for item in ordered if item.monotonic_ms is not None),
        None,
    )
    wall_origin = next(
        (item.timestamp for item in ordered if item.timestamp is not None),
        None,
    )
    normalized: list[NormalizedTraceEvent] = []
    for ordinal, item in enumerate(ordered):
        if item.monotonic_ms is not None and monotonic_origin is not None:
            relative = item.monotonic_ms - monotonic_origin
        elif item.timestamp is not None and wall_origin is not None:
            relative = (item.timestamp - wall_origin).total_seconds() * 1_000
        else:
            relative = None
        normalized.append(
            NormalizedTraceEvent(
                event_id=item.event_id,
                anchor=item.anchor,
                ordinal=ordinal,
                relative_ms=relative,
                evidence_ref=item.evidence_ref,
                observation_digest=item.observation_digest,
            )
        )
    return tuple(normalized)


_GAP_SCORE = -2
_EXACT_OBSERVATION_SCORE = 8
_ANCHOR_ONLY_SCORE = 4
_CONTENT_DIFFERENCE_SCORE = 1
_NEGATIVE_INFINITY = -(10**9)
_DIAGONAL = 1
_UP = 2
_LEFT = 3


def _diagonal_score(left: NormalizedTraceEvent, right: NormalizedTraceEvent) -> int:
    if left.anchor != right.anchor:
        return _NEGATIVE_INFINITY
    if left.observation_digest is None or right.observation_digest is None:
        return _ANCHOR_ONLY_SCORE
    if left.observation_digest == right.observation_digest:
        return _EXACT_OBSERVATION_SCORE
    return _CONTENT_DIFFERENCE_SCORE


def _aligned_status(
    left: NormalizedTraceEvent, right: NormalizedTraceEvent
) -> AlignmentStatus:
    if (
        left.observation_digest is not None
        and right.observation_digest is not None
        and left.observation_digest != right.observation_digest
    ):
        return "CONTENT_DIFFERENCE"
    return "MATCH"


def align_traces(
    left: Sequence[NormalizedTraceEvent], right: Sequence[NormalizedTraceEvent]
) -> AlignmentResult:
    """Globally align traces using anchors and observed content digests.

    The dynamic program keeps only two score rows. A one-byte traceback cell
    is retained for each pair so the exact deterministic alignment can be
    reconstructed without the unbounded Python-object matrix used previously.
    Callers handling untrusted traces must still impose their own event-count
    admission bound before invoking this quadratic operation.
    """

    n, m = len(left), len(right)
    width = m + 1
    traceback = bytearray((n + 1) * width)
    previous = [index * _GAP_SCORE for index in range(width)]
    for column in range(1, width):
        traceback[column] = _LEFT

    for row in range(1, n + 1):
        current = [row * _GAP_SCORE] + [0] * m
        traceback[row * width] = _UP
        left_event = left[row - 1]
        for column in range(1, width):
            right_event = right[column - 1]
            diagonal_component = _diagonal_score(left_event, right_event)
            diagonal = (
                previous[column - 1] + diagonal_component
                if diagonal_component != _NEGATIVE_INFINITY
                else _NEGATIVE_INFINITY
            )
            up = previous[column] + _GAP_SCORE
            across = current[column - 1] + _GAP_SCORE

            # Deterministic tie order: a semantic diagonal, then a left-trace
            # event, then a right-trace event. Exact digest matches carry a
            # substantially larger score, so repeated anchors align to the
            # observed content rather than the first positional occurrence.
            best = max(diagonal, up, across)
            if diagonal == best:
                direction = _DIAGONAL
            elif up == best:
                direction = _UP
            else:
                direction = _LEFT
            current[column] = best
            traceback[row * width + column] = direction
        previous = current

    rows: list[AnchorAlignment] = []
    row, column = n, m
    while row or column:
        direction = traceback[row * width + column]
        if row and column and direction == _DIAGONAL:
            left_event = left[row - 1]
            right_event = right[column - 1]
            if left_event.anchor != right_event.anchor:
                raise RuntimeError("traceback attempted an invalid cross-anchor diagonal")
            rows.append(
                AnchorAlignment(
                    left_ordinal=row - 1,
                    right_ordinal=column - 1,
                    anchor=left_event.anchor,
                    status=_aligned_status(left_event, right_event),
                )
            )
            row -= 1
            column -= 1
        elif row and (direction == _UP or column == 0):
            event = left[row - 1]
            rows.append(
                AnchorAlignment(row - 1, None, event.anchor, "LEFT_ONLY")
            )
            row -= 1
        elif column and (direction == _LEFT or row == 0):
            event = right[column - 1]
            rows.append(
                AnchorAlignment(None, column - 1, event.anchor, "RIGHT_ONLY")
            )
            column -= 1
        else:
            raise RuntimeError("traceback contains an invalid alignment direction")
    rows.reverse()
    alignments = tuple(rows)
    content_differences = sum(
        item.status == "CONTENT_DIFFERENCE" for item in alignments
    )
    exact_observation_matches = sum(
        item.status == "MATCH"
        and item.left_ordinal is not None
        and item.right_ordinal is not None
        and left[item.left_ordinal].observation_digest is not None
        and left[item.left_ordinal].observation_digest
        == right[item.right_ordinal].observation_digest
        for item in alignments
    )
    return AlignmentResult(
        alignments=alignments,
        matched_anchors=sum(
            item.status in {"MATCH", "CONTENT_DIFFERENCE"}
            for item in alignments
        ),
        left_only=sum(item.status == "LEFT_ONLY" for item in alignments),
        right_only=sum(item.status == "RIGHT_ONLY" for item in alignments),
        clock_skew_tolerant=True,
        content_differences=content_differences,
        exact_observation_matches=exact_observation_matches,
    )


_NON_MEANINGFUL = {SemanticAnchor.START, SemanticAnchor.REQUEST}


def _row_events(
    row: AnchorAlignment,
    left: Sequence[NormalizedTraceEvent],
    right: Sequence[NormalizedTraceEvent],
) -> tuple[NormalizedTraceEvent | None, NormalizedTraceEvent | None]:
    return (
        left[row.left_ordinal] if row.left_ordinal is not None else None,
        right[row.right_ordinal] if row.right_ordinal is not None else None,
    )


def _nearest_evidence_ref(
    alignments: Sequence[AnchorAlignment],
    position: int,
    *,
    side: Literal["left", "right"],
    events: Sequence[NormalizedTraceEvent],
) -> str | None:
    attribute = "left_ordinal" if side == "left" else "right_ordinal"
    for distance in range(1, len(alignments) + 1):
        # Prefer the following aligned event at equal distance. For insertions
        # this is the event the other trace proceeds to after the extra row.
        for candidate_position in (position + distance, position - distance):
            if candidate_position < 0 or candidate_position >= len(alignments):
                continue
            ordinal = getattr(alignments[candidate_position], attribute)
            if ordinal is None:
                continue
            reference = events[ordinal].evidence_ref
            if reference is not None:
                return reference
    return None


def _contextual_evidence_refs(
    alignments: Sequence[AnchorAlignment],
    position: int,
    left: Sequence[NormalizedTraceEvent],
    right: Sequence[NormalizedTraceEvent],
    left_event: NormalizedTraceEvent | None,
    right_event: NormalizedTraceEvent | None,
) -> tuple[str, ...]:
    left_ref = (
        left_event.evidence_ref
        if left_event is not None and left_event.evidence_ref is not None
        else _nearest_evidence_ref(
            alignments, position, side="left", events=left
        )
    )
    right_ref = (
        right_event.evidence_ref
        if right_event is not None and right_event.evidence_ref is not None
        else _nearest_evidence_ref(
            alignments, position, side="right", events=right
        )
    )
    ordered: list[str] = []
    for value in (left_ref, right_ref):
        if value is not None and value not in ordered:
            ordered.append(value)
    return tuple(ordered)


def _divergence_reason(row: AnchorAlignment) -> tuple[str, float]:
    if row.status == "CONTENT_DIFFERENCE":
        return (
            f"{row.anchor.value} observation digests differ at the same semantic anchor",
            0.95,
        )
    side = "left" if row.status == "LEFT_ONLY" else "right"
    return (f"{side} trace contains an unmatched {row.anchor.value} anchor", 0.85)


def first_meaningful_divergence(
    left: Sequence[NormalizedTraceEvent],
    right: Sequence[NormalizedTraceEvent],
    *,
    preregistered_intervention: bool = False,
    counterfactual_replication: bool = False,
    manipulation_fidelity_pass: bool = False,
    comparison_invariants_pass: bool = False,
) -> DivergenceResult:
    """Return the first observed aligned divergence without inventing cause.

    A content difference at the same anchor is meaningful even for a request,
    because the persisted observation itself differs. Unmatched START/REQUEST
    scaffolding remains ignorable so harmless trace preambles do not become the
    headline diagnostic. `comparison_invariants_pass` is retained only for
    compatibility with frozen callers: it is not a derived persisted cross-arm
    evidence check and cannot promote a divergence. For a one-sided row,
    evidence references include the
    nearest observed event on the absent side so the diagnostic remains
    bilaterally inspectable without pretending that the events were aligned.
    """

    alignment = align_traces(left, right)
    for position, row in enumerate(alignment.alignments):
        if row.status == "MATCH":
            continue
        if row.status != "CONTENT_DIFFERENCE" and row.anchor in _NON_MEANINGFUL:
            continue
        left_event, right_event = _row_events(row, left, right)
        refs = _contextual_evidence_refs(
            alignment.alignments,
            position,
            left,
            right,
            left_event,
            right_event,
        )
        reason, confidence = _divergence_reason(row)
        derived_comparison_invariants_available = False
        causal_candidate = all(
            (
                preregistered_intervention,
                counterfactual_replication,
                manipulation_fidelity_pass,
                derived_comparison_invariants_available,
                bool(refs),
            )
        )
        return DivergenceResult(
            found=True,
            left_ordinal=row.left_ordinal,
            right_ordinal=row.right_ordinal,
            confidence=confidence,
            reason=reason,
            evidence_refs=refs,
            diagnostic_only=not causal_candidate,
            causal_label=(
                "COUNTERFACTUAL_SUPPORTED_CANDIDATE"
                if causal_candidate
                else "DIAGNOSTIC_ONLY"
            ),
        )

    return DivergenceResult(
        found=False,
        left_ordinal=None,
        right_ordinal=None,
        confidence=None,
        reason="no meaningful aligned divergence observed",
        evidence_refs=(),
        diagnostic_only=True,
        causal_label="DIAGNOSTIC_ONLY",
    )
