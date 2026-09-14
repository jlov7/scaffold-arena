"""Fail-closed, immutable decision briefs and claim ledgers for Analysis v1.

This module only interprets a completed :class:`AnalysisReport`.  It does not
load receipts, execute analysis, or promote evidence.  Receipt references are
content-addressed declarations supplied by the caller; a maturity label is
never sufficient unless its immutable receipt is explicitly linked to the
claim and to the input report.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from protocol_v1.canonical import canonical_json

from .decision import CostStatus
from .engine import AnalysisReport, EffectReport


class ClaimModel(BaseModel):
    """Strict, finite, immutable contracts for claim interpretation."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, allow_inf_nan=False
    )


class EvidenceMaturity(StrEnum):
    FIXTURE = "fixture"
    LOCAL_LIVE = "local_live"
    REPLICATED = "replicated"
    CROSS_MODEL = "cross_model"
    HUMAN_CALIBRATED = "human_calibrated"
    INDEPENDENT = "independent"


class ClaimKind(StrEnum):
    FIXTURE_OBSERVATION = "fixture_observation"
    LOCAL_LIVE_OBSERVATION = "local_live_observation"
    CAUSAL_EFFECT = "causal_effect"
    GENERALIZED_EFFECT = "generalized_effect"
    COST_COMPARISON = "cost_comparison"
    PARETO_COMPARISON = "pareto_comparison"
    CROSS_MODEL_REPLICATION = "cross_model_replication"
    HUMAN_CALIBRATED_ASSESSMENT = "human_calibrated_assessment"
    INDEPENDENT_VALIDATION = "independent_validation"


class ClaimCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    FIXTURE_ONLY = "fixture_only"
    LOCAL_LIVE_ONLY = "local_live_only"
    CONFIRMATORY_ANALYSIS = "confirmatory_analysis"
    REPLICATED = "replicated"
    CROSS_MODEL = "cross_model"
    HUMAN_CALIBRATED = "human_calibrated"
    INDEPENDENT = "independent"


class ClaimDisposition(StrEnum):
    SUPPORTED = "SUPPORTED"
    HOLD = "HOLD"
    REJECTED = "REJECTED"


class DecisionVerdict(StrEnum):
    PASS = "PASS"
    HOLD = "HOLD"
    REJECT = "REJECT"


class EvidenceReceiptReference(ClaimModel):
    """An immutable receipt explicitly bound to one AnalysisReport hash."""

    receipt_id: str = Field(min_length=1)
    maturity: EvidenceMaturity
    immutable: Literal[True] = True
    receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_ref: str = Field(min_length=1)


class RiskConstraints(ClaimModel):
    """Risk policy may narrow outcomes; it cannot waive hard evidence gates."""

    severe_failure_disposition: Literal["HOLD", "REJECT"] = "HOLD"
    require_zero_exclusions: Literal[True] = True
    require_estimated_effect_for_effect_claims: Literal[True] = True
    maximum_claim_ceiling: ClaimCeiling = ClaimCeiling.INDEPENDENT


class ProposedClaim(ClaimModel):
    """A requested claim with exact, immutable receipt links.

    The request deliberately contains no score, adequacy, exclusion, estimate,
    severe-failure, or ceiling fields.  Those values are always derived from
    the immutable report and the engine's hard gates.
    """

    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    kind: ClaimKind
    linked_receipt_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("linked_receipt_ids")
    @classmethod
    def unique_receipt_links(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(not item for item in value):
            raise ValueError("linked receipt ids must be non-empty and unique")
        return value


class DecisionAdmissionRequest(ClaimModel):
    """Public API admission contract for a service-derived Analysis v1 decision."""

    analysis_report_id: str | None = Field(default=None, min_length=1)
    experiment_id: str | None = Field(default=None, min_length=1)
    execution_id: str | None = Field(default=None, min_length=1)
    risk_constraints: RiskConstraints
    proposed_claims: tuple[ProposedClaim, ...] = Field(min_length=1)

    @field_validator("risk_constraints", mode="before")
    @classmethod
    def validate_risk_constraints_json(cls, value: object) -> RiskConstraints:
        if isinstance(value, RiskConstraints):
            return value
        return RiskConstraints.model_validate_json(canonical_json(value))

    @field_validator("proposed_claims", mode="before")
    @classmethod
    def validate_proposed_claims_json(cls, value: object) -> tuple[ProposedClaim, ...]:
        if not isinstance(value, list):
            return value  # type: ignore[return-value]
        return tuple(
            claim
            if isinstance(claim, ProposedClaim)
            else ProposedClaim.model_validate_json(canonical_json(claim))
            for claim in value
        )

    @model_validator(mode="after")
    def validate_selector(self) -> DecisionAdmissionRequest:
        if self.analysis_report_id is not None:
            if self.experiment_id is not None or self.execution_id is not None:
                raise ValueError("analysis_report_id cannot be combined with experiment_id or execution_id")
            return self
        if self.experiment_id is None or self.execution_id is None:
            raise ValueError("provide analysis_report_id or both experiment_id and execution_id")
        return self


class DecisionRequest(ClaimModel):
    """All inputs to the pure decision engine, bound before interpretation."""

    analysis_report: AnalysisReport
    evidence_receipts: tuple[EvidenceReceiptReference, ...] = Field(min_length=1)
    risk_constraints: RiskConstraints = Field(default_factory=RiskConstraints)
    proposed_claims: tuple[ProposedClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_links(self) -> DecisionRequest:
        report_body = self.analysis_report.model_dump(
            mode="json", exclude={"canonical_hash"}
        )
        if _canonical_hash(report_body) != self.analysis_report.canonical_hash:
            raise ValueError("analysis report canonical hash does not match its content")
        receipt_ids = [receipt.receipt_id for receipt in self.evidence_receipts]
        if len(set(receipt_ids)) != len(receipt_ids):
            raise ValueError("evidence receipt ids must be unique")
        if any(
            receipt.analysis_report_hash != self.analysis_report.canonical_hash
            for receipt in self.evidence_receipts
        ):
            raise ValueError("every evidence receipt must bind to the analysis report hash")
        claim_ids = [claim.claim_id for claim in self.proposed_claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("proposed claim ids must be unique")
        known_receipts = set(receipt_ids)
        for claim in self.proposed_claims:
            if any(item not in known_receipts for item in claim.linked_receipt_ids):
                raise ValueError("every proposed claim must link known evidence receipts")
        return self


class OutcomeVector(ClaimModel):
    included_attempt_count: int = Field(ge=0)
    profile_count: int = Field(ge=0)
    estimated_effect_count: int = Field(ge=0)
    held_effect_count: int = Field(ge=0)
    severe_failure_events: int = Field(ge=0)
    excluded_attempt_count: int = Field(ge=0)
    unknown_cost_profile_ids: tuple[str, ...]
    profiles: tuple[ProfileOutcome, ...]


class ProfileOutcome(ClaimModel):
    profile_id: str
    pass_at_1: float | None
    pass_power_k: float | None
    severe_failure_rate: float | None
    auditability: float | None
    latency_seconds: float | None
    cost_status: CostStatus
    cost_usd: float | None


class ClaimLedgerEntry(ClaimModel):
    claim_id: str
    statement: str
    kind: ClaimKind
    evidence_refs: tuple[EvidenceReceiptReference, ...]
    analysis_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    disposition: ClaimDisposition
    limitations: tuple[str, ...]
    falsifiers: tuple[str, ...]
    blockers: tuple[str, ...]


class ClaimLedger(ClaimModel):
    schema_version: Literal["claim-ledger-v1"] = "claim-ledger-v1"
    analysis_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    entries: tuple[ClaimLedgerEntry, ...]
    canonical_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class DecisionBrief(ClaimModel):
    schema_version: Literal["decision-brief-v1"] = "decision-brief-v1"
    analysis_report_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    verdict: DecisionVerdict
    severe_failures: tuple[tuple[str, int], ...]
    outcome_vector: OutcomeVector
    uncertainty: tuple[str, ...]
    exclusions: tuple[tuple[str, str], ...]
    supported_claim_ceiling: ClaimCeiling
    blockers: tuple[str, ...]
    next_lawful_action: str
    canonical_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class DecisionArtifacts(ClaimModel):
    """The paired, hash-stable outputs of one immutable decision request."""

    brief: DecisionBrief
    ledger: ClaimLedger


_REQUIRED_MATURITY: dict[ClaimKind, EvidenceMaturity] = {
    ClaimKind.FIXTURE_OBSERVATION: EvidenceMaturity.FIXTURE,
    ClaimKind.LOCAL_LIVE_OBSERVATION: EvidenceMaturity.LOCAL_LIVE,
    ClaimKind.CAUSAL_EFFECT: EvidenceMaturity.LOCAL_LIVE,
    ClaimKind.GENERALIZED_EFFECT: EvidenceMaturity.REPLICATED,
    ClaimKind.COST_COMPARISON: EvidenceMaturity.LOCAL_LIVE,
    ClaimKind.PARETO_COMPARISON: EvidenceMaturity.LOCAL_LIVE,
    ClaimKind.CROSS_MODEL_REPLICATION: EvidenceMaturity.CROSS_MODEL,
    ClaimKind.HUMAN_CALIBRATED_ASSESSMENT: EvidenceMaturity.HUMAN_CALIBRATED,
    ClaimKind.INDEPENDENT_VALIDATION: EvidenceMaturity.INDEPENDENT,
}

_CEILING_FOR_KIND: dict[ClaimKind, ClaimCeiling] = {
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

_CEILING_RANK: dict[ClaimCeiling, int] = {
    ClaimCeiling.NO_CLAIM: 0,
    ClaimCeiling.FIXTURE_ONLY: 1,
    ClaimCeiling.LOCAL_LIVE_ONLY: 2,
    ClaimCeiling.CONFIRMATORY_ANALYSIS: 3,
    ClaimCeiling.REPLICATED: 4,
    ClaimCeiling.CROSS_MODEL: 5,
    ClaimCeiling.HUMAN_CALIBRATED: 6,
    ClaimCeiling.INDEPENDENT: 7,
}


def build_decision_artifacts(request: DecisionRequest) -> DecisionArtifacts:
    """Return a deterministic brief and ledger without mutating any input."""
    receipts = {receipt.receipt_id: receipt for receipt in request.evidence_receipts}
    facts = _report_facts(request.analysis_report)
    entries = tuple(
        _evaluate_claim(claim, receipts, request, facts)
        for claim in sorted(request.proposed_claims, key=lambda item: item.claim_id)
    )
    ledger_body: dict[str, Any] = {
        "schema_version": "claim-ledger-v1",
        "analysis_report_hash": request.analysis_report.canonical_hash,
        "entries": entries,
    }
    ledger = ClaimLedger(
        **ledger_body,
        canonical_hash=_canonical_hash(ledger_body),
    )
    brief_body = _brief_body(request, facts, entries)
    brief = DecisionBrief(
        **brief_body,
        canonical_hash=_canonical_hash(brief_body),
    )
    return DecisionArtifacts(brief=brief, ledger=ledger)


def _evaluate_claim(
    claim: ProposedClaim,
    receipts: dict[str, EvidenceReceiptReference],
    request: DecisionRequest,
    facts: _ReportFacts,
) -> ClaimLedgerEntry:
    linked = tuple(receipts[item] for item in claim.linked_receipt_ids)
    blockers: list[str] = []
    required_maturity = _REQUIRED_MATURITY[claim.kind]
    if not any(item.maturity is required_maturity for item in linked):
        blockers.append(
            f"missing linked {required_maturity.value} receipt for {claim.kind.value}"
        )
    if facts.severe_failure_events:
        blockers.append("severe failures are present in the immutable analysis report")
    if facts.source_exclusions:
        blockers.append("analysis report contains excluded attempts")
    if claim.kind in {
        ClaimKind.CAUSAL_EFFECT,
        ClaimKind.GENERALIZED_EFFECT,
    } and request.analysis_report.adequacy.claim_level != "CONFIRMATORY_ANALYSIS_ELIGIBLE":
        blockers.append("descriptive-only adequacy blocks causal or generalized claims")
    if claim.kind in {
        ClaimKind.CAUSAL_EFFECT,
        ClaimKind.GENERALIZED_EFFECT,
    } and facts.estimated_effect_count == 0:
        blockers.append("no estimated effect is available in the immutable analysis report")
    if claim.kind in {ClaimKind.COST_COMPARISON, ClaimKind.PARETO_COMPARISON} and facts.unknown_cost_profile_ids:
        blockers.append("unknown cost blocks cost and Pareto claims")
    requested_ceiling = _CEILING_FOR_KIND[claim.kind]
    if _CEILING_RANK[requested_ceiling] > _CEILING_RANK[
        request.risk_constraints.maximum_claim_ceiling
    ]:
        blockers.append("risk constraints set a lower maximum claim ceiling")
    if facts.severe_failure_events:
        disposition = (
            ClaimDisposition.REJECTED
            if request.risk_constraints.severe_failure_disposition == "REJECT"
            else ClaimDisposition.HOLD
        )
    else:
        disposition = ClaimDisposition.HOLD if blockers else ClaimDisposition.SUPPORTED
    return ClaimLedgerEntry(
        claim_id=claim.claim_id,
        statement=claim.statement,
        kind=claim.kind,
        evidence_refs=linked,
        analysis_report_hash=request.analysis_report.canonical_hash,
        disposition=disposition,
        limitations=_limitations(request.analysis_report, facts),
        falsifiers=_falsifiers(claim.kind),
        blockers=tuple(blockers),
    )


@dataclass(frozen=True)
class _ReportFacts:
    severe_failure_events: int
    source_exclusions: tuple[tuple[str, str], ...]
    exclusions: tuple[tuple[str, str], ...]
    estimated_effect_count: int
    held_effect_count: int
    unknown_cost_profile_ids: tuple[str, ...]


def _report_facts(report: AnalysisReport) -> _ReportFacts:
    effects: tuple[EffectReport, ...] = (
        report.clean_vs_stressed_tax
        + report.main_effects
        + report.secondary_interactions
    )
    return _ReportFacts(
        severe_failure_events=sum(count for _, count in report.severe_failures_before_composites),
        source_exclusions=report.exclusions,
        exclusions=tuple(sorted(report.exclusions + report.pareto_exclusions)),
        estimated_effect_count=sum(item.status == "ESTIMATED" for item in effects),
        held_effect_count=sum(item.status == "HOLD" for item in effects),
        unknown_cost_profile_ids=tuple(
            profile.profile_id
            for profile in report.profiles
            if profile.cost_status is CostStatus.UNKNOWN
        ),
    )


def _brief_body(
    request: DecisionRequest,
    facts: _ReportFacts,
    entries: tuple[ClaimLedgerEntry, ...],
) -> dict[str, Any]:
    severe = request.analysis_report.severe_failures_before_composites
    blockers = _brief_blockers(request, facts, entries)
    if facts.severe_failure_events:
        verdict = (
            DecisionVerdict.REJECT
            if request.risk_constraints.severe_failure_disposition == "REJECT"
            else DecisionVerdict.HOLD
        )
    elif all(entry.disposition is ClaimDisposition.SUPPORTED for entry in entries):
        verdict = DecisionVerdict.PASS
    else:
        verdict = DecisionVerdict.HOLD
    return {
        "schema_version": "decision-brief-v1",
        "analysis_report_hash": request.analysis_report.canonical_hash,
        "verdict": verdict,
        "severe_failures": severe,
        "outcome_vector": OutcomeVector(
            included_attempt_count=len(request.analysis_report.included_attempt_ids),
            profile_count=len(request.analysis_report.profiles),
            estimated_effect_count=facts.estimated_effect_count,
            held_effect_count=facts.held_effect_count,
            severe_failure_events=facts.severe_failure_events,
            excluded_attempt_count=len(request.analysis_report.exclusions),
            unknown_cost_profile_ids=facts.unknown_cost_profile_ids,
            profiles=tuple(
                ProfileOutcome(
                    profile_id=profile.profile_id,
                    pass_at_1=profile.pass_at_1.value,
                    pass_power_k=profile.pass_power_k.value,
                    severe_failure_rate=profile.severe_failure.value,
                    auditability=profile.auditability.value,
                    latency_seconds=profile.latency_seconds.value,
                    cost_status=profile.cost_status,
                    cost_usd=profile.cost_usd.value,
                )
                for profile in request.analysis_report.profiles
            ),
        ),
        "uncertainty": _uncertainty(request.analysis_report, facts),
        "exclusions": facts.exclusions,
        "supported_claim_ceiling": _supported_ceiling(entries),
        "blockers": blockers,
        "next_lawful_action": _next_lawful_action(blockers),
    }


def _brief_blockers(
    request: DecisionRequest,
    facts: _ReportFacts,
    entries: tuple[ClaimLedgerEntry, ...],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if facts.severe_failure_events:
        blockers.append("severe failures must be resolved before any claim promotion")
    if facts.source_exclusions:
        blockers.append("excluded attempts prevent claim promotion")
    if request.analysis_report.adequacy.claim_level != "CONFIRMATORY_ANALYSIS_ELIGIBLE":
        blockers.append("analysis adequacy is descriptive-only")
    if facts.unknown_cost_profile_ids:
        blockers.append("one or more profiles have unknown cost")
    blockers.extend(
        f"{entry.claim_id}: {blocker}"
        for entry in entries
        for blocker in entry.blockers
        if blocker not in {
            "severe failures are present in the immutable analysis report",
            "analysis report contains excluded attempts or Pareto exclusions",
        }
    )
    return tuple(dict.fromkeys(blockers))


def _supported_ceiling(entries: tuple[ClaimLedgerEntry, ...]) -> ClaimCeiling:
    supported = [
        _CEILING_FOR_KIND[entry.kind]
        for entry in entries
        if entry.disposition is ClaimDisposition.SUPPORTED
    ]
    return max(supported, key=lambda item: _CEILING_RANK[item], default=ClaimCeiling.NO_CLAIM)


def _uncertainty(report: AnalysisReport, facts: _ReportFacts) -> tuple[str, ...]:
    uncertainty = list(report.adequacy.reasons)
    if facts.held_effect_count:
        uncertainty.append("one or more effect estimates are held")
    if facts.unknown_cost_profile_ids:
        uncertainty.append("cost is unknown for one or more profiles")
    if not uncertainty:
        uncertainty.append("claim scope remains limited to linked immutable receipts")
    return tuple(dict.fromkeys(uncertainty))


def _limitations(report: AnalysisReport, facts: _ReportFacts) -> tuple[str, ...]:
    limitations = list(_uncertainty(report, facts))
    if report.adequacy.claim_level == "DESCRIPTIVE_ONLY":
        limitations.append("descriptive evidence does not establish causal or generalized effects")
    return tuple(dict.fromkeys(limitations))


def _falsifiers(kind: ClaimKind) -> tuple[str, ...]:
    if kind in {ClaimKind.COST_COMPARISON, ClaimKind.PARETO_COMPARISON}:
        return ("a linked profile with unreconciled provider cost falsifies this claim",)
    if kind in {ClaimKind.CAUSAL_EFFECT, ClaimKind.GENERALIZED_EFFECT}:
        return ("loss of confirmatory adequacy or an estimated effect falsifies this claim",)
    required = _REQUIRED_MATURITY[kind]
    return (f"absence of the linked {required.value} receipt falsifies this claim",)


def _next_lawful_action(blockers: tuple[str, ...]) -> str:
    if not blockers:
        return "Publish only the supported ledger claims with their linked immutable receipts."
    if blockers[0].startswith("severe failures"):
        return "Resolve and reproduce the severe failures, then build a new immutable analysis report."
    if blockers[0].startswith("excluded"):
        return "Resolve the exclusion basis and regenerate the immutable analysis report."
    if blockers[0].startswith("analysis adequacy"):
        return "Meet every adequacy gate and regenerate the immutable analysis report."
    if blockers[0].startswith("one or more profiles have unknown cost"):
        return "Attach provider usage and price receipts, then regenerate the immutable analysis report."
    return "Attach the missing linked immutable receipt or narrow the proposed claim."


def _canonical_hash(value: Any) -> str:
    import json

    return sha256(
        json.dumps(
            value,
            default=_json_default,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"not JSON serializable: {type(value).__name__}")
