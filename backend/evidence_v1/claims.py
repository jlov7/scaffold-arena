from __future__ import annotations

from collections.abc import Mapping

from .models import (
    ClaimMaturity,
    ClaimPromotion,
    EvidenceVerification,
    ExternalIndependenceAttestation,
)

_ORDER = tuple(ClaimMaturity)
_REQUIRED = {
    ClaimMaturity.FIXTURE: "fixture_receipt",
    ClaimMaturity.LOCAL_LIVE: "local_live_receipt",
    ClaimMaturity.REPLICATED: "reproduction_receipt",
    ClaimMaturity.CROSS_MODEL: "cross_model_receipt",
    ClaimMaturity.HUMAN_CALIBRATED: "human_calibration_receipt",
    ClaimMaturity.INDEPENDENTLY_REPRODUCED: "independent_reproduction_receipt",
}


def promote_claim(
    current: ClaimMaturity,
    requested: ClaimMaturity,
    evidence: Mapping[str, EvidenceVerification],
    *,
    independence_attestation: ExternalIndependenceAttestation | None = None,
) -> ClaimPromotion:
    current_index, requested_index = _ORDER.index(current), _ORDER.index(requested)
    if requested_index <= current_index:
        return ClaimPromotion(
            current=current,
            requested=requested,
            promoted=True,
            claim_ceiling=current.value,
            blockers=(),
        )
    blockers: list[str] = []
    for level in _ORDER[current_index + 1 : requested_index + 1]:
        required = _REQUIRED[level]
        verification = evidence.get(required)
        if verification is None:
            blockers.append(f"missing required {required}")
            continue
        expected_type = {
            ClaimMaturity.LOCAL_LIVE: "local_live",
            ClaimMaturity.REPLICATED: "reproduction",
            ClaimMaturity.CROSS_MODEL: "cross_model",
            ClaimMaturity.HUMAN_CALIBRATED: "human_calibration",
            ClaimMaturity.INDEPENDENTLY_REPRODUCED: "independent_reproduction",
        }[level]
        if not verification.verified or verification.errors:
            blockers.append(f"{required} is not integrity-verified")
        if verification.evidence_type != expected_type:
            blockers.append(f"{required} verification has the wrong evidence type")
        if level is ClaimMaturity.INDEPENDENTLY_REPRODUCED:
            if (
                independence_attestation is None
                or not independence_attestation.attestation_evidence_ref
            ):
                blockers.append(
                    "independent reproduction requires external attestation evidence"
                )
            elif (
                independence_attestation.reproduction_receipt_hash
                != verification.receipt_hash
            ):
                blockers.append(
                    "external attestation is not bound to the verified reproduction receipt"
                )
    if blockers:
        return ClaimPromotion(
            current=current,
            requested=requested,
            promoted=False,
            claim_ceiling=current.value,
            blockers=tuple(dict.fromkeys(blockers)),
        )
    # Code verifies receipt/artifact integrity and bindings. Identity independence remains external evidence.
    return ClaimPromotion(
        current=requested,
        requested=requested,
        promoted=True,
        claim_ceiling=requested.value,
    )
