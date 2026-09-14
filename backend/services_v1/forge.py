"""Provider-free custody services for Arena Forge, planning, and process safety.

Forge has no executor.  It accepts explicit, digest-bound records, evaluates
their contract boundaries, and writes immutable custody artifacts.  It never
opens a sealed holdout, starts a provider, calls a tool, requests a network
operation, applies a patch, or merges a change.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select

from artifacts_v1 import ArtifactIntegrityError, ArtifactStore
from forge_v1 import (
    EvolutionReceipt,
    ForgeApproval,
    ForgeEvaluation,
    ForgeProposal,
    NextBestExperimentReport,
    NextBestExperimentRequest,
    ProcessSafetyReport,
    ProcessSafetyRequest,
)
from persistence_v1 import ArenaRepository
from persistence_v1.schema import (
    artifacts,
    forge_approvals,
    forge_evaluations,
    forge_planner_reports,
    forge_proposals,
    process_safety_reports,
    projects,
)
from protocol_v1.canonical import canonical_json


_PROPOSAL_MEDIA_TYPE = "application/vnd.scaffold-arena.forge-proposal+json"
_APPROVAL_MEDIA_TYPE = "application/vnd.scaffold-arena.forge-approval+json"
_EVALUATION_MEDIA_TYPE = "application/vnd.scaffold-arena.forge-evaluation+json"
_RECEIPT_MEDIA_TYPE = "application/vnd.scaffold-arena.evolution-receipt+json"
_PLANNER_MEDIA_TYPE = "application/vnd.scaffold-arena.next-best-experiment-report+json"
_SAFETY_MEDIA_TYPE = "application/vnd.scaffold-arena.process-safety-report+json"

_FORGE_CEILING = "Arena Forge records product controls only; ADMITTED is a record-only policy outcome and does not execute, merge, establish evidence validity, prove model performance, or provide security assessment or containment proof."
_PLANNER_CEILING = "The planner is a bounded design simulation and value-of-information aid, not an execution, admission, performance, or security claim."
_SAFETY_CEILING = "Process-safety records establish product controls only; they are not a security assessment, containment proof, or evidence that sensitive content was never exposed."
_SENSITIVITY_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3, "SECRET": 4}
_ALLOWED_TRANSITIONS = {
    ("DRAFT", "PENDING_APPROVAL"),
    ("PENDING_APPROVAL", "APPROVED"),
    ("PENDING_APPROVAL", "REJECTED"),
    ("APPROVED", "EVALUATED"),
    ("EVALUATED", "ADMITTED"),
    ("EVALUATED", "REJECTED"),
    ("EVALUATED", "QUARANTINED"),
    ("EVALUATED", "INCONCLUSIVE"),
}


class ForgeError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _bare(value: str, *, code: str = "forge_digest_invalid") -> str:
    value = value.removeprefix("sha256:")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ForgeError(code, "A lowercase SHA-256 digest is required.")
    return value


def _prefixed(value: str) -> str:
    return f"sha256:{value}"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _model(payload: Mapping[str, Any], kind: type[Any], *, code: str) -> Any:
    try:
        return kind.model_validate(payload)
    except (TypeError, ValidationError, ValueError) as exc:
        raise ForgeError(code, "A strict Arena Forge contract is required.") from exc


class ForgeService:
    """Content-addressed project-scoped custody for proposals, approvals, and receipts."""

    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def _project(self, project_id: str | None) -> str:
        project = project_id or self.personal_project_id
        if not project:
            raise ForgeError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            if conn.execute(select(projects.c.id).where(projects.c.id == project)).scalar_one_or_none() is None:
                raise ForgeError("unknown_project", "The supplied project does not exist.", status_code=404)
        return project

    def _store(self, raw: Mapping[str, Any], *, media_type: str, kind: str) -> tuple[str, bytes]:
        content = canonical_json(raw)
        digest = hashlib.sha256(content).hexdigest()
        try:
            stored = self.artifact_store.put_bytes(content, media_type=media_type, metadata={"kind": kind})
        except (ArtifactIntegrityError, OSError, ValueError) as exc:
            raise ForgeError("forge_artifact_unavailable", "The immutable custody artifact could not be stored.", status_code=503) from exc
        if stored != digest:
            raise ForgeError("forge_artifact_integrity", "The immutable custody artifact failed its digest check.", status_code=500)
        return digest, content

    def _register_artifact(self, conn: Any, *, digest: str, content: bytes, media_type: str, kind: str) -> None:
        if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none() is None:
            conn.execute(insert(artifacts).values(
                digest=digest,
                size_bytes=len(content),
                storage_uri=self.artifact_store.uri_for(digest),
                media_type=media_type,
                metadata_json={"kind": kind},
            ))

    def _read_model(self, digest: str, kind: type[Any], *, code: str) -> Any:
        try:
            return kind.model_validate_json(self.artifact_store.get_bytes(digest))
        except (ArtifactIntegrityError, FileNotFoundError, OSError, ValidationError, ValueError) as exc:
            raise ForgeError(code, "The immutable custody artifact could not be recovered.", status_code=500) from exc

    @staticmethod
    def _proposal_public(proposal: ForgeProposal, *, digest: str, state: str, idempotent: bool) -> dict[str, Any]:
        return {
            "proposal_id": proposal.proposal_id,
            "proposal_digest": _prefixed(digest),
            "proposal_artifact_digest": _prefixed(digest),
            "state": state,
            "proposal": proposal.model_dump(mode="json"),
            "claim_ceiling": _FORGE_CEILING,
            "execution_started": False,
            "automatic_merge": False,
            "idempotent_replay": idempotent,
        }

    def create_proposal(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        proposal = _model(payload, ForgeProposal, code="forge_proposal_invalid")
        raw = proposal.model_dump(mode="json")
        digest, content = self._store(raw, media_type=_PROPOSAL_MEDIA_TYPE, kind="forge-proposal")
        with self.repository.transaction(immediate=True) as conn:
            prior = conn.execute(select(forge_proposals).where(
                forge_proposals.c.project_id == project,
                forge_proposals.c.proposal_digest == digest,
            )).mappings().one_or_none()
            if prior is not None:
                return self._proposal_public(proposal, digest=digest, state=prior["state"], idempotent=True)
            self._register_artifact(conn, digest=digest, content=content, media_type=_PROPOSAL_MEDIA_TYPE, kind="forge-proposal")
            conn.execute(insert(forge_proposals).values(
                id=uuid.uuid4().hex,
                project_id=project,
                proposal_digest=digest,
                proposal_artifact_digest=digest,
                proposer_identity=proposal.proposer_identity,
                base_genome_digest=_bare(proposal.base_genome_digest),
                candidate_genome_digest=_bare(proposal.candidate_genome_digest),
                mechanism_id=proposal.mechanism_change.mechanism_id,
                state="PENDING_APPROVAL",
                claim_scope=proposal.requested_claim_scope,
            ))
        return self._proposal_public(proposal, digest=digest, state="PENDING_APPROVAL", idempotent=False)

    def proposal(self, proposal_digest: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        digest = _bare(proposal_digest)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(forge_proposals).where(
                forge_proposals.c.project_id == project,
                forge_proposals.c.proposal_digest == digest,
            )).mappings().one_or_none()
        if row is None:
            raise ForgeError("forge_proposal_not_found", "The proposal was not found.", status_code=404)
        proposal = self._read_model(row["proposal_artifact_digest"], ForgeProposal, code="forge_proposal_artifact_invalid")
        return self._proposal_public(proposal, digest=digest, state=row["state"], idempotent=False)

    @staticmethod
    def _approval_public(approval: ForgeApproval, *, digest: str, proposal_digest: str, idempotent: bool) -> dict[str, Any]:
        return {
            "proposal_digest": _prefixed(proposal_digest),
            "approval_digest": _prefixed(digest),
            "approval_artifact_digest": _prefixed(digest),
            "decision": approval.decision,
            "authority_kind": approval.authority_kind,
            "approver_identity": approval.approver_identity,
            "execution_authorized": False,
            "merge_authorized": False,
            "idempotent_replay": idempotent,
        }

    def approve(self, proposal_digest: str, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        bare_proposal = _bare(proposal_digest)
        approval = _model(payload, ForgeApproval, code="forge_approval_invalid")
        if _bare(approval.proposal_digest) != bare_proposal:
            raise ForgeError("forge_approval_proposal_mismatch", "The approval must bind the URL proposal digest.")
        with self.repository.engine.connect() as conn:
            proposal_row = conn.execute(select(forge_proposals).where(
                forge_proposals.c.project_id == project,
                forge_proposals.c.proposal_digest == bare_proposal,
            )).mappings().one_or_none()
        if proposal_row is None:
            raise ForgeError("forge_proposal_not_found", "The proposal was not found.", status_code=404)
        proposal = self._read_model(proposal_row["proposal_artifact_digest"], ForgeProposal, code="forge_proposal_artifact_invalid")
        if approval.approver_identity == proposal.proposer_identity:
            raise ForgeError("forge_self_approval_forbidden", "A proposer cannot approve its own candidate.", status_code=403)
        raw = approval.model_dump(mode="json")
        approval_digest, content = self._store(raw, media_type=_APPROVAL_MEDIA_TYPE, kind="forge-approval")
        with self.repository.transaction(immediate=True) as conn:
            prior = conn.execute(select(forge_approvals).where(
                forge_approvals.c.project_id == project,
                forge_approvals.c.proposal_digest == bare_proposal,
            )).mappings().one_or_none()
            if prior is not None:
                if prior["approval_artifact_digest"] != approval_digest:
                    raise ForgeError("forge_approval_immutable", "A proposal already has an immutable owner decision.", status_code=409)
                return self._approval_public(approval, digest=approval_digest, proposal_digest=bare_proposal, idempotent=True)
            self._register_artifact(conn, digest=approval_digest, content=content, media_type=_APPROVAL_MEDIA_TYPE, kind="forge-approval")
            conn.execute(insert(forge_approvals).values(
                id=uuid.uuid4().hex,
                project_id=project,
                proposal_digest=bare_proposal,
                approval_artifact_digest=approval_digest,
                approver_identity=approval.approver_identity,
                decision=approval.decision,
            ))
            conn.execute(forge_proposals.update().where(
                forge_proposals.c.project_id == project,
                forge_proposals.c.proposal_digest == bare_proposal,
            ).values(state="APPROVED" if approval.decision == "APPROVED" else "REJECTED"))
        return self._approval_public(approval, digest=approval_digest, proposal_digest=bare_proposal, idempotent=False)

    def _approved_proposal(self, project: str, proposal_digest: str) -> tuple[ForgeProposal, Mapping[str, Any], Mapping[str, Any]]:
        with self.repository.engine.connect() as conn:
            proposal_row = conn.execute(select(forge_proposals).where(
                forge_proposals.c.project_id == project,
                forge_proposals.c.proposal_digest == proposal_digest,
            )).mappings().one_or_none()
            approval_row = conn.execute(select(forge_approvals).where(
                forge_approvals.c.project_id == project,
                forge_approvals.c.proposal_digest == proposal_digest,
            )).mappings().one_or_none()
        if proposal_row is None:
            raise ForgeError("forge_proposal_not_found", "The proposal was not found.", status_code=404)
        if approval_row is None or approval_row["decision"] != "APPROVED":
            raise ForgeError("forge_approval_required", "An immutable owner or policy approval is required before evaluation.", status_code=409)
        proposal = self._read_model(proposal_row["proposal_artifact_digest"], ForgeProposal, code="forge_proposal_artifact_invalid")
        return proposal, proposal_row, approval_row

    def _process_safety_passes(self, project: str, digest: str) -> bool:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(process_safety_reports).where(
                process_safety_reports.c.project_id == project,
                process_safety_reports.c.report_artifact_digest == digest,
            )).mappings().one_or_none()
        return row is not None and row["verdict"] == "PASS"

    def create_evaluation(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        evaluation = _model(payload, ForgeEvaluation, code="forge_evaluation_invalid")
        proposal_digest = _bare(evaluation.proposal_digest)
        proposal, _, approval_row = self._approved_proposal(project, proposal_digest)
        if evaluation.evaluator_identity == proposal.proposer_identity:
            raise ForgeError("forge_evaluator_proposer_conflict", "The evaluator must be distinct from the proposer.", status_code=403)
        if evaluation.admission.admitting_identity in {proposal.proposer_identity, evaluation.evaluator_identity}:
            raise ForgeError("forge_admitter_separation_required", "The admitting human or policy must be distinct from proposer and evaluator.", status_code=403)
        if evaluation.outcome == "ADMITTED" and any(failure.severity == "severe" or failure.disposition == "blocks_admission" for failure in evaluation.failures):
            raise ForgeError("forge_admission_blocked_by_failure", "Severe retained failures block admission.", status_code=409)
        safety_digest = _bare(evaluation.process_safety_report_digest)
        if not self._process_safety_passes(project, safety_digest):
            raise ForgeError("forge_process_safety_required", "A project-scoped PASS process-safety report is required before an Evolution Receipt.", status_code=409)
        evaluation_raw = evaluation.model_dump(mode="json")
        evaluation_digest, evaluation_content = self._store(evaluation_raw, media_type=_EVALUATION_MEDIA_TYPE, kind="forge-evaluation")
        receipt_raw = {
            "schema_version": "scaffold-arena.evolution-receipt/1",
            "receipt_id": f"receipt-{evaluation_digest[:24]}",
            "proposal_digest": _prefixed(proposal_digest),
            "approval_digest": _prefixed(approval_row["approval_artifact_digest"]),
            "evaluation_digest": _prefixed(evaluation_digest),
            "outcome": evaluation.outcome,
            "evaluator_identity": evaluation.evaluator_identity,
            "admitting_identity": evaluation.admission.admitting_identity,
            "claim_ceiling": _FORGE_CEILING,
            "immutable": True,
            "execution_started": False,
            "automatic_merge": False,
        }
        receipt_digest, receipt_content = self._store(receipt_raw, media_type=_RECEIPT_MEDIA_TYPE, kind="evolution-receipt")
        public_raw = {
            **receipt_raw,
            "receipt_digest": _prefixed(receipt_digest),
            "receipt_artifact_digest": _prefixed(receipt_digest),
            "idempotent_replay": False,
        }
        receipt = _model(public_raw, EvolutionReceipt, code="forge_receipt_invalid")
        with self.repository.transaction(immediate=True) as conn:
            prior = conn.execute(select(forge_evaluations).where(
                forge_evaluations.c.project_id == project,
                forge_evaluations.c.evaluation_digest == evaluation_digest,
            )).mappings().one_or_none()
            if prior is not None:
                if prior["receipt_artifact_digest"] != receipt_digest:
                    raise ForgeError("forge_receipt_conflict", "An immutable Evolution Receipt already exists for this evaluation.", status_code=409)
                return receipt.model_copy(update={"idempotent_replay": True}).model_dump(mode="json")
            transition = conn.execute(forge_proposals.update().where(
                forge_proposals.c.project_id == project,
                forge_proposals.c.proposal_digest == proposal_digest,
                forge_proposals.c.state == "APPROVED",
            ).values(state=evaluation.outcome))
            if transition.rowcount != 1:
                raise ForgeError(
                    "forge_proposal_not_approved",
                    "The proposal must remain APPROVED when its Evolution Receipt is recorded.",
                    status_code=409,
                )
            self._register_artifact(conn, digest=evaluation_digest, content=evaluation_content, media_type=_EVALUATION_MEDIA_TYPE, kind="forge-evaluation")
            self._register_artifact(conn, digest=receipt_digest, content=receipt_content, media_type=_RECEIPT_MEDIA_TYPE, kind="evolution-receipt")
            conn.execute(insert(forge_evaluations).values(
                id=uuid.uuid4().hex,
                project_id=project,
                proposal_digest=proposal_digest,
                evaluation_digest=evaluation_digest,
                evaluation_artifact_digest=evaluation_digest,
                receipt_artifact_digest=receipt_digest,
                evaluator_identity=evaluation.evaluator_identity,
                outcome=evaluation.outcome,
                process_safety_report_digest=safety_digest,
            ))
        return receipt.model_dump(mode="json")

    def receipt(self, receipt_digest: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        digest = _bare(receipt_digest)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(forge_evaluations).where(
                forge_evaluations.c.project_id == project,
                forge_evaluations.c.receipt_artifact_digest == digest,
            )).mappings().one_or_none()
        if row is None:
            raise ForgeError("evolution_receipt_not_found", "The Evolution Receipt was not found.", status_code=404)
        try:
            raw = json.loads(self.artifact_store.get_bytes(digest))
            if not isinstance(raw, Mapping):
                raise TypeError("Evolution Receipt must contain a JSON object")
            value = {
                **raw,
                "receipt_digest": _prefixed(digest),
                "receipt_artifact_digest": _prefixed(digest),
                "idempotent_replay": False,
            }
            return EvolutionReceipt.model_validate(value).model_dump(mode="json")
        except (ArtifactIntegrityError, FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValidationError, ValueError) as exc:
            raise ForgeError("evolution_receipt_artifact_invalid", "The Evolution Receipt could not be recovered.", status_code=500) from exc


class ExperimentPlannerService:
    """Constrained design simulation. It ranks input designs and performs no work."""

    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def _project(self, project_id: str | None) -> str:
        project = project_id or self.personal_project_id
        if not project:
            raise ForgeError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            if conn.execute(select(projects.c.id).where(projects.c.id == project)).scalar_one_or_none() is None:
                raise ForgeError("unknown_project", "The supplied project does not exist.", status_code=404)
        return project

    @staticmethod
    def _raw(request: NextBestExperimentRequest) -> dict[str, Any]:
        mechanisms = {item.mechanism_id: item for item in request.mechanisms}
        coverage = {item.coverage_id: item for item in request.coverage}
        prior: dict[str, list[float]] = {}
        for item in request.prior_evidence:
            prior.setdefault(item.mechanism_id, []).append(item.evidence_strength)
        recommendations: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for design in request.candidate_designs:
            mechanism = mechanisms[design.mechanism_id]
            max_affordable = math.floor(request.remaining_budget_usd / design.cost_per_attempt_usd)
            if design.risk > request.maximum_risk:
                excluded.append({"design_id": design.design_id, "reason": "Design risk exceeds the declared maximum."})
                continue
            if max_affordable < design.minimum_attempts:
                excluded.append({"design_id": design.design_id, "reason": "Remaining budget cannot fund the minimum attempt count."})
                continue
            signal = max(mechanism.expected_effect, 1e-12)
            attempts = math.ceil(design.minimum_attempts * (request.minimum_detectable_effect / signal) ** 2)
            attempts = min(max(design.minimum_attempts, attempts), design.maximum_attempts, max_affordable)
            if attempts < design.minimum_attempts:
                excluded.append({"design_id": design.design_id, "reason": "Minimum detectable effect cannot be assessed inside the remaining budget."})
                continue
            selected_coverage = [coverage[item].fraction for item in design.coverage_ids]
            coverage_fraction = math.fsum(selected_coverage) / len(selected_coverage)
            evidence_strengths = prior.get(design.mechanism_id, [])
            prior_strength = math.fsum(evidence_strengths) / len(evidence_strengths) if evidence_strengths else 0.0
            residual_uncertainty = mechanism.uncertainty * (1.0 - 0.5 * prior_strength)
            information_gain = residual_uncertainty * coverage_fraction * min(1.0, signal / request.minimum_detectable_effect) * (1.0 - 0.5 * mechanism.interaction_uncertainty)
            upper_attempts = min(design.maximum_attempts, max_affordable)
            recommendations.append({
                "proposed_design": design.model_dump(mode="json"),
                "expected_information_gain": max(0.0, information_gain),
                "attempts": attempts,
                "cost_interval": {"lower_usd": attempts * design.cost_per_attempt_usd, "upper_usd": upper_attempts * design.cost_per_attempt_usd},
                "risk": design.risk,
                "assumptions": list(design.assumptions),
            })
        recommendations.sort(key=lambda item: (-item["expected_information_gain"], item["risk"], item["cost_interval"]["lower_usd"], item["proposed_design"]["design_id"]))
        ids = [item["proposed_design"]["design_id"] for item in recommendations]
        for index, item in enumerate(recommendations, start=1):
            item["rank"] = index
            item["alternatives"] = [candidate for candidate in ids if candidate != item["proposed_design"]["design_id"]]
            item["claim_ceiling"] = _PLANNER_CEILING
        raw = {
            "schema_version": "scaffold-arena.next-best-experiment-report/1",
            "report_id": f"plan-{_digest(request)[:24]}",
            "request_digest": _prefixed(_digest(request)),
            "mode": request.mode,
            "verdict": "READY" if recommendations else "HOLD",
            "recommendations": recommendations,
            "excluded_designs": excluded,
            "claim_ceiling": _PLANNER_CEILING,
            "execution_started": False,
            "network_requested": False,
        }
        return raw

    @staticmethod
    def _public(raw: Mapping[str, Any], *, digest: str, idempotent: bool) -> dict[str, Any]:
        value = {
            **raw,
            "report_digest": _prefixed(digest),
            "report_artifact_digest": _prefixed(digest),
            "idempotent_replay": idempotent,
        }
        return _model(value, NextBestExperimentReport, code="planner_report_invalid").model_dump(mode="json")

    def local_report(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = _model(payload, NextBestExperimentRequest, code="planner_request_invalid")
        raw = self._raw(request)
        return self._public(raw, digest=_digest(raw), idempotent=False)

    def create(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        request = _model(payload, NextBestExperimentRequest, code="planner_request_invalid")
        raw = self._raw(request)
        request_digest = _digest(request)
        content = canonical_json(raw)
        digest = hashlib.sha256(content).hexdigest()
        try:
            stored = self.artifact_store.put_bytes(content, media_type=_PLANNER_MEDIA_TYPE, metadata={"kind": "next-best-experiment-report"})
        except (ArtifactIntegrityError, OSError, ValueError) as exc:
            raise ForgeError("planner_artifact_unavailable", "The planner report could not be stored.", status_code=503) from exc
        if stored != digest:
            raise ForgeError("planner_artifact_integrity", "The planner report failed its digest check.", status_code=500)
        with self.repository.transaction(immediate=True) as conn:
            prior = conn.execute(select(forge_planner_reports).where(
                forge_planner_reports.c.project_id == project,
                forge_planner_reports.c.request_digest == request_digest,
            )).mappings().one_or_none()
            if prior is not None:
                if prior["report_artifact_digest"] != digest:
                    raise ForgeError("planner_report_conflict", "An immutable planner report already exists for this request.", status_code=409)
                return self._public(raw, digest=digest, idempotent=True)
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=digest, size_bytes=len(content), storage_uri=self.artifact_store.uri_for(digest), media_type=_PLANNER_MEDIA_TYPE, metadata_json={"kind": "next-best-experiment-report"}))
            conn.execute(insert(forge_planner_reports).values(
                id=uuid.uuid4().hex,
                project_id=project,
                request_digest=request_digest,
                report_artifact_digest=digest,
                mode=request.mode,
                verdict=raw["verdict"],
            ))
        return self._public(raw, digest=digest, idempotent=False)

    def report(self, report_digest: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        digest = _bare(report_digest)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(forge_planner_reports).where(
                forge_planner_reports.c.project_id == project,
                forge_planner_reports.c.report_artifact_digest == digest,
            )).mappings().one_or_none()
        if row is None:
            raise ForgeError("planner_report_not_found", "The planner report was not found.", status_code=404)
        try:
            raw = json.loads(self.artifact_store.get_bytes(digest))
        except (ArtifactIntegrityError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise ForgeError("planner_report_artifact_invalid", "The planner report could not be recovered.", status_code=500) from exc
        return self._public(raw, digest=digest, idempotent=False)


class ProcessSafetyService:
    """Fail-closed information-flow checks over digest-only records."""

    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def _project(self, project_id: str | None) -> str:
        project = project_id or self.personal_project_id
        if not project:
            raise ForgeError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            if conn.execute(select(projects.c.id).where(projects.c.id == project)).scalar_one_or_none() is None:
                raise ForgeError("unknown_project", "The supplied project does not exist.", status_code=404)
        return project

    @staticmethod
    def _check(check_id: str, verdict: str, detail: str) -> dict[str, str]:
        return {"check_id": check_id, "verdict": verdict, "detail": detail}

    @classmethod
    def _raw(cls, request: ProcessSafetyRequest) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        maximum = _SENSITIVITY_RANK[request.policy.maximum_sensitivity]
        too_sensitive = [flow for flow in request.flows if _SENSITIVITY_RANK[flow.sensitivity] > maximum]
        checks.append(cls._check("data_scope", "FAIL" if too_sensitive else "PASS", "A flow exceeds the declared sensitivity scope." if too_sensitive else "Every flow is within the declared sensitivity scope."))
        tool_flows = [flow for flow in request.flows if "tool" in {flow.source, flow.destination}]
        prohibited_tools = [flow for flow in tool_flows if flow.tool_digest is None or flow.tool_digest not in request.policy.allowed_tool_digests]
        checks.append(cls._check("tool_allowlist", "FAIL" if prohibited_tools else "PASS", "A tool flow lacks an allowlisted tool digest." if prohibited_tools else "Every declared tool flow is allowlisted."))
        egress = [flow for flow in request.flows if flow.destination == "external"]
        checks.append(cls._check("network_egress", "FAIL" if egress else "PASS", "External destination is forbidden by this policy." if egress else "No external destination is declared."))
        too_deep = [flow for flow in request.flows if flow.delegation_depth > request.policy.maximum_delegation_depth]
        checks.append(cls._check("delegation_depth", "FAIL" if too_deep else "PASS", "A flow exceeds the declared delegation depth." if too_deep else "Every flow is within the declared delegation depth."))
        secret_escape = [flow for flow in request.flows if flow.sensitivity == "SECRET" and flow.destination != "artifact"]
        checks.append(cls._check("secret_handling", "FAIL" if secret_escape else "PASS", "Secret-labelled content may be retained only as a redacted artifact manifest." if secret_escape else "Sensitive records retain digests and redacted manifests only."))
        invalid_transitions = [transition for transition in request.transitions if (transition.from_state, transition.to_state) not in _ALLOWED_TRANSITIONS]
        checks.append(cls._check("plan_transitions", "FAIL" if invalid_transitions else "PASS", "An unsafe plan transition was requested." if invalid_transitions else "Every requested plan transition remains in the approval and evaluation state machine."))
        for outcome in request.outcomes:
            verdict = "FAIL" if outcome.state == "DETECTED" else "HOLD" if outcome.state == "UNKNOWN" else "PASS"
            checks.append(cls._check(f"outcome-{outcome.outcome_type}", verdict, "The typed outcome was detected." if verdict == "FAIL" else "The typed outcome remains unknown." if verdict == "HOLD" else "The typed outcome is absent or was blocked by policy."))
        verdict = "FAIL" if any(item["verdict"] == "FAIL" for item in checks) else "HOLD" if any(item["verdict"] == "HOLD" for item in checks) else "PASS"
        manifests = sorted({
            item
            for flow in request.flows
            for item in (flow.content_digest, flow.redacted_manifest_digest, flow.tool_digest)
            if item is not None
        } | {request.source_manifest_digest, request.policy.policy_digest} | ({request.cleanup_receipt_digest} if request.cleanup_receipt_digest else set()))
        return {
            "schema_version": "scaffold-arena.process-safety-report/1",
            "report_id": f"safety-{_digest(request)[:24]}",
            "request_digest": _prefixed(_digest(request)),
            "verdict": verdict,
            "checks": checks,
            "retained_manifest_digests": manifests,
            "claim_ceiling": _SAFETY_CEILING,
            "raw_sensitive_content_retained": False,
            "execution_started": False,
            "network_requested": False,
        }

    @staticmethod
    def _public(raw: Mapping[str, Any], *, digest: str, idempotent: bool) -> dict[str, Any]:
        value = {**raw, "report_digest": _prefixed(digest), "report_artifact_digest": _prefixed(digest), "idempotent_replay": idempotent}
        return _model(value, ProcessSafetyReport, code="process_safety_report_invalid").model_dump(mode="json")

    def local_report(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = _model(payload, ProcessSafetyRequest, code="process_safety_request_invalid")
        raw = self._raw(request)
        return self._public(raw, digest=_digest(raw), idempotent=False)

    def create(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        request = _model(payload, ProcessSafetyRequest, code="process_safety_request_invalid")
        raw = self._raw(request)
        request_digest = _digest(request)
        content = canonical_json(raw)
        digest = hashlib.sha256(content).hexdigest()
        try:
            stored = self.artifact_store.put_bytes(content, media_type=_SAFETY_MEDIA_TYPE, metadata={"kind": "process-safety-report"})
        except (ArtifactIntegrityError, OSError, ValueError) as exc:
            raise ForgeError("process_safety_artifact_unavailable", "The process-safety report could not be stored.", status_code=503) from exc
        if stored != digest:
            raise ForgeError("process_safety_artifact_integrity", "The process-safety report failed its digest check.", status_code=500)
        with self.repository.transaction(immediate=True) as conn:
            prior = conn.execute(select(process_safety_reports).where(
                process_safety_reports.c.project_id == project,
                process_safety_reports.c.request_digest == request_digest,
            )).mappings().one_or_none()
            if prior is not None:
                if prior["report_artifact_digest"] != digest:
                    raise ForgeError("process_safety_report_conflict", "An immutable process-safety report already exists for this request.", status_code=409)
                return self._public(raw, digest=digest, idempotent=True)
            if conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none() is None:
                conn.execute(insert(artifacts).values(digest=digest, size_bytes=len(content), storage_uri=self.artifact_store.uri_for(digest), media_type=_SAFETY_MEDIA_TYPE, metadata_json={"kind": "process-safety-report"}))
            conn.execute(insert(process_safety_reports).values(
                id=uuid.uuid4().hex,
                project_id=project,
                request_digest=request_digest,
                report_artifact_digest=digest,
                verdict=raw["verdict"],
                policy_digest=_bare(request.policy.policy_digest),
            ))
        return self._public(raw, digest=digest, idempotent=False)

    def report(self, report_digest: str, *, project_id: str | None) -> dict[str, Any]:
        project = self._project(project_id)
        digest = _bare(report_digest)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(process_safety_reports).where(
                process_safety_reports.c.project_id == project,
                process_safety_reports.c.report_artifact_digest == digest,
            )).mappings().one_or_none()
        if row is None:
            raise ForgeError("process_safety_report_not_found", "The process-safety report was not found.", status_code=404)
        try:
            raw = json.loads(self.artifact_store.get_bytes(digest))
        except (ArtifactIntegrityError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise ForgeError("process_safety_report_artifact_invalid", "The process-safety report could not be recovered.", status_code=500) from exc
        return self._public(raw, digest=digest, idempotent=False)
