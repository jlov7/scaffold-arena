"""Persistence-backed Trace Lab v1.1 diagnostics; never causal attribution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from analysis_v1.trace import (
    AnchorAlignment,
    NormalizedTraceEvent,
    SemanticAnchor,
    align_traces,
    first_meaningful_divergence,
    normalize_trace,
)
from analysis_v1.trace import TraceEvent as AnalysisTraceEvent
from persistence_v1 import ArenaRepository
from persistence_v1.schema import projects
from protocol_v1 import TraceEvent as PersistedTraceEvent
from protocol_v1.canonical import canonical_json, sha256


class TraceLabError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    left_attempt_id: str = Field(min_length=1, max_length=64)
    right_attempt_id: str = Field(min_length=1, max_length=64)
    diagnostic_partial_mode: bool = False
    declared_semantic_anchors: dict[str, SemanticAnchor] = Field(default_factory=dict)

    @field_validator("declared_semantic_anchors")
    @classmethod
    def _anchor_ids_are_bounded(
        cls, value: dict[str, SemanticAnchor]
    ) -> dict[str, SemanticAnchor]:
        if len(value) > 256 or any(
            not event_id or len(event_id) > 64 for event_id in value
        ):
            raise ValueError(
                "declared semantic anchors must use at most 256 bounded persisted event ids"
            )
        return value


_ANCHORS = {
    "request": SemanticAnchor.REQUEST,
    "response": SemanticAnchor.MODEL_RESPONSE,
    "tool_call": SemanticAnchor.TOOL_CALL,
    "tool_result": SemanticAnchor.TOOL_RESULT,
    "state": SemanticAnchor.STATE_CHANGE,
    "error": SemanticAnchor.ERROR,
}
_MAX_TRACE_EVENTS = 1_024
_CREDENTIAL_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer_token",
        "credential",
        "credentials",
        "password",
        "refresh_token",
        "secret",
        "access_token",
        "client_secret",
        "private_key",
    }
)


@dataclass(frozen=True)
class _LoadedTrace:
    attempt_id: str
    execution_id: str
    experiment_id: str
    events: tuple[PersistedTraceEvent, ...]
    stored_event_ids: tuple[str, ...]
    source_digest: str
    exclusions: tuple[str, ...]


class TraceLabService:
    """Compare two persisted protocol traces within one project and experiment."""

    def __init__(
        self, repository: ArenaRepository, *, personal_project_id: str | None = None
    ) -> None:
        self.repository = repository
        self.personal_project_id = personal_project_id

    def resolve_project(self, project_id: str | None) -> str:
        resolved = project_id or self.personal_project_id
        if not resolved:
            raise TraceLabError(
                "project_context_required", "An explicit project context is required."
            )
        with self.repository.engine.connect() as conn:
            exists = conn.execute(
                select(projects.c.id).where(projects.c.id == resolved)
            ).scalar_one_or_none()
        if exists is None:
            raise TraceLabError(
                "unknown_project", "The supplied project does not exist.", status_code=404
            )
        return resolved

    def analyze(
        self, payload: Mapping[str, Any], *, project_id: str | None
    ) -> dict[str, Any]:
        request = self._request(payload)
        project_id = self.resolve_project(project_id)
        if request.left_attempt_id == request.right_attempt_id:
            raise TraceLabError(
                "same_attempt", "Trace comparison requires two distinct attempts."
            )

        left = self._load(project_id, request.left_attempt_id)
        right = self._load(project_id, request.right_attempt_id)
        if left.experiment_id != right.experiment_id:
            raise TraceLabError(
                "cross_experiment_ambiguity",
                "Attempts must belong to one persisted experiment.",
                status_code=409,
            )
        if request.declared_semantic_anchors and not set(
            request.declared_semantic_anchors
        ).issubset(set(left.stored_event_ids) | set(right.stored_event_ids)):
            raise TraceLabError(
                "unknown_declared_anchor",
                "Declared semantic anchors must refer only to source event ids.",
            )

        exclusions = tuple(sorted(set(left.exclusions + right.exclusions)))
        if exclusions and not request.diagnostic_partial_mode:
            raise TraceLabError(
                "partial_trace_hold",
                "Trace completeness is insufficient; set diagnostic_partial_mode=true for a diagnostic-only comparison.",
                status_code=409,
            )

        left_normalized = normalize_trace(
            self._analysis_events(
                left.events,
                left.stored_event_ids,
                request.declared_semantic_anchors,
            )
        )
        right_normalized = normalize_trace(
            self._analysis_events(
                right.events,
                right.stored_event_ids,
                request.declared_semantic_anchors,
            )
        )
        alignment = align_traces(left_normalized, right_normalized)
        divergence = first_meaningful_divergence(left_normalized, right_normalized)
        divergence_position = self._divergence_position(
            alignment.alignments,
            divergence.left_ordinal,
            divergence.right_ordinal,
            found=divergence.found,
        )
        sorted_left = tuple(sorted(left.events, key=lambda event: event.sequence))
        sorted_right = tuple(sorted(right.events, key=lambda event: event.sequence))
        state = self._state_context(
            sorted_left,
            sorted_right,
            alignment.alignments,
            divergence_position,
        )
        rows = self._alignment_rows(
            alignment.alignments, left_normalized, right_normalized
        )
        source_digest = sha256(
            {
                "analysis_version": "trace-lab-v1.1",
                "left": left.source_digest,
                "right": right.source_digest,
                "declared_semantic_anchors": {
                    key: value.value
                    for key, value in sorted(
                        request.declared_semantic_anchors.items()
                    )
                },
            }
        )
        response = {
            "analysis_version": "trace-lab-v1.1",
            "project_id": project_id,
            "experiment_id": left.experiment_id,
            "mode": (
                "DIAGNOSTIC_PARTIAL"
                if exclusions
                else "COMPLETE_TRACE_DIAGNOSTIC"
            ),
            "causal_label": "DIAGNOSTIC_ONLY",
            "claim_ceiling": "observed persisted-trace diagnostic only; no causal attribution, outcome reconstruction, or missing-event reconstruction",
            "attempt_links": {
                "left": self._attempt_link(left.attempt_id),
                "right": self._attempt_link(right.attempt_id),
            },
            "source_event_ids": {
                "left": list(left.stored_event_ids),
                "right": list(right.stored_event_ids),
            },
            "alignment": {
                "source_digest": source_digest,
                "source_digests": {
                    "left": left.source_digest,
                    "right": right.source_digest,
                },
                "matched_anchors": alignment.matched_anchors,
                "exact_observation_matches": alignment.exact_observation_matches,
                "content_differences": alignment.content_differences,
                "left_only": alignment.left_only,
                "right_only": alignment.right_only,
                "clock_skew_tolerant": alignment.clock_skew_tolerant,
                "rows": rows,
            },
            "first_meaningful_divergence": {
                "found": divergence.found,
                "label": "DIAGNOSTIC_ONLY",
                "reason": divergence.reason,
                "confidence": divergence.confidence,
                "alignment_position": divergence_position,
                "left_event_id": self._normalized_event_id(
                    left_normalized, divergence.left_ordinal
                ),
                "right_event_id": self._normalized_event_id(
                    right_normalized, divergence.right_ordinal
                ),
                "evidence_refs": list(divergence.evidence_refs),
                "state_before": state["before"],
                "state_after": state["after"],
                "state_ref_diff": state["diff"],
            },
            "coverage": {
                "numerator": alignment.matched_anchors,
                "denominator": max(len(left_normalized), len(right_normalized)),
                "exclusions": list(exclusions),
            },
        }
        return {**response, "analysis_digest": sha256(response)}

    @staticmethod
    def _request(payload: Mapping[str, Any]) -> _Request:
        try:
            return _Request.model_validate_json(canonical_json(dict(payload)))
        except (TypeError, ValueError, ValidationError) as exc:
            raise TraceLabError(
                "invalid_trace_analysis_request",
                "Use only left_attempt_id, right_attempt_id, diagnostic_partial_mode, and declared_semantic_anchors; raw events, payloads, and outcomes are forbidden.",
            ) from exc

    def _load(self, project_id: str, attempt_id: str) -> _LoadedTrace:
        source = self.repository.attempt_evaluation_source(project_id, attempt_id)
        if source is None:
            raise TraceLabError(
                "attempt_not_in_project",
                "Each attempt must already exist in the selected project.",
                status_code=404,
            )
        execution_id = str(source["execution_id"])
        binding = self.repository.get_execution_evidence_binding(
            project_id, execution_id
        )
        if binding is None:
            raise TraceLabError(
                "attempt_execution_ambiguity",
                "The persisted attempt execution is not project-scoped.",
                status_code=409,
            )
        rows = self.repository.list_attempt_events(attempt_id)
        trace_rows = [row for row in rows if row.get("event_type") == "trace"]
        if len(trace_rows) > _MAX_TRACE_EVENTS:
            raise TraceLabError(
                "trace_too_large",
                f"Trace Lab accepts at most {_MAX_TRACE_EVENTS} persisted events per attempt before quadratic alignment.",
                status_code=409,
            )
        exclusions: list[str] = []
        if source.get("status") != "completed":
            exclusions.append(f"{attempt_id}:attempt_status_{source.get('status')}")
        result_metadata = source.get("result_metadata")
        if (
            not isinstance(result_metadata, Mapping)
            or result_metadata.get("trace_complete") is not True
        ):
            exclusions.append(f"{attempt_id}:trace_completeness_unverified")
        if not trace_rows:
            raise TraceLabError(
                "trace_unavailable",
                "Each attempt requires persisted trace events; missing traces cannot be reconstructed.",
                status_code=409,
            )

        events: list[PersistedTraceEvent] = []
        stored_event_ids: list[str] = []
        for row in trace_rows:
            try:
                event = PersistedTraceEvent.model_validate_json(
                    canonical_json(row.get("payload"))
                )
            except ValidationError as exc:
                raise TraceLabError(
                    "invalid_persisted_trace",
                    "Persisted trace events must satisfy the protocol trace contract.",
                    status_code=409,
                ) from exc
            if event.attempt_id != attempt_id:
                raise TraceLabError(
                    "invalid_persisted_trace",
                    "Persisted trace event attempt binding is invalid.",
                    status_code=409,
                )
            events.append(event)
            stored_event_ids.append(str(row["id"]))
        sequences = [event.sequence for event in events]
        if len(set(sequences)) != len(sequences):
            raise TraceLabError(
                "ambiguous_trace_sequence",
                "Duplicate persisted trace sequences cannot be deterministically diagnosed.",
                status_code=409,
            )
        if sorted(sequences) != list(range(len(sequences))):
            exclusions.append(f"{attempt_id}:trace_sequence_gap")
        if sequences != sorted(sequences):
            exclusions.append(f"{attempt_id}:persisted_trace_order_reordered")
        event_tuple = tuple(events)
        event_id_tuple = tuple(stored_event_ids)
        return _LoadedTrace(
            attempt_id=attempt_id,
            execution_id=execution_id,
            experiment_id=str(binding["experiment_id"]),
            events=event_tuple,
            stored_event_ids=event_id_tuple,
            source_digest=self._trace_source_digest(event_tuple, event_id_tuple),
            exclusions=tuple(exclusions),
        )

    @staticmethod
    def _trace_source_digest(
        events: Sequence[PersistedTraceEvent], stored_event_ids: Sequence[str]
    ) -> str:
        return sha256(
            [
                {
                    "persisted_event_id": event_id,
                    "event": event.model_dump(mode="json", exclude={"payload"}),
                }
                for event, event_id in zip(events, stored_event_ids, strict=True)
            ]
        )

    @staticmethod
    def _analysis_events(
        events: Sequence[PersistedTraceEvent],
        stored_event_ids: Sequence[str],
        declared: Mapping[str, SemanticAnchor],
    ) -> tuple[AnalysisTraceEvent, ...]:
        return tuple(
            AnalysisTraceEvent(
                event_id=stored_event_id,
                anchor=declared.get(
                    stored_event_id, _ANCHORS[event.event_type]
                ),
                sequence=event.sequence,
                timestamp=event.timestamp,
                monotonic_ms=event.monotonic_time * 1_000,
                evidence_ref=TraceLabService._evidence_ref(event),
                observation_digest=event.payload_hash,
            )
            for event, stored_event_id in zip(
                events, stored_event_ids, strict=True
            )
        )

    @staticmethod
    def _evidence_ref(event: PersistedTraceEvent) -> str | None:
        if event.state_ref is not None:
            return (
                f"state:{event.state_ref.state_id}:"
                f"{event.state_ref.snapshot_hash}"
            )
        return None

    @staticmethod
    def _attempt_link(attempt_id: str) -> dict[str, str]:
        return {
            "attempt_id": attempt_id,
            "trace_url": f"/api/v1/attempts/{attempt_id}/trace",
        }

    @staticmethod
    def _normalized_event_id(
        events: Sequence[Any], ordinal: int | None
    ) -> str | None:
        return events[ordinal].event_id if ordinal is not None else None

    @staticmethod
    def _alignment_event(
        events: Sequence[NormalizedTraceEvent], ordinal: int | None
    ) -> dict[str, Any] | None:
        if ordinal is None:
            return None
        event = events[ordinal]
        return {
            "event_id": event.event_id,
            "ordinal": event.ordinal,
            "observation_digest": event.observation_digest,
            "relative_ms": event.relative_ms,
            "evidence_ref": event.evidence_ref,
        }

    @classmethod
    def _alignment_rows(
        cls,
        alignments: Sequence[AnchorAlignment],
        left: Sequence[NormalizedTraceEvent],
        right: Sequence[NormalizedTraceEvent],
    ) -> list[dict[str, Any]]:
        return [
            {
                "position": position,
                "status": row.status,
                "anchor": row.anchor.value,
                "left": cls._alignment_event(left, row.left_ordinal),
                "right": cls._alignment_event(right, row.right_ordinal),
            }
            for position, row in enumerate(alignments)
        ]

    @staticmethod
    def _divergence_position(
        alignments: Sequence[AnchorAlignment],
        left_ordinal: int | None,
        right_ordinal: int | None,
        *,
        found: bool,
    ) -> int | None:
        if not found:
            return None
        for position, row in enumerate(alignments):
            if (
                row.status != "MATCH"
                and row.left_ordinal == left_ordinal
                and row.right_ordinal == right_ordinal
            ):
                return position
        raise TraceLabError(
            "alignment_inconsistent",
            "The first divergence is not represented by the deterministic alignment.",
            status_code=409,
        )

    @classmethod
    def _state_context(
        cls,
        left: Sequence[PersistedTraceEvent],
        right: Sequence[PersistedTraceEvent],
        alignments: Sequence[AnchorAlignment],
        position: int | None,
    ) -> dict[str, Any]:
        if position is None:
            before = {"left": None, "right": None}
            after = {"left": None, "right": None}
        else:
            before = {
                "left": cls._observed_state_ref(
                    left,
                    cls._context_ordinal(
                        alignments, position, side="left", before=True
                    ),
                    before=True,
                ),
                "right": cls._observed_state_ref(
                    right,
                    cls._context_ordinal(
                        alignments, position, side="right", before=True
                    ),
                    before=True,
                ),
            }
            after = {
                "left": cls._observed_state_ref(
                    left,
                    cls._context_ordinal(
                        alignments, position, side="left", before=False
                    ),
                    before=False,
                ),
                "right": cls._observed_state_ref(
                    right,
                    cls._context_ordinal(
                        alignments, position, side="right", before=False
                    ),
                    before=False,
                ),
            }
        return {
            "before": before,
            "after": after,
            "diff": cls._state_diff(before, after),
        }

    @staticmethod
    def _context_ordinal(
        alignments: Sequence[AnchorAlignment],
        position: int,
        *,
        side: str,
        before: bool,
    ) -> int | None:
        attribute = "left_ordinal" if side == "left" else "right_ordinal"
        current = getattr(alignments[position], attribute)
        if current is not None:
            return int(current)
        if before:
            for row in reversed(alignments[:position]):
                ordinal = getattr(row, attribute)
                if ordinal is not None:
                    # _observed_state_ref(before=True) excludes its pivot. Add
                    # one so the nearest observed event is included as context.
                    return int(ordinal) + 1
            return 0
        for row in alignments[position + 1 :]:
            ordinal = getattr(row, attribute)
            if ordinal is not None:
                return int(ordinal)
        return None

    @classmethod
    def _observed_state_ref(
        cls,
        events: Sequence[PersistedTraceEvent],
        ordinal: int | None,
        *,
        before: bool,
    ) -> dict[str, str] | None:
        if ordinal is None:
            return None
        indices = (
            range(min(ordinal - 1, len(events) - 1), -1, -1)
            if before
            else range(ordinal, len(events))
        )
        for index in indices:
            event = events[index]
            if event.state_ref is not None:
                return cls._redact(event.state_ref.model_dump(mode="json"))
            candidate = (
                event.payload.get("state_ref")
                if isinstance(event.payload, Mapping)
                else None
            )
            if isinstance(candidate, Mapping):
                safe = {
                    key: value
                    for key, value in candidate.items()
                    if key in {"state_id", "snapshot_hash"}
                }
                if safe:
                    return cls._redact(safe)
        return None

    @staticmethod
    def _state_diff(
        before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            side: {
                key: {
                    "before": before[side].get(key) if before[side] else None,
                    "after": after[side].get(key) if after[side] else None,
                }
                for key in ("state_id", "snapshot_hash")
                if (before[side] or {}).get(key)
                != (after[side] or {}).get(key)
            }
            for side in ("left", "right")
        }

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): (
                    "[REDACTED]"
                    if cls._is_credential_key(str(key))
                    else cls._redact(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [cls._redact(item) for item in value]
        return value

    @staticmethod
    def _is_credential_key(key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        return normalized in _CREDENTIAL_KEYS or normalized.endswith(
            ("_secret", "_password")
        )
