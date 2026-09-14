"""Static, non-executing Harness X-Ray ingestion and custody inspection."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select

from artifacts_v1 import ArtifactIntegrityError, ArtifactStore
from persistence_v1 import ArenaRepository
from persistence_v1.schema import (
    artifacts,
    projects,
    xray_analyses,
    xray_findings,
    xray_snapshots,
)
from xray_v1 import (
    XRayRequest,
    XRayReport,
    XraySourceSnapshot,
    canonical_snapshot_bytes,
    snapshot_digest,
)

_CEILING = "static source-snapshot observation only; no execution, network retrieval, causal, performance, or security-assurance claim"
_REPORT_CEILING = "bounded captured-artifact inspection only; candidate mechanisms are declared or observed static metadata, never runtime, causal, performance, or security evidence"
_MAX_SOURCE_BYTES = 1_000_000


class XrayError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _id() -> str:
    return f"x{uuid.uuid4().hex}"


def _bare(digest: str) -> str:
    if not digest.startswith("sha256:"):
        raise XrayError("xray_digest_invalid", "A SHA-256 source digest is required.")
    return digest[7:]


def _artifact_digest(digest: str) -> str:
    value = digest.removeprefix("sha256:")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise XrayError("xray_artifact_digest_invalid", "A lowercase SHA-256 captured-artifact digest is required.")
    return value


class XrayService:
    """Accept captured JSON/text only; it contains no executor or client."""

    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def _project(self, project_id: str | None) -> str:
        project = project_id or self.personal_project_id
        if not project:
            raise XrayError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            found = conn.execute(select(projects.c.id).where(projects.c.id == project)).scalar_one_or_none()
        if found is None:
            raise XrayError("unknown_project", "The supplied project does not exist.", status_code=404)
        return project

    @staticmethod
    def _parse(payload: Mapping[str, Any]) -> XraySourceSnapshot:
        try:
            snapshot = XraySourceSnapshot.model_validate(payload)
        except (TypeError, ValidationError, ValueError) as exc:
            raise XrayError("xray_snapshot_invalid", "A strict static X-Ray source snapshot is required.") from exc
        expected = snapshot_digest(snapshot)
        if snapshot.source_digest != expected:
            raise XrayError("xray_digest_mismatch", "The source digest does not bind the supplied static snapshot.")
        return snapshot

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = self._parse(payload)
        return {
            "valid": True,
            "snapshot_id": snapshot.snapshot_id,
            "source_digest": snapshot.source_digest,
            "finding_states": sorted({finding.evidence_state for finding in snapshot.findings}),
            "claim_ceiling": _CEILING,
            "execution_started": False,
            "network_requested": False,
        }

    def ingest(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        snapshot = self._parse(payload)
        canonical = canonical_snapshot_bytes(snapshot)
        digest = _bare(snapshot.source_digest or "")
        stored_digest = self.artifact_store.put_bytes(canonical, media_type="application/vnd.scaffold-arena.xray-source+json", metadata={"kind": "xray-source-snapshot"})
        if stored_digest != digest:
            raise XrayError("xray_artifact_integrity", "The source snapshot could not be stored with its declared digest.", status_code=500)
        with self.repository.transaction(immediate=True) as conn:
            existing = conn.execute(select(xray_snapshots).where(xray_snapshots.c.project_id == project, xray_snapshots.c.source_digest == digest)).mappings().one_or_none()
            if existing is not None:
                if existing["id"] != snapshot.snapshot_id:
                    # Content identity wins.  This avoids two names becoming two authorities.
                    return self._summary(existing, idempotent_replay=True)
                return self._summary(existing, idempotent_replay=True)
            artifact = conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none()
            if artifact is None:
                conn.execute(insert(artifacts).values(digest=digest, size_bytes=len(canonical), storage_uri=self.artifact_store.uri_for(digest), media_type="application/vnd.scaffold-arena.xray-source+json", metadata_json={"kind": "xray-source-snapshot"}))
            conn.execute(insert(xray_snapshots).values(id=snapshot.snapshot_id, project_id=project, source_digest=digest, source_name=snapshot.source_name, source_uri=snapshot.source_uri, source_revision=snapshot.source_revision, captured_at=snapshot.captured_at, claim_ceiling=_CEILING))
            for finding in snapshot.findings:
                statement_digest = hashlib.sha256(finding.statement.encode("utf-8")).hexdigest()
                conn.execute(insert(xray_findings).values(snapshot_id=snapshot.snapshot_id, finding_id=finding.finding_id, evidence_state=finding.evidence_state, statement_digest=statement_digest))
        return self._summary_by_id(project, snapshot.snapshot_id, idempotent_replay=False)

    def create_report(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        """Inspect a durable byte capture; this never executes or fetches its source."""
        project = self._project(project_id)
        try:
            request = XRayRequest.model_validate(payload)
        except (TypeError, ValidationError, ValueError) as exc:
            raise XrayError("xray_request_invalid", "A strict XRayRequest with a captured artifact digest is required.") from exc
        source_digest = _artifact_digest(request.source_artifact_digest)
        with self.repository.engine.connect() as conn:
            artifact = conn.execute(select(artifacts).where(artifacts.c.digest == source_digest)).mappings().one_or_none()
        if artifact is None:
            raise XrayError("xray_source_not_found", "The named captured source artifact is not available.", status_code=404)
        if artifact["size_bytes"] > _MAX_SOURCE_BYTES:
            raise XrayError(
                "xray_source_too_large",
                "The named captured source exceeds the static X-Ray byte bound.",
                status_code=409,
            )
        try:
            source = self.artifact_store.get_bytes(source_digest)
        except (ArtifactIntegrityError, OSError) as exc:
            raise XrayError("xray_source_unavailable", "The named captured source artifact cannot be verified.", status_code=409) from exc
        if len(source) != artifact["size_bytes"]:
            raise XrayError("xray_source_unavailable", "The named captured source artifact size does not match custody metadata.", status_code=409)
        report = self._build_report(source, source_digest=source_digest, source_kind=request.source_kind, profile_id=request.profile_id)
        # Address fields are deliberately outside the stored payload. This makes
        # ``report_digest`` the SHA-256 of exactly the immutable report bytes.
        raw = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        artifact_digest = self.artifact_store.put_bytes(raw, media_type="application/vnd.scaffold-arena.xray-report+json", metadata={"kind": "xray-report", "source_digest": source_digest})
        # ArtifactStore is content-addressed; a mismatch means custody is not sound.
        if artifact_digest != digest:
            raise XrayError("xray_artifact_integrity", "The X-Ray report could not be stored content-addressably.", status_code=500)
        with self.repository.transaction(immediate=True) as conn:
            existing = conn.execute(select(xray_analyses).where(xray_analyses.c.project_id == project, xray_analyses.c.source_digest == source_digest, xray_analyses.c.source_kind == request.source_kind)).mappings().one_or_none()
            if existing is not None:
                if existing["analysis_digest"] != digest:
                    raise XrayError("xray_report_conflict", "A different report is already bound to this project source and source kind.", status_code=409)
                return self._load_report(existing["analysis_digest"], project=project, idempotent_replay=True)
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == artifact_digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=artifact_digest, size_bytes=len(raw), storage_uri=self.artifact_store.uri_for(artifact_digest), media_type="application/vnd.scaffold-arena.xray-report+json", metadata_json={"kind": "xray-report", "source_digest": source_digest}))
            conn.execute(insert(xray_analyses).values(analysis_digest=digest, project_id=project, source_digest=source_digest, source_kind=request.source_kind, report_artifact_digest=artifact_digest, claim_ceiling=_REPORT_CEILING))
        return self._public_report(report, digest=digest, idempotent_replay=False)

    def report(self, report_digest: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        return self._load_report(_artifact_digest(report_digest), project=project, idempotent_replay=False)

    def _load_report(self, digest: str, *, project: str, idempotent_replay: bool) -> dict[str, Any]:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(xray_analyses).where(xray_analyses.c.analysis_digest == digest, xray_analyses.c.project_id == project)).mappings().one_or_none()
        if row is None:
            raise XrayError("xray_report_not_found", "The requested X-Ray report was not found.", status_code=404)
        try:
            raw = self.artifact_store.get_bytes(row["report_artifact_digest"])
            if hashlib.sha256(raw).hexdigest() != row["report_artifact_digest"]:
                raise ValueError("report digest mismatch")
            report = json.loads(raw)
        except (ArtifactIntegrityError, OSError, TypeError, ValueError) as exc:
            raise XrayError("xray_custody_unavailable", "The X-Ray report cannot be verified.", status_code=409) from exc
        return self._public_report(report, digest=digest, idempotent_replay=idempotent_replay)

    @staticmethod
    def _public_report(report: Mapping[str, Any], *, digest: str, idempotent_replay: bool) -> dict[str, Any]:
        public = {
            **report,
            "report_id": f"xray-{digest[:24]}",
            "report_digest": f"sha256:{digest}",
            "analysis_digest": f"sha256:{digest}",  # v1 workbench compatibility
            "report_artifact_digest": f"sha256:{digest}",
            "idempotent_replay": idempotent_replay,
        }
        try:
            return XRayReport.model_validate(public).model_dump(mode="json")
        except ValidationError as exc:
            raise XrayError("xray_report_invalid", "The bounded X-Ray report could not be validated.", status_code=500) from exc

    @staticmethod
    def _build_report(source: bytes, *, source_digest: str, source_kind: str, profile_id: str | None) -> dict[str, Any]:
        """Extract only explicitly structured static declarations, never source text."""
        structured: Mapping[str, Any] = {}
        try:
            decoded = json.loads(source)
            if isinstance(decoded, Mapping):
                structured = decoded
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        refs = (f"artifact:sha256:{source_digest}",)
        mechanisms: list[dict[str, Any]] = []

        def add(
            mechanism_id: str,
            *,
            status: str,
            evidence_refs: list[str] | tuple[str, ...] = refs,
            inference_basis: str | None = None,
            verification_method: str | None = None,
            limitation: str | None = None,
        ) -> None:
            supported = {"declared", "observed", "inferred", "verified", "unsupported", "unknown"}
            resolved_status = status if status in supported else "unknown"
            resolved_refs = sorted(set(evidence_refs)) if resolved_status != "unknown" else []
            if resolved_status == "inferred" and (not resolved_refs or not inference_basis):
                resolved_status, resolved_refs, inference_basis = "unknown", [], None
            if resolved_status == "verified" and (not resolved_refs or not verification_method):
                resolved_status, resolved_refs, verification_method, limitation = (
                    "unsupported",
                    resolved_refs,
                    None,
                    "The captured declaration does not include a verification method.",
                )
            if resolved_status == "unsupported" and not limitation:
                limitation = "The captured source marks this control unsupported."
            base = mechanism_id
            existing_ids = {item["mechanism_id"] for item in mechanisms}
            if base in existing_ids:
                base = f"{base}-{hashlib.sha256((mechanism_id + status + '|'.join(resolved_refs)).encode('utf-8')).hexdigest()[:12]}"
            mechanisms.append(
                {
                    "mechanism_id": base,
                    "status": resolved_status,
                    "evidence_refs": resolved_refs,
                    **({"inference_basis": inference_basis} if inference_basis else {}),
                    **({"verification_method": verification_method} if verification_method else {}),
                    **({"limitation": limitation} if limitation else {}),
                }
            )

        component_categories = {
            "memory": "memory-read-write",
            "tool": "tools-permissions",
            "tool_transport": "tools-permissions",
            "telemetry": "evidence-tracing",
            "evaluator": "verification",
            "checkpoint": "retries-recovery",
            "approval_policy": "tools-permissions",
            "sandbox": "tools-permissions",
            "artifact_store": "evidence-tracing",
        }
        capability_categories = {
            "tools": "tools-permissions",
            "state": "context-selection-compaction",
            "checkpoint": "retries-recovery",
            "memory": "memory-read-write",
            "delegation": "routing-delegation",
            "usage": "budgets",
            "sandboxing": "tools-permissions",
            "approval": "tools-permissions",
            "telemetry": "evidence-tracing",
            "cancellation": "stopping",
            "cleanup": "retries-recovery",
        }
        relation_categories = {
            "delegates_to": "routing-delegation",
            "evaluates": "verification",
            "guards": "tools-permissions",
            "stores": "memory-read-write",
            "emits": "evidence-tracing",
            "invokes": "tools-permissions",
            "calls": "tools-permissions",
        }
        components = structured.get("components")
        if isinstance(components, list):
            for component in components[:256]:
                if isinstance(component, Mapping) and isinstance(component.get("component_id"), str):
                    kind = component.get("kind")
                    category = component_categories.get(kind) if isinstance(kind, str) else None
                    component_id = component["component_id"].lower()
                    if category is None:
                        if "plan" in component_id or "revision" in component_id:
                            category = "planning-revision"
                        elif "stop" in component_id or "budget" in component_id:
                            category = "stopping" if "stop" in component_id else "budgets"
                    if category is not None:
                        add(category, status="declared")
        relations = structured.get("relations")
        if isinstance(relations, list):
            for relation in relations[:512]:
                if isinstance(relation, Mapping) and isinstance(relation.get("relation_id"), str):
                    predicate = relation.get("predicate")
                    category = relation_categories.get(predicate) if isinstance(predicate, str) else None
                    if category is not None:
                        # The source capture is the only reportable evidence link.
                        # Caller-provided labels or URIs could disclose source material
                        # and are not independently verified at this boundary.
                        add(category, status="declared")
        capabilities = structured.get("capabilities")
        if isinstance(capabilities, list):
            for capability in capabilities[:256]:
                if isinstance(capability, Mapping):
                    domain = capability.get("domain")
                    category = capability_categories.get(domain) if isinstance(domain, str) else None
                    if category is not None:
                        add(category, status="declared")
        findings = structured.get("findings")
        if isinstance(findings, list):
            for finding in findings[:1024]:
                if not isinstance(finding, Mapping) or not isinstance(finding.get("finding_id"), str):
                    continue
                status = finding.get("evidence_state")
                add(
                    f"finding-{hashlib.sha256(finding['finding_id'].encode('utf-8')).hexdigest()[:24]}",
                    status=status if isinstance(status, str) else "unknown",
                    evidence_refs=[] if status == "unknown" else refs,
                    inference_basis=finding.get("inference_basis") if isinstance(finding.get("inference_basis"), str) else None,
                    verification_method=finding.get("verification_method") if isinstance(finding.get("verification_method"), str) else None,
                    limitation=finding.get("limitation") if isinstance(finding.get("limitation"), str) else None,
                )
        if source_kind == "otel_bundle":
            add("evidence-tracing", status="declared")
        if source_kind == "recorded_run":
            add("recorded-run-observation", status="declared")
        mechanisms = sorted(mechanisms, key=lambda item: (item["mechanism_id"], item["status"]))
        states = sorted({item["status"] for item in mechanisms})
        candidate = {
            "schema": "scaffold-arena.xray-candidate-genome/1",
            "source_artifact_digest": f"sha256:{source_digest}",
            "source_kind": source_kind,
            "profile_id": profile_id,
            "status": states[0] if len(states) == 1 else "mixed" if states else "unknown",
            "component_count": len(mechanisms),
            "evidence_states": states,
            "claim_ceiling": _REPORT_CEILING,
        }
        return {
            "claim_ceiling": _REPORT_CEILING,
            "candidate_genome": candidate,
            "mechanism_graph": {"nodes": [{"node_id": item["mechanism_id"], "status": item["status"], "evidence_refs": item["evidence_refs"]} for item in mechanisms], "edges": [], "status": candidate["status"], "evidence_refs": list(refs)},
            "detected_mechanisms": mechanisms,
            "mechanisms": mechanisms,
            "unobservable_controls": ["runtime behavior", "provider calls", "network effects", "hidden configuration"],
            "confounds": ["captured artifact may be incomplete", "source provenance is not independently verified"],
            "security_paths": ["unknown: static capture does not establish a live security boundary"],
            "first_study": {"status": "HOLD", "design": "preregister a bounded same-model, same-task comparison before execution", "evidence_refs": list(refs)},
            "expected_attempts": None,
            "expected_cost_interval": {"minimum_usd": None, "maximum_usd": None, "status": "unknown", "reason": "no provider usage or price evidence is present in a static capture"},
            "evidence_ceiling": _REPORT_CEILING,
            "limitations": ["No execution was started.", "No network was requested.", "Static extraction does not establish runtime behavior."],
            "provider_execution_started": False,
            "execution_started": False,
            "network_requested": False,
        }

    def list(self, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(select(xray_snapshots).where(xray_snapshots.c.project_id == project).order_by(xray_snapshots.c.created_at, xray_snapshots.c.id)).mappings().all()
        return {"snapshots": [self._summary(row, idempotent_replay=False) for row in rows], "claim_ceiling": _CEILING}

    def get(self, snapshot_id: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(xray_snapshots).where(xray_snapshots.c.project_id == project, xray_snapshots.c.id == snapshot_id)).mappings().one_or_none()
        if row is None:
            raise XrayError("xray_snapshot_not_found", "The requested X-Ray snapshot was not found.", status_code=404)
        try:
            raw = self.artifact_store.get_bytes(row["source_digest"])
            snapshot = XraySourceSnapshot.model_validate_json(raw)
            if _bare(snapshot.source_digest or "") != row["source_digest"] or snapshot.snapshot_id != row["id"]:
                raise ValueError("custody index mismatch")
        except (ArtifactIntegrityError, OSError, ValueError, ValidationError) as exc:
            raise XrayError("xray_custody_unavailable", "The static X-Ray source snapshot cannot be verified.", status_code=409) from exc
        return {"snapshot": snapshot.model_dump(mode="json"), "custody": {"source_digest": snapshot.source_digest, "artifact_integrity_verified": True}, "claim_ceiling": _CEILING, "execution_started": False, "network_requested": False}

    def _summary_by_id(self, project: str, snapshot_id: str, *, idempotent_replay: bool) -> dict[str, Any]:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(xray_snapshots).where(xray_snapshots.c.project_id == project, xray_snapshots.c.id == snapshot_id)).mappings().one()
        return self._summary(row, idempotent_replay=idempotent_replay)

    @staticmethod
    def _summary(row: Mapping[str, Any], *, idempotent_replay: bool) -> dict[str, Any]:
        return {"snapshot_id": row["id"], "source_name": row["source_name"], "source_uri": row["source_uri"], "source_revision": row["source_revision"], "source_digest": f"sha256:{row['source_digest']}", "captured_at": row["captured_at"], "claim_ceiling": row["claim_ceiling"], "idempotent_replay": idempotent_replay, "execution_started": False, "network_requested": False}
