"""add invocation fencing and reservation lifecycle

Revision ID: 20260816_0012
Revises: 20260814_0011
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "20260816_0012"
down_revision = "20260814_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usage_ledger") as batch:
        batch.drop_constraint("valid_cost_status", type_="check")
        batch.create_check_constraint(
            "valid_cost_status",
            "cost_status IN ('reserved', 'estimated', 'reconciled', 'unknown', 'mismatch', 'released', 'expired')",
        )

    op.create_table(
        "invocation_records",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("attempt_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("fence_token", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("provider_model", sa.String(255), nullable=False),
        sa.Column("provider_idempotency_key", sa.String(255), nullable=False),
        sa.Column("provider_request_id", sa.String(512)),
        sa.Column("lease_owner", sa.String(255), nullable=False),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True)),
        sa.Column("aggregate_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("transport_context_state", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("cancellation_state", sa.String(32), nullable=False, server_default="not_requested"),
        sa.Column("side_effect_state", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("usage_state", sa.String(32), nullable=False, server_default="not_observed"),
        sa.Column("admission_state", sa.String(32), nullable=False, server_default="current"),
        sa.Column("provider_result_digest", sa.String(64)),
        sa.Column("terminal_outcome", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "generation", name="invocation_attempt_generation"),
        sa.UniqueConstraint("fence_token", name="invocation_fence_token"),
        sa.CheckConstraint("generation >= 1", name="invocation_positive_generation"),
        sa.CheckConstraint("length(fence_token) = 64", name="invocation_fence_digest"),
        sa.CheckConstraint("provider_result_digest IS NULL OR length(provider_result_digest) = 64", name="invocation_result_digest"),
        sa.CheckConstraint("transport_context_state IN ('unknown', 'supported', 'unsupported')", name="invocation_transport_context_state"),
        sa.CheckConstraint("cancellation_state IN ('not_requested', 'requested', 'dispatched', 'acknowledged', 'unsupported', 'unknown')", name="invocation_cancellation_state"),
        sa.CheckConstraint("side_effect_state IN ('not_started', 'possible', 'observed', 'reconciled', 'ambiguous')", name="invocation_side_effect_state"),
        sa.CheckConstraint("usage_state IN ('not_observed', 'observed', 'reconciled', 'unknown', 'disputed')", name="invocation_usage_state"),
        sa.CheckConstraint("admission_state IN ('current', 'stale', 'duplicate', 'ambiguous')", name="invocation_admission_state"),
    )
    op.create_index("ix_invocation_attempt_generation", "invocation_records", ["attempt_id", "generation"])
    op.create_index("ix_invocation_execution_admission", "invocation_records", ["execution_id", "admission_state"])
    op.create_index("ix_invocation_provider_request", "invocation_records", ["provider", "provider_request_id"])

    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("ledger_id", sa.String(64), nullable=False),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("attempt_id", sa.String(64)),
        sa.Column("invocation_id", sa.String(128)),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["ledger_id"], ["usage_ledger.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invocation_id"], ["invocation_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ledger_id", name="budget_reservation_ledger"),
        sa.CheckConstraint("state IN ('requested', 'reserved', 'committed', 'released', 'expired', 'disputed', 'unknown_usage')", name="budget_reservation_state"),
        sa.CheckConstraint("version >= 1", name="budget_reservation_positive_version"),
    )
    op.create_index("ix_budget_reservation_execution_state", "budget_reservations", ["execution_id", "state"])
    op.create_index("ix_budget_reservation_invocation", "budget_reservations", ["invocation_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_reservation_invocation", table_name="budget_reservations")
    op.drop_index("ix_budget_reservation_execution_state", table_name="budget_reservations")
    op.drop_table("budget_reservations")
    op.drop_index("ix_invocation_provider_request", table_name="invocation_records")
    op.drop_index("ix_invocation_execution_admission", table_name="invocation_records")
    op.drop_index("ix_invocation_attempt_generation", table_name="invocation_records")
    op.drop_table("invocation_records")
    op.execute("UPDATE usage_ledger SET cost_status = 'unknown', cost_usd = NULL, actual_cost_usd = NULL, price_catalog_revision = NULL, provider_usage_digest = NULL WHERE cost_status IN ('released', 'expired')")
    with op.batch_alter_table("usage_ledger") as batch:
        batch.drop_constraint("valid_cost_status", type_="check")
        batch.create_check_constraint(
            "valid_cost_status",
            "cost_status IN ('reserved', 'estimated', 'reconciled', 'unknown', 'mismatch')",
        )
