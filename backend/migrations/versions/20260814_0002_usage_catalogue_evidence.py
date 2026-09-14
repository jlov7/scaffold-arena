"""persist observed aggregate usage and versioned price profiles

Revision ID: 20260814_0002
Revises: 20260814_0001
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0002"
down_revision = "20260814_0001"
branch_labels = None
depends_on = None


_USAGE_CHECK = (
    "(input_tokens IS NULL OR input_tokens >= 0) AND "
    "(output_tokens IS NULL OR output_tokens >= 0) AND "
    "(total_tokens IS NULL OR total_tokens >= 0) AND "
    "(context_tokens IS NULL OR context_tokens >= 0) AND "
    "(tool_calls IS NULL OR tool_calls >= 0) AND "
    "(reserved_max_tokens IS NULL OR reserved_max_tokens >= 0) AND "
    "(reserved_max_tool_calls IS NULL OR reserved_max_tool_calls >= 0)"
)


def upgrade() -> None:
    with op.batch_alter_table("usage_ledger", recreate="always") as batch:
        batch.drop_constraint("nonnegative_usage", type_="check")
        batch.drop_constraint("reconciled_cost_evidence", type_="check")
        batch.alter_column("input_tokens", existing_type=sa.Integer(), nullable=True, server_default=None)
        batch.alter_column("output_tokens", existing_type=sa.Integer(), nullable=True, server_default=None)
        batch.add_column(sa.Column("total_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("context_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("tool_calls", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reserved_max_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reserved_max_tool_calls", sa.Integer(), nullable=True))
        batch.create_check_constraint("nonnegative_usage", _USAGE_CHECK)
        batch.create_check_constraint(
            "reconciled_cost_evidence",
            "cost_status != 'reconciled' OR (cost_usd IS NOT NULL AND actual_cost_usd IS NOT NULL "
            "AND price_catalog_revision IS NOT NULL AND provider_usage_digest IS NOT NULL "
            "AND length(provider_usage_digest) = 64 AND input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND total_tokens IS NOT NULL "
            "AND total_tokens = input_tokens + output_tokens AND context_tokens IS NOT NULL "
            "AND tool_calls IS NOT NULL)",
        )
    with op.batch_alter_table("price_catalog", recreate="always") as batch:
        batch.drop_constraint("revision_model_provider_effective", type_="unique")
        batch.add_column(sa.Column("billing_profile", sa.String(length=128), nullable=False, server_default="standard"))
        batch.create_unique_constraint(
            "revision_model_provider_profile_effective",
            ["revision", "model_id", "provider", "billing_profile", "effective_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("price_catalog", recreate="always") as batch:
        batch.drop_constraint("revision_model_provider_profile_effective", type_="unique")
        batch.drop_column("billing_profile")
        batch.create_unique_constraint(
            "revision_model_provider_effective",
            ["revision", "model_id", "provider", "effective_at"],
        )
    with op.batch_alter_table("usage_ledger", recreate="always") as batch:
        batch.drop_constraint("nonnegative_usage", type_="check")
        batch.drop_constraint("reconciled_cost_evidence", type_="check")
        batch.drop_column("reserved_max_tool_calls")
        batch.drop_column("reserved_max_tokens")
        batch.drop_column("tool_calls")
        batch.drop_column("context_tokens")
        batch.drop_column("total_tokens")
        batch.alter_column("output_tokens", existing_type=sa.Integer(), nullable=False, server_default="0")
        batch.alter_column("input_tokens", existing_type=sa.Integer(), nullable=False, server_default="0")
        batch.create_check_constraint("nonnegative_usage", "input_tokens >= 0 AND output_tokens >= 0")
        batch.create_check_constraint("reconciled_cost_evidence", "cost_status != 'reconciled' OR (cost_usd IS NOT NULL AND actual_cost_usd IS NOT NULL AND price_catalog_revision IS NOT NULL AND provider_usage_digest IS NOT NULL AND length(provider_usage_digest) = 64)")
