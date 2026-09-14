import pytest
from pydantic import ValidationError

from analysis_v1.claims import (
    ClaimCeiling,
    ClaimDisposition,
    ClaimKind,
    DecisionRequest,
    DecisionVerdict,
    EvidenceMaturity,
    EvidenceReceiptReference,
    ProposedClaim,
    build_decision_artifacts,
)
from analysis_v1.decision import CostStatus
from analysis_v1.engine import (
    AnalysisGates,
    AnalysisInput,
    AnalysisOptions,
    AttemptRecord,
    FactorLevel,
    MainEffectSpec,
    RegisteredFactor,
    build_analysis_report,
)


def _attempt(identifier: str, *, treatment: bool, cost_status: CostStatus) -> AttemptRecord:
    pair_index = int(identifier.rsplit("-", 1)[1]) // 2
    values: dict[str, object] = {
        "attempt_id": identifier,
        "experiment_id": "claim-experiment",
        "task_id": f"task-{pair_index}",
        "task_cluster_id": f"cluster-{pair_index}",
        "scaffold_id": "scaffold-a",
        "pair_id": f"pair-{pair_index}",
        "repeat_index": 1,
        "factor_levels": (FactorLevel(factor_id="mode", level="treatment" if treatment else "control"),),
        "success": treatment,
        "auditability": 1.0,
        "trace_complete": True,
        "manipulation_pass": True,
        "evaluator_independent": True,
        "held_out": True,
        "cost_status": cost_status,
        "latency_seconds": 1.0,
    }
    if cost_status is CostStatus.RECONCILED:
        values.update(
            cost_usd=0.01,
            provider_usage_ref=f"usage:{identifier}",
            price_reference="prices:v1",
        )
    return AttemptRecord(**values)


def _report(
    *,
    severe: bool = False,
    unknown_cost: bool = False,
    descriptive_only: bool = False,
):
    cost_status = CostStatus.UNKNOWN if unknown_cost else CostStatus.RECONCILED
    records = tuple(
        _attempt(f"attempt-{index}", treatment=index % 2 == 1, cost_status=cost_status)
        for index in range(20)
    )
    if severe:
        records = (records[0].model_copy(update={"severe_failures": ("unsafe",)}),) + records[1:]
    return build_analysis_report(
        AnalysisInput(
            experiment_id="claim-experiment",
            registered_factors=(RegisteredFactor(factor_id="mode", levels=("control", "treatment")),),
            primary_main_effects=(MainEffectSpec(effect_id="mode-effect", factor_id="mode", control_level="control", treatment_level="treatment"),),
            attempts=records,
            gates=AnalysisGates(
                preregistered_design=not descriptive_only,
                comparison_invariants_pass=True,
            ),
            options=AnalysisOptions(bootstrap_resamples=100, bootstrap_seed=5),
        )
    )


def _receipt(report_hash: str, identifier: str, maturity: EvidenceMaturity) -> EvidenceReceiptReference:
    return EvidenceReceiptReference(
        receipt_id=identifier,
        maturity=maturity,
        receipt_hash="a" * 64,
        analysis_report_hash=report_hash,
        artifact_ref=f"evidence:{identifier}",
    )


def _request(report, *claims: ProposedClaim, receipts: tuple[EvidenceReceiptReference, ...]) -> DecisionRequest:
    return DecisionRequest(
        analysis_report=report,
        evidence_receipts=receipts,
        proposed_claims=claims,
    )


def test_severe_failure_cannot_be_masked_by_a_good_aggregate():
    report = _report(severe=True)
    fixture = _receipt(report.canonical_hash, "a-fixture", EvidenceMaturity.FIXTURE)
    artifacts = build_decision_artifacts(
        _request(
            report,
            ProposedClaim(claim_id="observed", statement="The fixture observation passed.", kind=ClaimKind.FIXTURE_OBSERVATION, linked_receipt_ids=(fixture.receipt_id,)),
            receipts=(fixture,),
        )
    )
    assert artifacts.brief.verdict is DecisionVerdict.HOLD
    assert artifacts.brief.supported_claim_ceiling is ClaimCeiling.NO_CLAIM
    assert artifacts.brief.blockers[0].startswith("severe failures")
    assert artifacts.ledger.entries[0].disposition is ClaimDisposition.HOLD


@pytest.mark.parametrize(
    ("kind", "required_maturity"),
    (
        (ClaimKind.CROSS_MODEL_REPLICATION, EvidenceMaturity.CROSS_MODEL),
        (ClaimKind.HUMAN_CALIBRATED_ASSESSMENT, EvidenceMaturity.HUMAN_CALIBRATED),
        (ClaimKind.INDEPENDENT_VALIDATION, EvidenceMaturity.INDEPENDENT),
    ),
)
def test_forged_maturity_label_without_matching_linked_receipt_is_held(
    kind: ClaimKind, required_maturity: EvidenceMaturity
):
    report = _report()
    fixture = _receipt(report.canonical_hash, "b-fixture", EvidenceMaturity.FIXTURE)
    artifacts = build_decision_artifacts(
        _request(
            report,
            ProposedClaim(claim_id="external", statement="This has external support.", kind=kind, linked_receipt_ids=(fixture.receipt_id,)),
            receipts=(fixture,),
        )
    )
    entry = artifacts.ledger.entries[0]
    assert entry.disposition is ClaimDisposition.HOLD
    assert entry.blockers == (f"missing linked {required_maturity.value} receipt for {kind.value}",)


def test_unknown_cost_blocks_cost_and_pareto_claims():
    report = _report(unknown_cost=True)
    live = _receipt(report.canonical_hash, "c-live", EvidenceMaturity.LOCAL_LIVE)
    artifacts = build_decision_artifacts(
        _request(
            report,
            ProposedClaim(claim_id="cost", statement="This is cheaper.", kind=ClaimKind.COST_COMPARISON, linked_receipt_ids=(live.receipt_id,)),
            ProposedClaim(claim_id="pareto", statement="This is Pareto optimal.", kind=ClaimKind.PARETO_COMPARISON, linked_receipt_ids=(live.receipt_id,)),
            receipts=(live,),
        )
    )
    assert [entry.disposition for entry in artifacts.ledger.entries] == [ClaimDisposition.HOLD, ClaimDisposition.HOLD]
    assert all("unknown cost blocks cost and Pareto claims" in entry.blockers for entry in artifacts.ledger.entries)


def test_descriptive_adequacy_blocks_causal_claims():
    report = _report(descriptive_only=True)
    live = _receipt(report.canonical_hash, "d-live", EvidenceMaturity.LOCAL_LIVE)
    artifacts = build_decision_artifacts(
        _request(
            report,
            ProposedClaim(claim_id="cause", statement="The scaffold caused the outcome.", kind=ClaimKind.CAUSAL_EFFECT, linked_receipt_ids=(live.receipt_id,)),
            receipts=(live,),
        )
    )
    assert artifacts.ledger.entries[0].disposition is ClaimDisposition.HOLD
    assert "descriptive-only adequacy blocks causal or generalized claims" in artifacts.ledger.entries[0].blockers


def test_absent_external_replication_blocks_generalized_claim():
    report = _report()
    live = _receipt(report.canonical_hash, "e-live", EvidenceMaturity.LOCAL_LIVE)
    artifacts = build_decision_artifacts(
        _request(
            report,
            ProposedClaim(claim_id="general", statement="The effect generalizes.", kind=ClaimKind.GENERALIZED_EFFECT, linked_receipt_ids=(live.receipt_id,)),
            receipts=(live,),
        )
    )
    assert artifacts.ledger.entries[0].disposition is ClaimDisposition.HOLD
    assert "missing linked replicated receipt for generalized_effect" in artifacts.ledger.entries[0].blockers


def test_hashes_are_stable_and_narrow_fixture_and_local_live_claims_pass():
    report = _report()
    fixture = _receipt(report.canonical_hash, "f-fixture", EvidenceMaturity.FIXTURE)
    live = _receipt(report.canonical_hash, "g-live", EvidenceMaturity.LOCAL_LIVE)
    request = _request(
        report,
        ProposedClaim(claim_id="fixture", statement="This fixture was observed.", kind=ClaimKind.FIXTURE_OBSERVATION, linked_receipt_ids=(fixture.receipt_id,)),
        ProposedClaim(claim_id="live", statement="This local live run was observed.", kind=ClaimKind.LOCAL_LIVE_OBSERVATION, linked_receipt_ids=(live.receipt_id,)),
        receipts=(fixture, live),
    )
    first = build_decision_artifacts(request)
    second = build_decision_artifacts(request)
    assert first.brief.canonical_hash == second.brief.canonical_hash
    assert first.ledger.canonical_hash == second.ledger.canonical_hash
    assert first.brief.verdict is DecisionVerdict.PASS
    assert first.brief.supported_claim_ceiling is ClaimCeiling.LOCAL_LIVE_ONLY
    assert all(entry.disposition is ClaimDisposition.SUPPORTED for entry in first.ledger.entries)


def test_contract_rejects_unbound_receipts_and_caller_overrides():
    report = _report()
    receipt = _receipt("f" * 64, "h-fixture", EvidenceMaturity.FIXTURE)
    claim = ProposedClaim(claim_id="fixture", statement="This fixture was observed.", kind=ClaimKind.FIXTURE_OBSERVATION, linked_receipt_ids=(receipt.receipt_id,))
    with pytest.raises(ValidationError, match="bind to the analysis report hash"):
        _request(report, claim, receipts=(receipt,))
    valid_receipt = _receipt(report.canonical_hash, "i-fixture", EvidenceMaturity.FIXTURE)
    tampered_report = report.model_copy(
        update={"severe_failures_before_composites": (("unsafe", 1),)}
    )
    with pytest.raises(ValidationError, match="canonical hash does not match"):
        _request(tampered_report, claim, receipts=(valid_receipt,))
    with pytest.raises(ValidationError, match="aggregate_score"):
        ProposedClaim.model_validate({"claim_id": "bad", "statement": "bad", "kind": ClaimKind.FIXTURE_OBSERVATION, "linked_receipt_ids": ("x",), "aggregate_score": 1.0})
