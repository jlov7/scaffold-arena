"""Bounded executable model for invocation fencing and reservation settlement.

This is deliberately independent from persistence and provider adapters.  It
exhaustively explores a small lifecycle (two generations, two result digests)
and fails on a safety invariant before the implementation tests run.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


Admission = Literal["current", "stale", "duplicate"]
Cancellation = Literal[
    "not_requested",
    "requested",
    "dispatched",
    "acknowledged",
    "unsupported",
    "unknown",
]
Reservation = Literal[
    "none",
    "reserved",
    "committed",
    "released",
    "expired",
    "unknown_usage",
    "disputed",
]

TERMINAL_RESERVATIONS = frozenset(
    {"committed", "released", "expired", "unknown_usage", "disputed"}
)
TERMINAL_CANCELLATIONS = frozenset({"acknowledged", "unsupported", "unknown"})
INVARIANTS = (
    "stale_generations_cannot_finalize_current_truth",
    "post_dispatch_unknown_usage_never_releases_as_zero",
    "settled_reservations_are_monotonic",
    "cancellation_terminal_states_are_monotonic",
    "duplicate_request_identity_is_not_independent_execution",
    "external_result_is_admitted_once",
    "budget_is_not_double_committed",
)


class InvariantViolation(AssertionError):
    """The bounded model reached a state forbidden by the lifecycle contract."""


@dataclass(frozen=True)
class Invocation:
    generation: int
    admission: Admission
    dispatched: bool = False
    cancellation: Cancellation = "not_requested"
    reservation: Reservation = "none"
    result_digest: str | None = None
    budget_committed: bool = False
    observed_request_identity: bool = False


@dataclass(frozen=True)
class LifecycleState:
    invocations: tuple[Invocation, ...] = ()
    request_owner_generation: int | None = None
    result_owners: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class ModelReport:
    max_depth: int
    max_generations: int
    states_checked: int
    transitions_checked: int
    invariants: tuple[str, ...] = INVARIANTS


class LifecycleModel:
    """Small state machine with only transitions that the durable protocol permits."""

    def __init__(self, *, max_generations: int = 2) -> None:
        if max_generations < 1:
            raise ValueError("max_generations must be positive")
        self.max_generations = max_generations

    def begin(self, state: LifecycleState) -> LifecycleState | None:
        if len(state.invocations) >= self.max_generations or self.current(state):
            return None
        generation = len(state.invocations) + 1
        return replace(
            state,
            invocations=state.invocations
            + (Invocation(generation=generation, admission="current"),),
        )

    def expire_lease(self, state: LifecycleState, generation: int) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if invocation is None or invocation.admission != "current":
            return None
        return self.replace_invocation(
            state,
            replace(invocation, admission="stale"),
        )

    def reserve(self, state: LifecycleState, generation: int) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if (
            invocation is None
            or invocation.admission != "current"
            or invocation.reservation != "none"
        ):
            return None
        return self.replace_invocation(state, replace(invocation, reservation="reserved"))

    def dispatch(self, state: LifecycleState, generation: int) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if (
            invocation is None
            or invocation.admission != "current"
            or invocation.dispatched
            or invocation.reservation in TERMINAL_RESERVATIONS
        ):
            return None
        return self.replace_invocation(state, replace(invocation, dispatched=True))

    def admit_result(
        self,
        state: LifecycleState,
        generation: int,
        result_digest: str,
    ) -> LifecycleState | None:
        invocation = self.get(state, generation)
        owners = dict(state.result_owners)
        if (
            invocation is None
            or invocation.admission != "current"
            or invocation.result_digest is not None
            or result_digest in owners
        ):
            return None
        next_state = self.replace_invocation(
            state,
            replace(invocation, result_digest=result_digest),
        )
        return replace(
            next_state,
            result_owners=tuple(sorted((*next_state.result_owners, (result_digest, generation)))),
        )

    def commit_budget(self, state: LifecycleState, generation: int) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if (
            invocation is None
            or invocation.reservation != "reserved"
            or invocation.result_digest is None
            or invocation.budget_committed
        ):
            return None
        return self.replace_invocation(
            state,
            replace(invocation, reservation="committed", budget_committed=True),
        )

    def settle_unknown_or_release(
        self,
        state: LifecycleState,
        generation: int,
    ) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if invocation is None or invocation.reservation != "reserved":
            return None
        reservation: Reservation = "unknown_usage" if invocation.dispatched else "released"
        return self.replace_invocation(state, replace(invocation, reservation=reservation))

    def dispute_budget(self, state: LifecycleState, generation: int) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if invocation is None or invocation.reservation != "reserved":
            return None
        return self.replace_invocation(state, replace(invocation, reservation="disputed"))

    def observe_request_identity(
        self,
        state: LifecycleState,
        generation: int,
    ) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if (
            invocation is None
            or invocation.observed_request_identity
            or invocation.result_digest is not None
        ):
            return None
        owner = state.request_owner_generation
        if owner is None:
            next_state = self.replace_invocation(
                state,
                replace(invocation, observed_request_identity=True),
            )
            return replace(next_state, request_owner_generation=generation)
        if owner == generation:
            return None
        return self.replace_invocation(
            state,
            replace(
                invocation,
                admission="duplicate",
                observed_request_identity=True,
            ),
        )

    def advance_cancellation(
        self,
        state: LifecycleState,
        generation: int,
        cancellation: Cancellation,
    ) -> LifecycleState | None:
        invocation = self.get(state, generation)
        if invocation is None or not self._is_next_cancellation(invocation.cancellation, cancellation):
            return None
        return self.replace_invocation(state, replace(invocation, cancellation=cancellation))

    def successors(self, state: LifecycleState) -> tuple[tuple[str, LifecycleState], ...]:
        transitions: list[tuple[str, LifecycleState]] = []

        def add(label: str, candidate: LifecycleState | None) -> None:
            if candidate is not None:
                transitions.append((label, candidate))

        add("begin", self.begin(state))
        for invocation in state.invocations:
            generation = invocation.generation
            add(f"expire:{generation}", self.expire_lease(state, generation))
            add(f"reserve:{generation}", self.reserve(state, generation))
            add(f"dispatch:{generation}", self.dispatch(state, generation))
            add(f"observe-request:{generation}", self.observe_request_identity(state, generation))
            add(f"admit:{generation}:rA", self.admit_result(state, generation, "rA"))
            add(f"admit:{generation}:rB", self.admit_result(state, generation, "rB"))
            add(f"commit:{generation}", self.commit_budget(state, generation))
            add(f"settle:{generation}", self.settle_unknown_or_release(state, generation))
            add(f"dispute:{generation}", self.dispute_budget(state, generation))
            for cancellation in self._next_cancellations(invocation.cancellation):
                add(
                    f"cancel:{generation}:{cancellation}",
                    self.advance_cancellation(state, generation, cancellation),
                )
        return tuple(transitions)

    @staticmethod
    def get(state: LifecycleState, generation: int) -> Invocation | None:
        return next(
            (item for item in state.invocations if item.generation == generation),
            None,
        )

    @staticmethod
    def current(state: LifecycleState) -> Invocation | None:
        return next(
            (item for item in state.invocations if item.admission == "current"),
            None,
        )

    @staticmethod
    def replace_invocation(state: LifecycleState, next_invocation: Invocation) -> LifecycleState:
        return replace(
            state,
            invocations=tuple(
                next_invocation if item.generation == next_invocation.generation else item
                for item in state.invocations
            ),
        )

    @staticmethod
    def _next_cancellations(current: Cancellation) -> tuple[Cancellation, ...]:
        if current == "not_requested":
            return ("requested",)
        if current == "requested":
            return ("dispatched",)
        if current == "dispatched":
            return ("acknowledged", "unsupported", "unknown")
        return ()

    @classmethod
    def _is_next_cancellation(
        cls,
        current: Cancellation,
        candidate: Cancellation,
    ) -> bool:
        return candidate in cls._next_cancellations(current)


def verify_bounded_lifecycle(
    *,
    max_depth: int = 8,
    max_generations: int = 2,
) -> ModelReport:
    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    model = LifecycleModel(max_generations=max_generations)
    initial = LifecycleState()
    frontier: list[tuple[LifecycleState, int]] = [(initial, 0)]
    seen = {initial}
    states_checked = 0
    transitions_checked = 0

    while frontier:
        state, depth = frontier.pop()
        _assert_state(state)
        states_checked += 1
        if depth >= max_depth:
            continue
        for _label, next_state in model.successors(state):
            _assert_transition(state, next_state)
            _assert_state(next_state)
            transitions_checked += 1
            if next_state not in seen:
                seen.add(next_state)
                frontier.append((next_state, depth + 1))

    return ModelReport(
        max_depth=max_depth,
        max_generations=max_generations,
        states_checked=states_checked,
        transitions_checked=transitions_checked,
    )


def _assert_state(state: LifecycleState) -> None:
    current = [item for item in state.invocations if item.admission == "current"]
    if len(current) > 1:
        raise InvariantViolation("more than one generation is current")
    if current and current[0].generation != max(
        item.generation for item in state.invocations
    ):
        raise InvariantViolation("an older generation remained current")

    owners = dict(state.result_owners)
    if len(owners) != len(state.result_owners):
        raise InvariantViolation("one external result was admitted twice")
    for invocation in state.invocations:
        if invocation.result_digest is not None and owners.get(invocation.result_digest) != invocation.generation:
            raise InvariantViolation("result owner does not match an admitted generation")
        if invocation.admission == "duplicate" and invocation.result_digest is not None:
            raise InvariantViolation("duplicate request identity admitted an independent result")
        if invocation.dispatched and invocation.reservation == "released":
            raise InvariantViolation("post-dispatch usage was released as zero")
        if invocation.budget_committed != (invocation.reservation == "committed"):
            raise InvariantViolation("budget commit and reservation state diverged")
        if invocation.reservation == "committed" and invocation.result_digest is None:
            raise InvariantViolation("budget committed without one admitted provider result")
        if (
            invocation.observed_request_identity
            and state.request_owner_generation is None
        ):
            raise InvariantViolation("observed request identity has no owner")


def _assert_transition(previous: LifecycleState, next_state: LifecycleState) -> None:
    before = {item.generation: item for item in previous.invocations}
    after = {item.generation: item for item in next_state.invocations}
    for generation, earlier in before.items():
        later = after[generation]
        if earlier.reservation in TERMINAL_RESERVATIONS and later.reservation != earlier.reservation:
            raise InvariantViolation("settled reservation regressed")
        if earlier.cancellation in TERMINAL_CANCELLATIONS and later.cancellation != earlier.cancellation:
            raise InvariantViolation("terminal cancellation state regressed")
        if earlier.result_digest is not None and later.result_digest != earlier.result_digest:
            raise InvariantViolation("admitted external result changed")
        if earlier.budget_committed and not later.budget_committed:
            raise InvariantViolation("budget commitment regressed")
