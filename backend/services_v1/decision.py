"""Durable, service-owned admission for Analysis v1 decision artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from analysis_v1 import (
    ClaimCeiling,
    ClaimDisposition,
    ClaimKind,
    ClaimLedger,
    DecisionArtifacts,
    DecisionBrief,
    DecisionRequest,
    DecisionVerdict,
    EvidenceMaturity,
    EvidenceReceiptReference,
    ProposedClaim,
    RiskConstraints,
    build_decision_artifacts,
)
from analysis_v1.engine import AnalysisReport
from artifacts_v1 import ArtifactStore
from evidence_v1 import EvidenceManifest, EvidenceReceipt, verify_evidence
from persistence_v1 import ArenaRepository, ImmutableDecisionConflict
from persistence_v1.schema import artifacts, decision_briefs, projects
from protocol_v1 import ExperimentSpec
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes


class DecisionError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_CEILING_BY_KIND = {
    ClaimKind.FIXTURE_OBSERVATION: ClaimCeiling.FIXTURE_ONLY,
    ClaimKind.LOCAL_LIVE_OBSERVATION: ClaimCeiling.LOCAL_LIVE_ONLY,
    ClaimKind.CAUSAL_EFFECT: ClaimCeiling.CONFIRMATORY_ANALYSIS,
    ClaimKind.GENERALIZED_EFFECT: ClaimCeiling.REPLICATED,
    ClaimKind.COST_COMPARISON: ClaimCeiling.LOCAL_LIVE_ONLY,
    ClaimKind.PARETO_COMPARISON: ClaimCeiling.LOCAL_LIVE_ONLY,
    ClaimKind.CROSS_MODEL_REPLICATION: ClaimCeiling.CROSS_MODEL,
    ClaimKind.HUMAN_CALIBRATED_ASSESSMENT: ClaimCeiling.HUMAN_CALIBRATED,
    ClaimKind.INDEPENDENT_VALIDATION: ClaimCeiling.INDEPENDENT,
}
_CEILING_RANK = {value: index for index, value in enumerate(ClaimCeiling)}


def _verification_evidence_type(receipt_kind: str) -> str:
    if receipt_kind == "derived_fixture":
        return "fixture"
    if receipt_kind == "derived_local_live":
        return "local_live"
    return receipt_kind


class DecisionService:
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
            raise DecisionError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            known = conn.execute(
                select(projects.c.id).where(projects.c.id == resolved)
            ).scalar_one_or_none()
        if known is None:
            raise DecisionError("unknown_project", "The supplied project does not exist.", status_code=404)
        return resolved

    def create(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        report_row, risk_constraints, proposed_claims = self._request(payload, project_id)
        report = self._load_report(report_row)
        references, holds = self._receipt_references(
            project_id, report_row, report.canonical_hash, proposed_claims
        )
        try:
            artifacts = build_decision_artifacts(
                DecisionRequest(
                    analysis_report=report,
                    evidence_receipts=tuple(references),
                    risk_constraints=risk_constraints,
                    proposed_claims=tuple(proposed_claims),
                )
            )
        except (ValidationError, ValueError) as exc:
            raise DecisionError(
                "decision_hold",
                "Stored analysis or evidence bindings cannot support a decision.",
                status_code=409,
            ) from exc
        artifacts = self._apply_service_holds(artifacts, holds)
        brief_bytes = canonical_json(artifacts.brief.model_dump(mode="json"))
        ledger_bytes = canonical_json(artifacts.ledger.model_dump(mode="json"))
        brief_digest = self._store_artifact(brief_bytes, "decision-brief-v1")
        ledger_digest = self._store_artifact(ledger_bytes, "claim-ledger-v1")
        request_digest = sha256(
            {
                "analysis_report_id": report_row["id"],
                "risk_constraints": risk_constraints,
                "proposed_claims": proposed_claims,
            }
        )
        record = {
            "id": sha256({"format": "decision-record-v1", "project_id": project_id, "analysis_report_id": report_row["id"]}),
            "project_id": project_id,
            "analysis_report_id": report_row["id"],
            "experiment_id": report_row["experiment_id"],
            "execution_id": report_row["execution_id"],
            "report_digest": report_row["report_digest"],
            "request_digest": request_digest,
            "brief_hash": artifacts.brief.canonical_hash,
            "ledger_hash": artifacts.ledger.canonical_hash,
            "brief_artifact_digest": brief_digest,
            "ledger_artifact_digest": ledger_digest,
            "verdict": artifacts.brief.verdict.value,
            "claim_ceiling": artifacts.brief.supported_claim_ceiling.value,
            "claim_refs": [
                {"claim_id": item.claim_id, "receipt_ids": list(item.linked_receipt_ids)}
                for item in proposed_claims
            ],
        }
        try:
            replay = self.repository.create_decision_brief(project_id, record=record)
        except ImmutableDecisionConflict as exc:
            raise DecisionError(
                "decision_conflict",
                "This analysis report is already bound to different decision content.",
                status_code=409,
            ) from exc
        except ValueError as exc:
            raise DecisionError(
                "decision_binding_invalid",
                "The decision artifacts cannot be bound to this immutable analysis report.",
                status_code=409,
            ) from exc
        return {**self._metadata(record), "idempotent_replay": replay}

    def get(self, decision_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        row = self.repository.get_decision_brief(project_id, decision_id)
        if row is None:
            raise DecisionError("decision_not_found", "The requested decision brief was not found.", status_code=404)
        return self._metadata(row)

    def list(
        self,
        *,
        project_id: str | None,
        execution_id: str | None = None,
        report_digest: str | None = None,
        verdict: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return redacted summaries only after revalidating durable decision bindings."""
        project_id = self.resolve_project(project_id)
        limit, offset = self._page(limit, offset)
        statement = select(decision_briefs).where(
            decision_briefs.c.project_id == project_id
        )
        if execution_id is not None:
            statement = statement.where(decision_briefs.c.execution_id == execution_id)
        if report_digest is not None:
            statement = statement.where(decision_briefs.c.report_digest == report_digest)
        if verdict is not None:
            statement = statement.where(decision_briefs.c.verdict == verdict)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(
                statement.order_by(decision_briefs.c.created_at, decision_briefs.c.id)
            ).mappings().all()
        summaries = [self._list_summary(project_id, row) for row in rows]
        page = summaries[offset : offset + limit]
        return {
            "decision_briefs": page,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": offset + limit if len(summaries) > offset + limit else None,
            },
            "integrity_not_truth": True,
            "claim_ceiling": "brief-specific; summaries do not expose decision artifacts",
        }

    def _request(
        self, payload: Mapping[str, Any], project_id: str
    ) -> tuple[Mapping[str, Any], RiskConstraints, tuple[ProposedClaim, ...]]:
        keys = set(payload)
        by_id = {"analysis_report_id", "risk_constraints", "proposed_claims"}
        by_execution = {"experiment_id", "execution_id", "risk_constraints", "proposed_claims"}
        if keys == by_id:
            report_id = payload.get("analysis_report_id")
            if not isinstance(report_id, str) or not report_id:
                raise DecisionError("invalid_decision_request", "analysis_report_id must be a non-empty string.")
            report = self.repository.get_analysis_report_by_id(project_id, report_id)
        elif keys == by_execution:
            experiment_id, execution_id = payload.get("experiment_id"), payload.get("execution_id")
            if not isinstance(experiment_id, str) or not isinstance(execution_id, str):
                raise DecisionError("invalid_decision_request", "experiment_id and execution_id must be strings.")
            report = self.repository.get_analysis_report(project_id, execution_id)
            if report is not None and report["experiment_id"] != experiment_id:
                report = None
        else:
            raise DecisionError(
                "invalid_decision_request",
                "Use exactly analysis_report_id or experiment_id plus execution_id, risk_constraints, and proposed_claims; caller maturity, hashes, and artifact references are forbidden.",
            )
        if report is None:
            raise DecisionError("analysis_report_not_found", "The immutable analysis report was not found in this project.", status_code=404)
        try:
            risk = RiskConstraints.model_validate_json(
                canonical_json(payload["risk_constraints"])
            )
            raw_claims = payload["proposed_claims"]
            if not isinstance(raw_claims, list) or not raw_claims:
                raise ValueError("proposed_claims must be a non-empty list")
            claims = tuple(
                ProposedClaim.model_validate_json(canonical_json(value))
                for value in raw_claims
            )
            if len({claim.claim_id for claim in claims}) != len(claims):
                raise ValueError("claim ids must be unique")
        except (KeyError, TypeError, ValidationError, ValueError) as exc:
            raise DecisionError("invalid_decision_request", "Risk constraints and proposed claims must satisfy the strict decision contract.") from exc
        return report, risk, claims

    def _load_report(self, row: Mapping[str, Any]) -> AnalysisReport:
        try:
            content = self.artifact_store.get_bytes(str(row["artifact_digest"]))
            report = AnalysisReport.model_validate_json(content)
        except (FileNotFoundError, ValidationError, ValueError, OSError) as exc:
            raise DecisionError("analysis_report_tampered", "The stored analysis report artifact cannot be read and verified.", status_code=409) from exc
        if (
            sha256_bytes(content) != row["artifact_digest"]
            or sha256_bytes(content) != row["report_digest"]
            or canonical_json(report.model_dump(mode="json")) != content
            or sha256(report.model_dump(mode="json", exclude={"canonical_hash"})) != report.canonical_hash
        ):
            raise DecisionError("analysis_report_tampered", "The stored analysis report bytes or canonical hash do not match its immutable record.", status_code=409)
        return report

    def _list_summary(self, project_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        """Check report, paired artifacts, and record binding before returning metadata."""
        report = self.repository.get_analysis_report_by_id(project_id, str(row["analysis_report_id"]))
        if report is None or any(
            report[key] != row[key]
            for key in ("experiment_id", "execution_id", "report_digest")
        ):
            raise DecisionError(
                "decision_integrity_hold",
                "A stored decision brief is not bound to its immutable analysis report.",
                status_code=409,
            )
        canonical_report = self._load_report(report)
        digests = {str(row["brief_artifact_digest"]), str(row["ledger_artifact_digest"])}
        with self.repository.engine.connect() as conn:
            registered = {
                str(item["digest"]): dict(item)
                for item in conn.execute(
                    select(artifacts).where(artifacts.c.digest.in_(digests))
                ).mappings()
            }
        if set(registered) != digests:
            raise DecisionError(
                "decision_integrity_hold",
                "A stored decision artifact is no longer durably registered.",
                status_code=409,
            )
        try:
            brief_bytes = self.artifact_store.get_bytes(str(row["brief_artifact_digest"]))
            ledger_bytes = self.artifact_store.get_bytes(str(row["ledger_artifact_digest"]))
            brief = DecisionBrief.model_validate_json(brief_bytes)
            ledger = ClaimLedger.model_validate_json(ledger_bytes)
        except (FileNotFoundError, OSError, ValidationError, ValueError) as exc:
            raise DecisionError(
                "decision_integrity_hold",
                "A stored decision artifact cannot be read and revalidated.",
                status_code=409,
            ) from exc
        if (
            registered[str(row["brief_artifact_digest"])].get("media_type") != "application/json"
            or registered[str(row["ledger_artifact_digest"])].get("media_type") != "application/json"
            or sha256_bytes(brief_bytes) != row["brief_artifact_digest"]
            or sha256_bytes(ledger_bytes) != row["ledger_artifact_digest"]
            or canonical_json(brief.model_dump(mode="json")) != brief_bytes
            or canonical_json(ledger.model_dump(mode="json")) != ledger_bytes
            or sha256(brief.model_dump(mode="json", exclude={"canonical_hash"})) != brief.canonical_hash
            or sha256(ledger.model_dump(mode="json", exclude={"canonical_hash"})) != ledger.canonical_hash
            or brief.canonical_hash != row["brief_hash"]
            or ledger.canonical_hash != row["ledger_hash"]
            or brief.analysis_report_hash != canonical_report.canonical_hash
            or ledger.analysis_report_hash != canonical_report.canonical_hash
            or brief.verdict.value != row["verdict"]
            or brief.supported_claim_ceiling.value != row["claim_ceiling"]
        ):
            raise DecisionError(
                "decision_integrity_hold",
                "A stored decision artifact or its immutable metadata binding is inconsistent.",
                status_code=409,
            )
        return {
            "decision_brief_id": row["id"],
            "created_at": row["created_at"],
            "analysis_report_id": row["analysis_report_id"],
            "experiment_id": row["experiment_id"],
            "execution_id": row["execution_id"],
            "report_digest": row["report_digest"],
            "verdict": row["verdict"],
            "claim_ceiling": row["claim_ceiling"],
            "claim_count": len(ledger.entries),
            "artifact_content": "withheld",
            "integrity_not_truth": True,
        }

    def _receipt_references(
        self,
        project_id: str,
        report_row: Mapping[str, Any],
        report_hash: str,
        claims: tuple[ProposedClaim, ...],
    ) -> tuple[list[EvidenceReceiptReference], dict[str, str]]:
        receipt_ids = tuple(sorted({item for claim in claims for item in claim.linked_receipt_ids}))
        references: list[EvidenceReceiptReference] = []
        holds: dict[str, str] = {}
        for receipt_id in receipt_ids:
            row = self.repository.get_evidence_receipt(project_id, receipt_id)
            if row is None:
                raise DecisionError("evidence_not_found", "A linked evidence receipt was not found in this project.", status_code=404)
            valid, reason = self._verify_receipt(project_id, row, report_row)
            maturity = self._receipt_maturity(row)
            reasons: list[str] = []
            if row.get("integrity_not_truth") is not True:
                valid = False
                reasons.append("stored evidence receipt lacks the integrity-not-truth boundary")
            if not valid:
                reasons.append(reason)
            if maturity is None:
                reasons.append("receipt type is not admitted by a dedicated maturity workflow")
                maturity = EvidenceMaturity.FIXTURE
            receipt_hash = str(row.get("receipt_hash") or "")
            if len(receipt_hash) != 64 or any(char not in "0123456789abcdef" for char in receipt_hash):
                reasons.append("stored receipt hash is invalid")
                receipt_hash = sha256({"invalid_receipt_id": receipt_id})
            if reasons:
                holds[receipt_id] = "; ".join(dict.fromkeys(reasons))
            references.append(
                EvidenceReceiptReference(
                    receipt_id=receipt_id,
                    maturity=maturity,
                    receipt_hash=receipt_hash,
                    analysis_report_hash=report_hash,
                    artifact_ref=f"receipt:{receipt_id}",
                )
            )
        return references, holds

    @staticmethod
    def _receipt_maturity(row: Mapping[str, Any]) -> EvidenceMaturity | None:
        """Only service-derived local-live receipts may carry local-live maturity."""
        try:
            manifest = EvidenceManifest.model_validate_json(canonical_json(row["manifest_json"]))
        except (TypeError, ValidationError, ValueError):
            return None
        kind = str(row.get("receipt_kind"))
        if kind in {"fixture", "derived_fixture"} and manifest.evidence_class.value == "fixture":
            return EvidenceMaturity.FIXTURE
        if kind == "derived_local_live" and manifest.evidence_class.value == "local_live":
            return EvidenceMaturity.LOCAL_LIVE
        return None

    def _verify_receipt(
        self,
        project_id: str,
        row: Mapping[str, Any],
        report_row: Mapping[str, Any],
    ) -> tuple[bool, str]:
        try:
            manifest = EvidenceManifest.model_validate_json(canonical_json(row["manifest_json"]))
            if sha256(manifest) != row["manifest_hash"]:
                return False, "stored evidence manifest hash is inconsistent"
            binding_error = self._receipt_binding_error(project_id, row, report_row, manifest)
            if binding_error:
                return False, binding_error
            receipt = EvidenceReceipt(
                receipt_id=str(row["id"]),
                manifest_hash=str(row["manifest_hash"]),
                artifact_hashes=tuple(row["artifact_hashes"] or ()),
                receipt_hash=str(row["receipt_hash"]),
            )
            verification = verify_evidence(
                receipt,
                manifest,
                self.artifact_store,
                evidence_type=_verification_evidence_type(str(row["receipt_kind"])),
                verifier_id="decision-brief-verifier-v1",
                verifier_digest=sha256({"service": "decision-brief-verifier-v1"}),
                registered_artifacts=self.repository.evidence_artifacts(project_id, str(row["id"])),
            )
        except (KeyError, TypeError, ValidationError, ValueError, OSError, FileNotFoundError):
            return False, "stored evidence receipt cannot be freshly verified"
        if not verification.verified:
            return False, "stored evidence custody/integrity verification failed"
        return True, ""

    def _receipt_binding_error(
        self,
        project_id: str,
        row: Mapping[str, Any],
        report_row: Mapping[str, Any],
        manifest: EvidenceManifest,
    ) -> str | None:
        execution_id = report_row["execution_id"]
        if row.get("execution_id") != execution_id:
            return "receipt execution does not exactly match the immutable analysis report execution"
        binding = self.repository.get_execution_evidence_binding(project_id, execution_id)
        if binding is None:
            return "analysis report execution no longer has a project-scoped frozen binding"
        if (
            binding.get("execution_status") != "completed"
            or binding.get("experiment_id") != report_row["experiment_id"]
            or binding.get("frozen_at") is None
            or binding.get("spec_hash") != report_row["spec_hash"]
            or binding.get("study_pack_hash") != report_row["study_pack_hash"]
            or not isinstance(binding.get("definition"), Mapping)
        ):
            return "analysis report execution frozen binding is invalid"
        try:
            spec = ExperimentSpec.model_validate_json(canonical_json(binding["definition"]))
        except (ValidationError, ValueError, TypeError):
            return "analysis report execution frozen definition is invalid"
        if not (
            spec.frozen
            and spec.experiment_id == report_row["experiment_id"]
            and spec.freeze_hash == report_row["spec_hash"]
            and spec.study_pack_hash == report_row["study_pack_hash"]
        ):
            return "analysis report execution frozen definition does not match stored hashes"
        if (
            manifest.experiment_id != report_row["experiment_id"]
            or manifest.experiment_hash != sha256(binding["definition"])
            or manifest.spec_hash != report_row["spec_hash"]
            or manifest.study_pack_hash != report_row["study_pack_hash"]
        ):
            return "evidence manifest does not match the immutable analysis report frozen binding"
        return None

    def _apply_service_holds(
        self, artifacts: DecisionArtifacts, holds: Mapping[str, str]
    ) -> DecisionArtifacts:
        if not holds:
            return artifacts
        entries = tuple(
            entry.model_copy(
                update={
                    "disposition": (
                        entry.disposition
                        if entry.disposition is ClaimDisposition.REJECTED
                        else ClaimDisposition.HOLD
                    ),
                    "blockers": tuple(
                        dict.fromkeys(
                            (
                                *entry.blockers,
                                *(
                                    f"{reference.receipt_id}: {holds[reference.receipt_id]}"
                                    for reference in entry.evidence_refs
                                    if reference.receipt_id in holds
                                ),
                            )
                        )
                    ),
                }
            )
            for entry in artifacts.ledger.entries
        )
        ledger_body = {
            "schema_version": artifacts.ledger.schema_version,
            "analysis_report_hash": artifacts.ledger.analysis_report_hash,
            "entries": entries,
        }
        ledger = ClaimLedger(**ledger_body, canonical_hash=sha256(ledger_body))
        supported = [
            _CEILING_BY_KIND[entry.kind]
            for entry in entries
            if entry.disposition is ClaimDisposition.SUPPORTED
        ]
        brief_body = artifacts.brief.model_dump(mode="python", exclude={"canonical_hash"})
        brief_body["verdict"] = (
            artifacts.brief.verdict
            if artifacts.brief.verdict is DecisionVerdict.REJECT
            else DecisionVerdict.HOLD
        )
        brief_body["supported_claim_ceiling"] = max(
            supported, key=lambda ceiling: _CEILING_RANK[ceiling], default=ClaimCeiling.NO_CLAIM
        )
        brief_body["blockers"] = tuple(
            dict.fromkeys(
                (*artifacts.brief.blockers, *(f"{receipt_id}: {reason}" for receipt_id, reason in holds.items()))
            )
        )
        brief = DecisionBrief(**brief_body, canonical_hash=sha256(brief_body))
        return DecisionArtifacts(brief=brief, ledger=ledger)

    def _store_artifact(self, content: bytes, artifact_format: str) -> str:
        digest = self.artifact_store.put_bytes(content, media_type="application/json")
        if digest != sha256_bytes(content):
            raise DecisionError("artifact_integrity_error", "The decision artifact digest does not match its canonical bytes.", status_code=409)
        self.repository.register_artifact(
            digest,
            size_bytes=len(content),
            storage_uri=self.artifact_store.uri_for(digest),
            media_type="application/json",
            content_metadata={"format": artifact_format},
        )
        return digest

    @staticmethod
    def _metadata(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "decision_brief_id": row["id"],
            "analysis_report_id": row["analysis_report_id"],
            "experiment_id": row["experiment_id"],
            "execution_id": row["execution_id"],
            "report_digest": row["report_digest"],
            "verdict": row["verdict"],
            "claim_ceiling": row["claim_ceiling"],
            "claim_refs": row["claim_refs"],
            "brief_ref": f"sha256:{row['brief_artifact_digest']}",
            "ledger_ref": f"sha256:{row['ledger_artifact_digest']}",
            "brief_hash": row["brief_hash"],
            "ledger_hash": row["ledger_hash"],
            "artifact_content": "withheld",
            "integrity_not_truth": True,
        }

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise DecisionError("invalid_limit", "The list limit must be an integer from 1 to 100.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise DecisionError("invalid_offset", "The list offset must be a nonnegative integer.")
        return limit, offset
