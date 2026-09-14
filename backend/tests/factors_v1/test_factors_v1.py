from __future__ import annotations

import json
import re
from itertools import permutations

import pytest
from pydantic import ValidationError

from factors_v1 import (
    FLAGSHIP_FACTORS,
    RecipeCompilationError,
    append_memory,
    authorize_recovery,
    check_manipulation_fidelity,
    compile_recipe,
    create_plan,
    enumerate_flagship_recipes,
    new_episode_memory,
    transition_plan_step,
    verify_before_finalization,
)
from factors_v1.models import (
    CapabilityProfile,
    CheckpointArtifact,
    EpisodeMemory,
    EvidencePointer,
    FailureEvent,
    FinalizationCandidate,
    MemoryItem,
    RecoveryPolicy,
    RepairAttempt,
    TreatmentBudget,
    VerificationCheck,
)
from protocol_v1.models import FactorSpec, IncompatibleLevelCombination

HASH = "a" * 64


def evidence(source_id: str = "source-one", content_hash: str = HASH) -> EvidencePointer:
    return EvidencePointer(source_id=source_id, uri=f"fixture://{source_id}", content_hash=content_hash)


def assignment(**overrides: bool) -> dict[str, bool]:
    value = {"planning": False, "verification": False, "recovery": False, "memory": False}
    value.update(overrides)
    return value


def test_plan_all_legal_transitions_and_evidence_bound_terminals() -> None:
    plan = create_plan(episode_id="episode-one", plan_id="plan-one", steps=(("step-one", "Inspect evidence"),))
    started = transition_plan_step(plan, step_id="step-one", state="in_progress")
    completed = transition_plan_step(started, step_id="step-one", state="completed", evidence=evidence())

    assert plan.steps[0].state == "pending"
    assert completed.steps[0].state == "completed"
    assert completed.steps[0].terminal_evidence == evidence()


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    (("pending", "completed"), ("pending", "failed"), ("in_progress", "pending"), ("completed", "in_progress"), ("failed", "in_progress")),
)
def test_plan_rejects_invalid_state_transitions(from_state: str, to_state: str) -> None:
    plan = create_plan(episode_id="episode-one", plan_id="plan-one", steps=(("step-one", "Inspect evidence"),))
    if from_state == "in_progress":
        plan = transition_plan_step(plan, step_id="step-one", state="in_progress")
    elif from_state == "completed":
        plan = transition_plan_step(transition_plan_step(plan, step_id="step-one", state="in_progress"), step_id="step-one", state="completed", evidence=evidence())
    elif from_state == "failed":
        plan = transition_plan_step(transition_plan_step(plan, step_id="step-one", state="in_progress"), step_id="step-one", state="failed", evidence=evidence())
    with pytest.raises(ValueError, match="invalid plan transition"):
        transition_plan_step(plan, step_id="step-one", state=to_state)


def test_plan_refuses_unevidenced_terminal_states_and_unknown_step() -> None:
    plan = create_plan(episode_id="episode-one", plan_id="plan-one", steps=(("step-one", "Inspect evidence"),))
    active = transition_plan_step(plan, step_id="step-one", state="in_progress")
    with pytest.raises(ValueError, match="require terminal evidence"):
        transition_plan_step(active, step_id="step-one", state="completed")
    with pytest.raises(ValueError, match="require terminal evidence"):
        transition_plan_step(active, step_id="step-one", state="failed")
    with pytest.raises(ValueError, match="unknown"):
        transition_plan_step(plan, step_id="missing", state="in_progress")


def test_plan_allows_evidenced_failure_from_in_progress() -> None:
    plan = create_plan(episode_id="episode-one", plan_id="plan-one", steps=(("step-one", "Inspect evidence"),))
    failed = transition_plan_step(
        transition_plan_step(plan, step_id="step-one", state="in_progress"), step_id="step-one", state="failed", evidence=evidence()
    )
    assert failed.steps[0].state == "failed"


def test_verification_is_pre_finalization_and_allows_one_evidenced_repair() -> None:
    candidate = FinalizationCandidate(episode_id="episode-one", response_hash=HASH)
    failed = VerificationCheck(check_id="check-one", status="failed", detail="missing citation", evidence=(evidence(),))
    repaired = VerificationCheck(check_id="check-one", status="passed", detail="citation present", evidence=(evidence(),))
    repair = RepairAttempt(repair_id="repair-one", episode_id="episode-one", original_candidate_response_hash=HASH, response_hash="b" * 64, checks=(repaired,), evidence=(evidence(),))

    result = verify_before_finalization(candidate, (failed,), repair=repair)

    assert result.finalization_allowed is True
    assert result.repairs_used == 1
    assert result.independent_arena_evaluation is False
    assert result.scope == "agent_pre_finalization"


def test_verification_fails_closed_without_evidence_and_rejects_extra_repair() -> None:
    candidate = FinalizationCandidate(episode_id="episode-one", response_hash=HASH)
    failed = VerificationCheck(check_id="check-one", status="failed", detail="bad", evidence=(evidence(),))
    result = verify_before_finalization(candidate, (failed,))
    assert result.finalization_allowed is False
    with pytest.raises(ValueError, match="exactly one"):
        verify_before_finalization(candidate, (failed,), repair_budget=2)
    passed = VerificationCheck(check_id="check-one", status="passed", detail="good", evidence=(evidence(),))
    repair = RepairAttempt(repair_id="repair-one", episode_id="episode-one", original_candidate_response_hash=HASH, response_hash="b" * 64, checks=(passed,), evidence=(evidence(),))
    with pytest.raises(ValueError, match="not permitted"):
        verify_before_finalization(candidate, (passed,), repair=repair)
    missing_evidence_repair = RepairAttempt(repair_id="repair-two", episode_id="episode-one", original_candidate_response_hash=HASH, response_hash="c" * 64, checks=(passed,), evidence=(evidence(),))
    missing_evidence_repair = missing_evidence_repair.model_copy(
        update={"evidence": ()}
    )
    assert verify_before_finalization(candidate, (failed,), repair=missing_evidence_repair).finalization_allowed is False


def test_repair_is_bound_to_candidate_episode_and_exact_original_checks() -> None:
    candidate = FinalizationCandidate(episode_id="episode-one", response_hash=HASH)
    checks = (
        VerificationCheck(check_id="check-one", status="failed", detail="one", evidence=(evidence(),)),
        VerificationCheck(check_id="check-two", status="failed", detail="two", evidence=(evidence(),)),
    )
    repaired = tuple(VerificationCheck(check_id=check.check_id, status="passed", detail="repaired", evidence=(evidence(),)) for check in checks)
    base = RepairAttempt(repair_id="repair-one", episode_id="episode-one", original_candidate_response_hash=HASH, response_hash="b" * 64, checks=repaired, evidence=(evidence(),))
    assert verify_before_finalization(candidate, checks, repair=base).finalization_allowed
    with pytest.raises(ValueError, match="episode_id"):
        verify_before_finalization(candidate, checks, repair=base.model_copy(update={"episode_id": "episode-two"}))
    with pytest.raises(ValueError, match="candidate hash"):
        verify_before_finalization(candidate, checks, repair=base.model_copy(update={"original_candidate_response_hash": "c" * 64}))
    with pytest.raises(ValueError, match="exactly"):
        verify_before_finalization(candidate, checks, repair=base.model_copy(update={"checks": repaired[:1]}))
    extra = VerificationCheck(check_id="check-three", status="passed", detail="extra", evidence=(evidence(),))
    with pytest.raises(ValueError, match="exactly"):
        verify_before_finalization(candidate, checks, repair=base.model_copy(update={"checks": (*repaired, extra)}))
    with pytest.raises(ValueError, match="unique"):
        verify_before_finalization(candidate, (checks[0], checks[0]))
    with pytest.raises(ValueError, match="unique"):
        verify_before_finalization(candidate, checks, repair=base.model_copy(update={"checks": (repaired[0], repaired[0])}))
    with pytest.raises(ValidationError, match="must differ"):
        RepairAttempt(repair_id="repair-same", episode_id="episode-one", original_candidate_response_hash=HASH, response_hash=HASH, checks=repaired, evidence=(evidence(),))
    with pytest.raises(ValueError, match="must differ"):
        verify_before_finalization(candidate, checks, repair=base.model_copy(update={"response_hash": HASH}))


def test_recovery_requires_declared_transient_failure_budget_provenance_and_unique_key() -> None:
    failure = FailureEvent(episode_id="episode-one", attempt_id="attempt-one", failure_id="network-timeout", failure_class="transient", detail="timeout")
    checkpoint = CheckpointArtifact(checkpoint_id="checkpoint-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0, state_hash=HASH, provenance=evidence())
    policy = RecoveryPolicy(max_retries=1, declared_transient_failures=("network-timeout",))
    allowed = authorize_recovery(failure, checkpoint, policy, retries_used=0, idempotency_key="retry-one", observed_checkpoint_sequences=frozenset({0}))
    assert allowed.allowed and allowed.retry_number == 1
    assert not authorize_recovery(failure, checkpoint, policy, retries_used=1, idempotency_key="retry-two", observed_checkpoint_sequences=frozenset({0})).allowed
    assert not authorize_recovery(failure, checkpoint, policy, retries_used=0, idempotency_key="retry-one", observed_checkpoint_sequences=frozenset({0}), used_idempotency_keys=frozenset({"retry-one"})).allowed
    wrong = checkpoint.model_copy(update={"attempt_id": "attempt-two"})
    assert not authorize_recovery(failure, wrong, policy, retries_used=0, idempotency_key="retry-three", observed_checkpoint_sequences=frozenset({0})).allowed
    undeclared = failure.model_copy(update={"failure_id": "other-transient"})
    assert not authorize_recovery(undeclared, checkpoint, policy, retries_used=0, idempotency_key="retry-four", observed_checkpoint_sequences=frozenset({0})).allowed
    assert not authorize_recovery(failure, checkpoint, policy, retries_used=0, idempotency_key="retry-five", observed_checkpoint_sequences=frozenset()).allowed
    with pytest.raises(ValidationError, match="bind state_hash"):
        CheckpointArtifact(checkpoint_id="checkpoint-bad", episode_id="episode-one", attempt_id="attempt-one", sequence=1, state_hash=HASH, provenance=evidence("other", "b" * 64))
    invalid_checkpoint = checkpoint.model_copy(update={"provenance": evidence("other", "b" * 64)})
    assert not authorize_recovery(failure, invalid_checkpoint, policy, retries_used=0, idempotency_key="retry-six", observed_checkpoint_sequences=frozenset({0})).allowed


@pytest.mark.parametrize("failure_class", ("undeclared", "permanent", "safety"))
def test_recovery_never_crosses_nontransient_failure_classes(failure_class: str) -> None:
    failure = FailureEvent(episode_id="episode-one", attempt_id="attempt-one", failure_id="network-timeout", failure_class=failure_class, detail="stop")
    checkpoint = CheckpointArtifact(checkpoint_id="checkpoint-one", episode_id="episode-one", attempt_id="attempt-one", sequence=0, state_hash=HASH, provenance=evidence())
    decision = authorize_recovery(failure, checkpoint, RecoveryPolicy(max_retries=1, declared_transient_failures=("network-timeout",)), retries_used=0, idempotency_key="retry-one", observed_checkpoint_sequences=frozenset({0}))
    assert decision.allowed is False


def test_memory_is_bounded_sourced_compacted_and_episode_local() -> None:
    memory = new_episode_memory(episode_id="episode-one", max_items=2, max_bytes=220)
    one = MemoryItem(item_id="item-one", episode_id="episode-one", content="a" * 100, source_pointers=(evidence(),))
    two = MemoryItem(item_id="item-two", episode_id="episode-one", content="b" * 100, source_pointers=(evidence("source-two"),))
    three = MemoryItem(item_id="item-three", episode_id="episode-one", content="c" * 100, source_pointers=(evidence("source-three"),))
    compacted = append_memory(append_memory(memory, one), two)
    compacted = append_memory(compacted, three)

    assert len(compacted.items) == 2
    assert compacted.items[0].content.startswith("[extractive-compaction;")
    assert "omitted_bytes=" in compacted.items[0].content
    assert "source_lineage=item-one,item-two" in compacted.items[0].content
    assert set(compacted.items[0].lineage) == {"item-one", "item-two"}
    assert compacted.total_bytes <= compacted.max_bytes
    with pytest.raises(ValueError, match="cross-episode"):
        append_memory(memory, MemoryItem(item_id="other", episode_id="episode-two", content="x", source_pointers=(evidence(),)))
    with pytest.raises(ValidationError, match="source_pointers"):
        MemoryItem(item_id="no-source", episode_id="episode-one", content="x", source_pointers=())


def test_memory_rejects_uncompactable_or_oversized_items() -> None:
    memory = new_episode_memory(episode_id="episode-one", max_items=2, max_bytes=5)
    with pytest.raises(ValueError, match="exceeds"):
        append_memory(memory, MemoryItem(item_id="item-one", episode_id="episode-one", content="too long", source_pointers=(evidence(),)))
    tiny = new_episode_memory(episode_id="episode-one", max_items=1, max_bytes=25)
    tiny = append_memory(tiny, MemoryItem(item_id="tiny-one", episode_id="episode-one", content="abcdefghij", source_pointers=(evidence(),)))
    with pytest.raises(ValueError, match="too small"):
        append_memory(tiny, MemoryItem(item_id="tiny-two", episode_id="episode-one", content="klmnopqrst", source_pointers=(evidence("source-two"),)))


def test_memory_extractive_compaction_is_unicode_bounded_and_deterministic_across_repeats() -> None:
    omitted_pattern = re.compile(r"omitted_bytes=(\d+)")

    def compact_run() -> tuple[EpisodeMemory, int]:
        memory = new_episode_memory(episode_id="episode-one", max_items=2, max_bytes=400)
        first_generation_omitted = -1
        for number, content in enumerate(("é" * 75, "ß" * 75, "漢" * 50, "λ" * 75), start=1):
            memory = append_memory(memory, MemoryItem(item_id=f"unicode-{number}", episode_id="episode-one", content=content, source_pointers=(evidence(f"source-{number}"),)))
            if number == 3:
                match = omitted_pattern.search(memory.items[0].content)
                assert match is not None
                first_generation_omitted = int(match.group(1))
        return memory, first_generation_omitted

    first, first_generation_omitted = compact_run()
    second, _ = compact_run()
    assert first == second
    assert first.total_bytes <= first.max_bytes
    assert first.total_bytes == sum(len(item.content.encode("utf-8")) for item in first.items)
    assert all(len(item.content.encode("utf-8")) <= first.max_bytes for item in first.items)
    assert "漢" in first.items[0].content or "λ" in first.items[0].content or "é" in first.items[0].content
    second_generation_match = omitted_pattern.search(first.items[0].content)
    assert second_generation_match is not None
    assert int(second_generation_match.group(1)) >= first_generation_omitted


def test_memory_fails_closed_on_malformed_internal_compaction_marker() -> None:
    memory = new_episode_memory(episode_id="episode-one", max_items=1, max_bytes=400)
    malformed = MemoryItem(
        item_id="compact-bad", episode_id="episode-one", content="[extractive-compaction; bad]\ntext",
        source_pointers=(evidence(),), lineage=("item-one", "item-two"),
    )
    memory = append_memory(memory, malformed)
    with pytest.raises(ValueError, match="malformed internal"):
        append_memory(memory, MemoryItem(item_id="item-three", episode_id="episode-one", content="more", source_pointers=(evidence("source-three"),)))


def test_all_sixteen_recipes_compile_deterministically_and_are_serializable() -> None:
    recipes = enumerate_flagship_recipes()
    assert len(recipes) == 16
    assert len({recipe.configuration_hash for recipe in recipes}) == 16
    assert enumerate_flagship_recipes() == recipes
    assert all(recipe.execution_claim == "not_executed" for recipe in recipes)
    json.dumps(recipes[0].model_dump(mode="json"))
    forward = compile_recipe({"planning": True, "verification": False, "recovery": True, "memory": False})
    alternate_order = compile_recipe({"m": False, "r": True, "p": True, "v": False})
    assert forward.configuration_hash == alternate_order.configuration_hash
    pairs = (("planning", True), ("verification", False), ("recovery", True), ("memory", False))
    hashes = {
        compile_recipe(dict(order)).configuration_hash
        for order in permutations(pairs)
    }
    assert hashes == {forward.configuration_hash}


def test_compiler_refuses_capability_mismatch_and_declared_incompatible_combo() -> None:
    no_memory = CapabilityProfile(profile_id="no-memory", adapter_kind="recorded", capabilities={"state": True, "checkpoint": True, "memory": False})
    with pytest.raises(RecipeCompilationError, match="unavailable"):
        compile_recipe(assignment(memory=True), profile=no_memory)

    planning = FLAGSHIP_FACTORS[0].model_dump(mode="python")
    planning["incompatible_level_combinations"] = (IncompatibleLevelCombination(assignments={"planning": True, "memory": True}, reason="test conflict"),)
    factors = (FactorSpec(**planning), *FLAGSHIP_FACTORS[1:])
    with pytest.raises(RecipeCompilationError, match="incompatible"):
        compile_recipe(assignment(planning=True, memory=True), factors=factors)

    planning["treatment_mutations"] = (FLAGSHIP_FACTORS[1].treatment_mutations[0],)
    conflicting = (FactorSpec(**planning), *FLAGSHIP_FACTORS[1:])
    with pytest.raises(RecipeCompilationError, match="conflicting"):
        compile_recipe(assignment(planning=True, verification=True), factors=conflicting)


def test_shams_use_the_same_declared_resource_envelope_and_fidelity_checks_delivery_only() -> None:
    off = compile_recipe(assignment())
    on = compile_recipe(assignment(planning=True))
    assert off.mechanisms[0].mode == "sham"
    assert on.mechanisms[0].mode == "active"
    assert off.mechanisms[0].treatment_budget == on.mechanisms[0].treatment_budget
    observed_budgets = {mechanism.factor_id: mechanism.treatment_budget for mechanism in off.mechanisms}
    fidelity = check_manipulation_fidelity(off, off.assignment, observed_budgets, (evidence(),))
    assert all(item.delivered and item.compute_context_matched for item in fidelity)
    assert all(item.claim == "treatment_delivery_only" for item in fidelity)
    observed_budgets["planning"] = TreatmentBudget(compute_units=99, context_bytes=0)
    assert check_manipulation_fidelity(off, off.assignment, observed_budgets, (evidence(),))[0].delivered is False
    with pytest.raises(RecipeCompilationError, match="matched"):
        compile_recipe(assignment(), treatment_budgets={"planning": TreatmentBudget(compute_units=99, context_bytes=0)})


def test_episode_memory_model_refuses_cross_episode_state() -> None:
    with pytest.raises(ValidationError, match="cross-episode"):
        EpisodeMemory(
            episode_id="episode-one", max_items=2, max_bytes=100, total_bytes=1,
            items=(MemoryItem(item_id="item-one", episode_id="episode-two", content="x", source_pointers=(evidence(),)),),
        )
