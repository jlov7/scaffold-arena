"""Immutable, evidence-bound plan state transitions."""

from __future__ import annotations

from .models import EvidencePointer, PlanArtifact, PlanStep

_TRANSITIONS = {
    "pending": {"in_progress"},
    "in_progress": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


def create_plan(*, episode_id: str, plan_id: str, steps: tuple[tuple[str, str], ...]) -> PlanArtifact:
    return PlanArtifact(episode_id=episode_id, plan_id=plan_id, steps=tuple(PlanStep(step_id=step_id, description=description) for step_id, description in steps))


def transition_plan_step(
    plan: PlanArtifact, *, step_id: str, state: str, evidence: EvidencePointer | None = None
) -> PlanArtifact:
    """Return a new plan after one legal transition; completed is evidence-gated."""
    current = next((step for step in plan.steps if step.step_id == step_id), None)
    if current is None:
        raise ValueError("unknown plan step")
    if state not in _TRANSITIONS[current.state]:
        raise ValueError(f"invalid plan transition: {current.state} -> {state}")
    if state in {"completed", "failed"} and evidence is None:
        raise ValueError("terminal plan steps require terminal evidence")
    if state not in {"completed", "failed"} and evidence is not None:
        raise ValueError("terminal evidence is only valid for terminal steps")
    replacement = PlanStep(step_id=current.step_id, description=current.description, state=state, terminal_evidence=evidence)
    return plan.model_copy(update={"steps": tuple(replacement if step.step_id == step_id else step for step in plan.steps)})
