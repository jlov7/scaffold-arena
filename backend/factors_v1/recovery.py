"""Fail-closed authorization for checkpoint-based transient recovery."""

from __future__ import annotations

from .models import CheckpointArtifact, FailureEvent, RecoveryDecision, RecoveryPolicy


def authorize_recovery(
    failure: FailureEvent,
    checkpoint: CheckpointArtifact | None,
    policy: RecoveryPolicy,
    *,
    retries_used: int,
    idempotency_key: str,
    observed_checkpoint_sequences: frozenset[int],
    used_idempotency_keys: frozenset[str] = frozenset(),
) -> RecoveryDecision:
    """Authorize a retry only when the failure, checkpoint and retry ledger all agree."""
    if not idempotency_key:
        raise ValueError("recovery requires an idempotency key")
    if idempotency_key in used_idempotency_keys:
        return RecoveryDecision(allowed=False, reason="idempotency key was already used", idempotency_key=idempotency_key)
    if retries_used < 0:
        raise ValueError("retries_used cannot be negative")
    if failure.failure_class != "transient":
        return RecoveryDecision(allowed=False, reason="only declared transient failures may recover", idempotency_key=idempotency_key)
    if failure.failure_id not in policy.declared_transient_failures:
        return RecoveryDecision(allowed=False, reason="transient failure is not declared by policy", idempotency_key=idempotency_key)
    if retries_used >= policy.max_retries:
        return RecoveryDecision(allowed=False, reason="recovery retry budget exhausted", idempotency_key=idempotency_key)
    if checkpoint is None:
        return RecoveryDecision(allowed=False, reason="recovery requires checkpoint provenance", idempotency_key=idempotency_key)
    if checkpoint.provenance.content_hash != checkpoint.state_hash:
        return RecoveryDecision(allowed=False, reason="checkpoint provenance does not bind its state hash", idempotency_key=idempotency_key)
    if checkpoint.episode_id != failure.episode_id or checkpoint.attempt_id != failure.attempt_id:
        return RecoveryDecision(allowed=False, reason="checkpoint provenance does not belong to the failed attempt", idempotency_key=idempotency_key)
    if checkpoint.sequence not in observed_checkpoint_sequences:
        return RecoveryDecision(allowed=False, reason="checkpoint sequence was not observed for the failed attempt", idempotency_key=idempotency_key)
    return RecoveryDecision(allowed=True, reason="declared transient failure may recover", retry_number=retries_used + 1, idempotency_key=idempotency_key, checkpoint_id=checkpoint.checkpoint_id)
