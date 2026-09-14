from __future__ import annotations

from execution_v1.formal_model import LifecycleModel, LifecycleState, verify_bounded_lifecycle


def test_bounded_lifecycle_model_checks_the_required_safety_invariants() -> None:
    report = verify_bounded_lifecycle()

    assert report.states_checked > 100
    assert report.transitions_checked > report.states_checked
    assert report.invariants == (
        "stale_generations_cannot_finalize_current_truth",
        "post_dispatch_unknown_usage_never_releases_as_zero",
        "settled_reservations_are_monotonic",
        "cancellation_terminal_states_are_monotonic",
        "duplicate_request_identity_is_not_independent_execution",
        "external_result_is_admitted_once",
        "budget_is_not_double_committed",
    )


def test_generation_lease_expiry_and_delayed_result_are_fenced() -> None:
    model = LifecycleModel()
    state = model.begin(LifecycleState())
    assert state is not None
    state = model.reserve(state, 1)
    assert state is not None
    state = model.dispatch(state, 1)
    assert state is not None
    state = model.expire_lease(state, 1)
    assert state is not None
    state = model.begin(state)
    assert state is not None

    assert model.admit_result(state, 1, "rA") is None
    admitted = model.admit_result(state, 2, "rA")
    assert admitted is not None
    assert admitted.invocations[0].admission == "stale"
    assert admitted.invocations[1].result_digest == "rA"


def test_duplicate_provider_identity_cannot_create_an_independent_effect() -> None:
    model = LifecycleModel()
    state = model.begin(LifecycleState())
    assert state is not None
    state = model.observe_request_identity(state, 1)
    assert state is not None
    state = model.expire_lease(state, 1)
    assert state is not None
    state = model.begin(state)
    assert state is not None

    duplicate = model.observe_request_identity(state, 2)
    assert duplicate is not None
    assert duplicate.invocations[1].admission == "duplicate"
    assert model.admit_result(duplicate, 2, "rA") is None


def test_reservation_unknown_dispute_commit_and_cancellation_are_terminal_monotonic() -> None:
    model = LifecycleModel()
    state = model.begin(LifecycleState())
    assert state is not None
    state = model.reserve(state, 1)
    assert state is not None
    state = model.dispatch(state, 1)
    assert state is not None
    unknown = model.settle_unknown_or_release(state, 1)
    assert unknown is not None
    assert unknown.invocations[0].reservation == "unknown_usage"
    assert model.dispute_budget(unknown, 1) is None

    state = model.begin(LifecycleState())
    assert state is not None
    state = model.reserve(state, 1)
    assert state is not None
    disputed = model.dispute_budget(state, 1)
    assert disputed is not None
    assert disputed.invocations[0].reservation == "disputed"
    assert model.settle_unknown_or_release(disputed, 1) is None

    state = model.begin(LifecycleState())
    assert state is not None
    state = model.reserve(state, 1)
    assert state is not None
    state = model.admit_result(state, 1, "rA")
    assert state is not None
    committed = model.commit_budget(state, 1)
    assert committed is not None
    assert committed.invocations[0].budget_committed is True
    assert model.commit_budget(committed, 1) is None

    state = model.advance_cancellation(LifecycleState(invocations=committed.invocations), 1, "requested")
    assert state is not None
    state = model.advance_cancellation(state, 1, "dispatched")
    assert state is not None
    terminal = model.advance_cancellation(state, 1, "acknowledged")
    assert terminal is not None
    assert model.advance_cancellation(terminal, 1, "requested") is None


def test_one_admitted_external_result_cannot_be_replaced() -> None:
    model = LifecycleModel()
    state = model.begin(LifecycleState())
    assert state is not None
    first = model.admit_result(state, 1, "rA")
    assert first is not None
    assert model.admit_result(first, 1, "rB") is None
