"""Read persisted attempt events without reconstructing, executing, or guessing."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from itertools import pairwise
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select

from artifacts_v1 import ArtifactIntegrityError, ArtifactStore
from observatory_v1 import ObservatoryReport, ObservatoryRequest
from persistence_v1 import ArenaRepository
from persistence_v1.schema import (
    artifacts,
    attempt_events,
    attempts,
    episodes,
    executions,
    experiments,
    observatory_analyses,
    observatory_reports,
    projects,
    xray_analyses,
)

_CEILING = "persisted-event observation only; no missing-event reconstruction, causal attribution, performance claim, or security assurance"
_LADDER = ("declared", "assigned", "available", "triggered", "applied", "activated", "observed", "downstream_pathway_detected")
_CONTEXT_METRICS = (
    "useful_context_density", "irrelevant_token_ratio", "stale_context_rate", "instruction_survival",
    "source_coverage", "compression_loss", "contradiction_exposure", "retrieval_precision",
    "retrieval_recall", "context_window_utilization", "context_cost_per_success",
)
_MEMORY_METRICS = (
    "write_precision", "retrieval_precision", "retrieval_recall", "stale_memory_rate",
    "contradiction_resolution", "write_amplification", "negative_transfer", "cross_task_interference",
    "privacy_leakage", "forgetting_correctness", "marginal_contribution", "cost_per_useful_retrieval",
)
_LOOP_CHECKS = (
    "repeated_state_loops", "oscillation", "redundant_tools", "verification_without_correction",
    "retries_with_unchanged_inputs", "context_growth_without_progress", "premature_stopping",
    "missing_stopping_conditions", "deadlock_livelock", "unbounded_delegation", "recovery_worsens_state",
)
_GRAPH_CHECKS = (
    "critical_path", "fan_in_fan_out", "coordination_overhead", "duplicated_messages",
    "state_bottlenecks", "failure_propagation", "authority_concentration", "unused_nodes", "cycles",
    "unreachable_transitions", "expensive_low_value_branches",
)
_MAX_EVENTS_PER_ATTEMPT = 2_048
_MAX_EVENTS_PER_ANALYSIS = 10_000
_MAX_ANALYSIS_REPORT_BYTES = 2_000_000


class ObservatoryError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _id() -> str:
    return f"x{uuid.uuid4().hex}"


class ObservatoryService:
    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def _project(self, project_id: str | None) -> str:
        project = project_id or self.personal_project_id
        if not project:
            raise ObservatoryError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            exists = conn.execute(select(projects.c.id).where(projects.c.id == project)).scalar_one_or_none()
        if exists is None:
            raise ObservatoryError("unknown_project", "The supplied project does not exist.", status_code=404)
        return project

    def ledger(self, attempt_id: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        attempt, events = self._load(project, attempt_id)
        ledger = self._ledger(attempt, events)
        return {"attempt_id": attempt_id, "ledger": ledger, "fidelity_ladder": list(_LADDER), "claim_ceiling": _CEILING}

    def capture(self, attempt_id: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        attempt, events = self._load(project, attempt_id)
        ledger = self._ledger(attempt, events)
        raw = json.dumps(ledger, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        digest = self.artifact_store.put_bytes(raw, media_type="application/vnd.scaffold-arena.observatory-ledger+json", metadata={"kind": "observatory-ledger"})
        with self.repository.transaction(immediate=True) as conn:
            existing = conn.execute(select(observatory_reports).where(observatory_reports.c.project_id == project, observatory_reports.c.attempt_id == attempt_id, observatory_reports.c.ledger_digest == digest)).mappings().one_or_none()
            if existing is not None:
                return self._report(existing, idempotent_replay=True)
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=digest, size_bytes=len(raw), storage_uri=self.artifact_store.uri_for(digest), media_type="application/vnd.scaffold-arena.observatory-ledger+json", metadata_json={"kind": "observatory-ledger"}))
            report_id = _id()
            conn.execute(insert(observatory_reports).values(id=report_id, project_id=project, attempt_id=attempt_id, ledger_digest=digest, fidelity_level=ledger["fidelity_level"], claim_ceiling=_CEILING))
        return {**self.ledger(attempt_id, project_id=project), "report_id": report_id, "ledger_digest": f"sha256:{digest}", "idempotent_replay": False}

    def create_report(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        try:
            request = ObservatoryRequest.model_validate(payload)
        except (TypeError, ValidationError, ValueError) as exc:
            raise ObservatoryError("observatory_request_invalid", "A strict ObservatoryRequest with named persisted attempts is required.") from exc
        xray_analysis_digest: str | None = None
        if request.xray_analysis_digest is not None:
            xray_digest = _bare_digest(request.xray_analysis_digest)
            with self.repository.engine.connect() as conn:
                exists = conn.execute(select(xray_analyses.c.analysis_digest).where(xray_analyses.c.analysis_digest == xray_digest, xray_analyses.c.project_id == project)).scalar_one_or_none()
            if exists is None:
                raise ObservatoryError("xray_report_not_found", "The named X-Ray report is not available in this project.", status_code=404)
            xray_analysis_digest = f"sha256:{xray_digest}"
        source_artifact_digest: str | None = None
        if request.source_artifact_digest is not None:
            source_artifact_digest = _bare_digest(request.source_artifact_digest)
            with self.repository.engine.connect() as conn:
                source_exists = conn.execute(
                    select(artifacts.c.digest).where(
                        artifacts.c.digest == source_artifact_digest
                    )
                ).scalar_one_or_none()
            if source_exists is None:
                raise ObservatoryError(
                    "observatory_source_not_found",
                    "The named source artifact is not available for a custody link.",
                    status_code=404,
                )
        ledgers = [self.ledger(attempt_id, project_id=project)["ledger"] for attempt_id in request.attempt_ids]
        if sum(len(ledger["events"]) for ledger in ledgers) > _MAX_EVENTS_PER_ANALYSIS:
            raise ObservatoryError(
                "observatory_analysis_too_large",
                "The named persisted evidence exceeds the Observatory analysis bound.",
                status_code=409,
            )
        report = self._analysis(
            ledgers,
            xray_analysis_digest=xray_analysis_digest,
            source_artifact_digest=(
                f"sha256:{source_artifact_digest}"
                if source_artifact_digest
                else None
            ),
        )
        raw = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(raw) > _MAX_ANALYSIS_REPORT_BYTES:
            raise ObservatoryError(
                "observatory_report_too_large",
                "The bounded Observatory projection would exceed its report size limit.",
                status_code=409,
            )
        digest = hashlib.sha256(raw).hexdigest()
        artifact_digest = self.artifact_store.put_bytes(raw, media_type="application/vnd.scaffold-arena.observatory-report+json", metadata={"kind": "observatory-report", "attempt_count": len(ledgers)})
        if artifact_digest != digest:
            raise ObservatoryError("observatory_artifact_integrity", "The observatory report could not be stored content-addressably.", status_code=500)
        with self.repository.transaction(immediate=True) as conn:
            existing = conn.execute(select(observatory_analyses).where(observatory_analyses.c.analysis_digest == digest, observatory_analyses.c.project_id == project)).mappings().one_or_none()
            if existing is not None:
                return self._load_analysis(digest, project=project, idempotent_replay=True)
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == artifact_digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=artifact_digest, size_bytes=len(raw), storage_uri=self.artifact_store.uri_for(artifact_digest), media_type="application/vnd.scaffold-arena.observatory-report+json", metadata_json={"kind": "observatory-report"}))
            conn.execute(insert(observatory_analyses).values(analysis_digest=digest, project_id=project, report_artifact_digest=artifact_digest, claim_ceiling=_CEILING))
        return self._public_analysis(report, digest=digest, idempotent_replay=False)

    def analysis(self, report_digest: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        return self._load_analysis(_bare_digest(report_digest), project=project, idempotent_replay=False)

    def report(self, report_id: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(observatory_reports).where(observatory_reports.c.project_id == project, observatory_reports.c.id == report_id)).mappings().one_or_none()
        if row is None:
            raise ObservatoryError("observatory_report_not_found", "The requested observatory report was not found.", status_code=404)
        try:
            ledger = json.loads(self.artifact_store.get_bytes(row["ledger_digest"]))
        except (ArtifactIntegrityError, OSError, TypeError, ValueError) as exc:
            raise ObservatoryError("observatory_custody_unavailable", "The persisted observatory ledger cannot be verified.", status_code=409) from exc
        return {"report_id": row["id"], "attempt_id": row["attempt_id"], "ledger_digest": f"sha256:{row['ledger_digest']}", "ledger": ledger, "fidelity_ladder": list(_LADDER), "claim_ceiling": _CEILING, "artifact_integrity_verified": True}

    def _load(self, project: str, attempt_id: str) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
        statement = select(attempts, executions.c.id.label("execution_id"), executions.c.status.label("execution_status"), experiments.c.id.label("experiment_id")).select_from(attempts.join(episodes, attempts.c.episode_id == episodes.c.id).join(executions, episodes.c.execution_id == executions.c.id).join(experiments, executions.c.experiment_id == experiments.c.id)).where(attempts.c.id == attempt_id, experiments.c.project_id == project)
        with self.repository.engine.connect() as conn:
            attempt = conn.execute(statement).mappings().one_or_none()
            if attempt is None:
                raise ObservatoryError("attempt_not_found", "The requested persisted attempt was not found.", status_code=404)
            events = conn.execute(
                select(attempt_events)
                .where(attempt_events.c.attempt_id == attempt_id)
                .order_by(attempt_events.c.sequence)
                .limit(_MAX_EVENTS_PER_ATTEMPT + 1)
            ).mappings().all()
        if len(events) > _MAX_EVENTS_PER_ATTEMPT:
            raise ObservatoryError(
                "observatory_attempt_too_large",
                "The named persisted attempt exceeds the Observatory event bound.",
                status_code=409,
            )
        return attempt, events

    @staticmethod
    def _ledger(attempt: Mapping[str, Any], events: list[Mapping[str, Any]]) -> dict[str, Any]:
        entries = []
        for event in events:
            payload = event["payload"] or {}
            payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            entries.append({"event_id": event["id"], "attempt_id": event["attempt_id"], "execution_id": event["execution_id"], "attempt_sequence": event["sequence"], "execution_sequence": event["execution_sequence"], "event_type": event["event_type"], "created_at": event["created_at"].isoformat() if event["created_at"] is not None else None, "payload_digest": "sha256:" + hashlib.sha256(payload_bytes).hexdigest()})
        trace_complete = bool((attempt["result_metadata"] or {}).get("trace_complete"))
        fidelity = "observed" if entries and trace_complete else "unknown"
        return {"ledger_version": "scaffold-arena.observatory/1", "attempt_id": attempt["id"], "execution_id": attempt["execution_id"], "experiment_id": attempt["experiment_id"], "fidelity_level": fidelity, "event_count": len(entries) if entries else None, "event_count_state": "observed" if entries else "unknown", "events": entries, "unknowns": (["no persisted attempt events"] if not entries else ([] if trace_complete else ["trace completeness is not verified"]))}

    @staticmethod
    def _analysis(
        ledgers: list[Mapping[str, Any]],
        *,
        xray_analysis_digest: str | None,
        source_artifact_digest: str | None,
    ) -> dict[str, Any]:
        event_count = sum(len(ledger["events"]) for ledger in ledgers)
        eventful = [ledger for ledger in ledgers if ledger["events"]]
        event_types = sorted({event["event_type"] for ledger in ledgers for event in ledger["events"]})
        # Ledgers expose type, sequence, and payload digest only. Payload text,
        # prompts, outputs, and secrets never become diagnostic output.
        context_events = [event for ledger in ledgers for event in ledger["events"] if "context" in event["event_type"].lower()]
        memory_events = [event for ledger in ledgers for event in ledger["events"] if "memory" in event["event_type"].lower()]
        unknown_context_metrics = [
            {"metric_id": metric, "value": None, "numerator": None, "denominator": None, "exclusions": ["event payload content and required annotations are not retained in this observatory report"]}
            for metric in _CONTEXT_METRICS
        ]
        unknown_memory_metrics = [
            {"metric_id": metric, "value": None, "numerator": None, "denominator": None, "exclusions": ["event payload content and required annotations are not retained in this observatory report"]}
            for metric in _MEMORY_METRICS
        ]
        loops = [
            {"check": check, "status": "unknown", "reason": "event types and payload digests do not establish the required state, progress, or correction evidence"}
            for check in _LOOP_CHECKS
        ]
        graph_nodes = [{"node_id": item, "status": "observed"} for item in event_types]
        graph_edges = []
        for ledger in ledgers:
            sequence = [event["event_type"] for event in ledger["events"]]
            graph_edges.extend({"subject": before, "object": after, "status": "observed"} for before, after in pairwise(sequence) if before != after)
        stages = []
        labels = {event["event_type"].lower() for ledger in ledgers for event in ledger["events"]}
        observed_edges = {
            (before.lower(), after.lower())
            for ledger in ledgers
            for before, after in pairwise(
                [event["event_type"] for event in ledger["events"]]
            )
            if before != after
        }
        aliases = {
            "declared": ("factor_declared",), "assigned": ("factor_assigned",), "available": ("factor_available",),
            "triggered": ("factor_triggered",), "applied": ("factor_applied",), "activated": ("factor_activated",),
            "observed": ("factor_observed", "factor_fidelity"), "downstream_pathway_detected": ("downstream_pathway_detected",),
        }
        for stage in _LADDER:
            if stage == "downstream_pathway_detected":
                matched = any(after in aliases[stage] for _, after in observed_edges)
                reason = (
                    "named persisted downstream edge observed"
                    if matched
                    else "no named persisted downstream edge establishes this stage"
                )
            else:
                matched = any(alias in labels for alias in aliases[stage])
                reason = (
                    "named persisted event observed"
                    if matched
                    else "no named persisted event establishes this stage"
                )
            stages.append({"stage": stage, "status": "observed" if matched else "unknown", "reason": reason})
        fidelity_level = next((stage["stage"] for stage in reversed(stages) if stage["status"] == "observed"), "unknown")
        attempt_ids = [ledger["attempt_id"] for ledger in ledgers]
        graph_checks = {
            check: {"status": "unknown", "reason": "event-type topology does not establish the required authority, value, or failure-propagation evidence"}
            for check in _GRAPH_CHECKS
        }
        conditional_treatment_metrics = [
            {"metric_id": metric, "value": None, "numerator": None, "denominator": None, "exclusions": [reason]}
            for metric, reason in (
                ("intention_to_treat", "assignment and outcome evidence are not established by this diagnostic"),
                ("opportunity", "opportunity denominator and eligibility evidence are not established by this diagnostic"),
                ("activation", "activation denominator and applied-control evidence are not established by this diagnostic"),
                ("fidelity_failure", "fidelity-stage and denominator evidence are not established by this diagnostic"),
                ("treatment_on_the_treated", "treatment-on-the-treated requires assignment, activation, exclusion, and no-confounding assumptions not established here"),
            )
        ]
        return {
            "claim_ceiling": _CEILING,
            "evidence_ceiling": _CEILING,
            "context_ledger": {
                "event_count": len(context_events) if context_events else None,
                "state": "observed" if context_events else "unknown",
                "reason": "only event-type metadata is available",
                "fields": {field: "unknown" for field in ("source", "scope", "sensitivity", "tokens", "retrieval_score", "transformation_lineage", "ordering", "compression_survival", "delivery", "citation_use", "cost")},
                "metrics": unknown_context_metrics,
            },
            "memory_ledger": {
                "event_count": len(memory_events) if memory_events else None,
                "state": "observed" if memory_events else "unknown",
                "reason": "only event-type metadata is available",
                "fields": {field: "unknown" for field in ("origin", "representation", "scope", "ttl_retention", "updates", "conflicts", "retrievals", "downstream_decisions", "deletion_forgetting", "privacy_class", "cost")},
                "metrics": unknown_memory_metrics,
            },
            "loop_microscope": loops,
            "graph_microscope": {"node_count": len(graph_nodes) if graph_nodes else None, "edge_count": len(graph_edges) if graph_edges else None, "nodes": graph_nodes, "edges": graph_edges, "state": "observed" if graph_nodes else "unknown", **graph_checks},
            "intervention_fidelity": stages,
            "fidelity_ladder": list(_LADDER),
            "fidelity_level": fidelity_level,
            "metrics": [
                {"metric_id": "attempts_with_persisted_events", "value": len(eventful), "numerator": len(eventful), "denominator": len(ledgers), "exclusions": [ledger["attempt_id"] for ledger in ledgers if not ledger["events"]]},
                {"metric_id": "persisted_event_count", "value": event_count if eventful else None, "numerator": event_count if eventful else None, "denominator": len(ledgers) if eventful else None, "exclusions": [ledger["attempt_id"] for ledger in ledgers if not ledger["events"]]},
                *conditional_treatment_metrics,
            ],
            "attempt_ids": attempt_ids,
            "xray_analysis_digest": xray_analysis_digest,
            "source_artifact_digest": source_artifact_digest,
            "limitations": ["No events were reconstructed.", "No execution was started.", "No causal, ITT, activation, fidelity-failure, or TOT outcome is reported without its required evidence."],
            "provider_execution_started": False,
            "execution_started": False,
            "network_requested": False,
        }

    def _load_analysis(self, digest: str, *, project: str, idempotent_replay: bool) -> dict[str, Any]:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(observatory_analyses).where(observatory_analyses.c.analysis_digest == digest, observatory_analyses.c.project_id == project)).mappings().one_or_none()
        if row is None:
            raise ObservatoryError("observatory_report_not_found", "The requested Observatory report was not found.", status_code=404)
        try:
            raw = self.artifact_store.get_bytes(row["report_artifact_digest"])
            if hashlib.sha256(raw).hexdigest() != row["report_artifact_digest"]:
                raise ValueError("report digest mismatch")
            report = json.loads(raw)
        except (ArtifactIntegrityError, OSError, TypeError, ValueError) as exc:
            raise ObservatoryError("observatory_custody_unavailable", "The observatory report cannot be verified.", status_code=409) from exc
        return self._public_analysis(report, digest=digest, idempotent_replay=idempotent_replay)

    @staticmethod
    def _public_analysis(report: Mapping[str, Any], *, digest: str, idempotent_replay: bool) -> dict[str, Any]:
        public = {
            **report,
            "report_id": f"observatory-{digest[:24]}",
            "report_digest": f"sha256:{digest}",
            "analysis_digest": f"sha256:{digest}",
            "report_artifact_digest": f"sha256:{digest}",
            "idempotent_replay": idempotent_replay,
        }
        try:
            return ObservatoryReport.model_validate(public).model_dump(mode="json")
        except ValidationError as exc:
            raise ObservatoryError(
                "observatory_report_invalid",
                "The bounded Observatory report could not be validated.",
                status_code=500,
            ) from exc

    @staticmethod
    def _report(row: Mapping[str, Any], *, idempotent_replay: bool) -> dict[str, Any]:
        return {"report_id": row["id"], "attempt_id": row["attempt_id"], "ledger_digest": f"sha256:{row['ledger_digest']}", "fidelity_level": row["fidelity_level"], "claim_ceiling": row["claim_ceiling"], "idempotent_replay": idempotent_replay}


def _bare_digest(value: str) -> str:
    value = value.removeprefix("sha256:")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ObservatoryError("observatory_digest_invalid", "A lowercase SHA-256 report digest is required.")
    return value
