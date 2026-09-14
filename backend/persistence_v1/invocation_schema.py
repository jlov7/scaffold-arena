"""Additive persistence contracts for invocation fencing and reservation state."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

from .schema import metadata, usage_ledger


# `usage_ledger` remains the numerical source of truth. Replace the original
# cost-status check by predicate rather than generated constraint name: the
# metadata naming convention prefixes explicit names on some dialects.
for _constraint in tuple(usage_ledger.constraints):
    if (
        isinstance(_constraint, CheckConstraint)
        and "cost_status IN" in str(_constraint.sqltext)
    ):
        usage_ledger.constraints.remove(_constraint)
usage_ledger.append_constraint(
    CheckConstraint(
        "cost_status IN ('reserved', 'estimated', 'reconciled', 'unknown', 'mismatch', 'released', 'expired')",
        name="valid_cost_status",
    )
)


invocation_records = Table(
    "invocation_records",
    metadata,
    Column("id", String(128), primary_key=True),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "job_id",
        String(64),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("generation", Integer, nullable=False),
    Column("fence_token", String(64), nullable=False),
    Column("provider", String(128), nullable=False),
    Column("provider_model", String(255), nullable=False),
    Column("provider_idempotency_key", String(255), nullable=False),
    Column("provider_request_namespace", String(64), nullable=False),
    Column("provider_request_id", String(512), nullable=True),
    Column("lease_owner", String(255), nullable=False),
    Column("lease_acquired_at", DateTime(timezone=True), nullable=False),
    Column("lease_expires_at", DateTime(timezone=True), nullable=False),
    Column("dispatch_started_at", DateTime(timezone=True), nullable=True),
    Column("aggregate_deadline_at", DateTime(timezone=True), nullable=True),
    Column("transport_context_state", String(32), nullable=False, server_default="unknown"),
    Column("cancellation_state", String(32), nullable=False, server_default="not_requested"),
    Column("side_effect_state", String(32), nullable=False, server_default="not_started"),
    Column("usage_state", String(32), nullable=False, server_default="not_observed"),
    Column("admission_state", String(32), nullable=False, server_default="current"),
    Column("provider_result_digest", String(64), nullable=True),
    Column("terminal_outcome", String(32), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("terminal_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("attempt_id", "generation", name="invocation_attempt_generation"),
    UniqueConstraint("fence_token", name="invocation_fence_token"),
    CheckConstraint("generation >= 1", name="invocation_positive_generation"),
    CheckConstraint("length(fence_token) = 64", name="invocation_fence_digest"),
    CheckConstraint(
        "length(provider_request_namespace) = 64",
        name="invocation_request_namespace_digest",
    ),
    CheckConstraint(
        "provider_result_digest IS NULL OR length(provider_result_digest) = 64",
        name="invocation_result_digest",
    ),
    CheckConstraint(
        "transport_context_state IN ('unknown', 'supported', 'unsupported')",
        name="invocation_transport_context_state",
    ),
    CheckConstraint(
        "cancellation_state IN ('not_requested', 'requested', 'dispatched', 'acknowledged', 'unsupported', 'unknown')",
        name="invocation_cancellation_state",
    ),
    CheckConstraint(
        "side_effect_state IN ('not_started', 'possible', 'observed', 'reconciled', 'ambiguous')",
        name="invocation_side_effect_state",
    ),
    CheckConstraint(
        "usage_state IN ('not_observed', 'observed', 'reconciled', 'unknown', 'disputed')",
        name="invocation_usage_state",
    ),
    CheckConstraint(
        "admission_state IN ('current', 'stale', 'duplicate', 'ambiguous')",
        name="invocation_admission_state",
    ),
)
Index(
    "ix_invocation_attempt_generation",
    invocation_records.c.attempt_id,
    invocation_records.c.generation,
)
Index(
    "ix_invocation_execution_admission",
    invocation_records.c.execution_id,
    invocation_records.c.admission_state,
)
Index(
    "ix_invocation_provider_request",
    invocation_records.c.provider_request_namespace,
    invocation_records.c.provider_request_id,
)


budget_reservations = Table(
    "budget_reservations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "ledger_id",
        String(64),
        ForeignKey("usage_ledger.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "execution_id",
        String(64),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "attempt_id",
        String(64),
        ForeignKey("attempts.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "invocation_id",
        String(128),
        ForeignKey("invocation_records.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("state", String(32), nullable=False),
    Column("reason", Text, nullable=True),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("reserved_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("terminal_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("ledger_id", name="budget_reservation_ledger"),
    CheckConstraint(
        "state IN ('requested', 'reserved', 'committed', 'released', 'expired', 'disputed', 'unknown_usage')",
        name="budget_reservation_state",
    ),
    CheckConstraint("version >= 1", name="budget_reservation_positive_version"),
)
Index(
    "ix_budget_reservation_execution_state",
    budget_reservations.c.execution_id,
    budget_reservations.c.state,
)
Index(
    "ix_budget_reservation_invocation",
    budget_reservations.c.invocation_id,
)
