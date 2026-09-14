from __future__ import annotations

from protocol_v1 import OutcomeVector

from .models import DecisionBrief


def build_decision_brief(
    *,
    brief_id: str,
    outcome: OutcomeVector,
    hard_gate_passed: bool,
    claim_ceiling: str,
    uncertainty: tuple[str, ...] = (),
    exclusions: tuple[str, ...] = (),
    next_lawful_action: str = "obtain the missing evidence",
) -> DecisionBrief:
    severe = tuple(outcome.severe_failures)
    blockers = list(exclusions)
    if severe:
        blockers.insert(0, "severe deterministic failure")
    if not hard_gate_passed:
        blockers.insert(0, "hard eligibility gate failed")
    if outcome.cost_status == "unknown":
        blockers.append("cost is UNKNOWN")
    verdict = "HOLD" if blockers else "ADVANCE"
    return DecisionBrief(
        brief_id=brief_id,
        verdict=verdict,
        severe_failures=severe,
        outcome_vector=outcome.model_dump(mode="json"),
        uncertainty=uncertainty,
        exclusions=exclusions,
        supported_claim_ceiling=claim_ceiling,
        blockers=tuple(dict.fromkeys(blockers)),
        next_lawful_action=next_lawful_action,
    )
