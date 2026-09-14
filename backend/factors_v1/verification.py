"""Agent-side pre-finalization verification.  This is not Arena evaluation."""

from __future__ import annotations

from .models import (
    FinalizationCandidate,
    RepairAttempt,
    VerificationArtifact,
    VerificationCheck,
)


def _all_pass(checks: tuple[VerificationCheck, ...]) -> bool:
    return bool(checks) and all(check.status == "passed" and check.evidence for check in checks)


def _check_ids(checks: tuple[VerificationCheck, ...]) -> set[str]:
    ids = [check.check_id for check in checks]
    if len(ids) != len(set(ids)):
        raise ValueError("verification check ids must be unique")
    return set(ids)


def verify_before_finalization(
    candidate: FinalizationCandidate,
    checks: tuple[VerificationCheck, ...],
    *,
    repair: RepairAttempt | None = None,
    repair_budget: int = 1,
) -> VerificationArtifact:
    """Permit finalization only after evidence-linked checks and zero/one repair."""
    if repair_budget != 1:
        raise ValueError("the verification repair budget is exactly one")
    initial_check_ids = _check_ids(checks)
    if not checks:
        return VerificationArtifact(episode_id=candidate.episode_id, candidate_response_hash=candidate.response_hash, final_response_hash=None, checks=(), repairs_used=0, finalization_allowed=False, failure_reason="verification evidence is missing")
    if _all_pass(checks):
        if repair is not None:
            raise ValueError("repair is not permitted after successful verification")
        return VerificationArtifact(episode_id=candidate.episode_id, candidate_response_hash=candidate.response_hash, final_response_hash=candidate.response_hash, checks=checks, repairs_used=0, finalization_allowed=True)
    if repair is None:
        return VerificationArtifact(episode_id=candidate.episode_id, candidate_response_hash=candidate.response_hash, final_response_hash=None, checks=checks, repairs_used=0, finalization_allowed=False, failure_reason="verification failed and no bounded repair evidence was supplied")
    if repair.episode_id != candidate.episode_id:
        raise ValueError("repair episode_id does not bind the candidate")
    if repair.original_candidate_response_hash != candidate.response_hash:
        raise ValueError("repair original candidate hash does not bind the candidate")
    if repair.response_hash == repair.original_candidate_response_hash:
        raise ValueError("repair response_hash must differ from the original candidate")
    if _check_ids(repair.checks) != initial_check_ids:
        raise ValueError("repair checks must cover exactly the original check ids")
    if not repair.evidence or not _all_pass(repair.checks):
        return VerificationArtifact(episode_id=candidate.episode_id, candidate_response_hash=candidate.response_hash, final_response_hash=None, checks=repair.checks, repair_evidence=repair.evidence, repairs_used=1, finalization_allowed=False, failure_reason="the single repair did not produce evidence-linked passing checks")
    return VerificationArtifact(episode_id=candidate.episode_id, candidate_response_hash=candidate.response_hash, final_response_hash=repair.response_hash, checks=repair.checks, repair_evidence=repair.evidence, repairs_used=1, finalization_allowed=True)
