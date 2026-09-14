"""add recoverable project retention plans and independent tombstones

Revision ID: 20260814_0011
Revises: 20260814_0010
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0011"
down_revision = "20260814_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("deletion_plans", sa.Column("id", sa.String(64), nullable=False), sa.Column("project_id", sa.String(64), nullable=False), sa.Column("state", sa.String(16), nullable=False), sa.Column("snapshot_digest", sa.String(64), nullable=False), sa.Column("confirmation_digest", sa.String(64), nullable=False), sa.Column("grace_seconds", sa.Integer(), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True), nullable=False), sa.Column("scheduled_by_identity_user_id", sa.String(64)), sa.Column("cancelled_at", sa.DateTime(timezone=True)), sa.Column("cancelled_by_identity_user_id", sa.String(64)), sa.Column("executed_at", sa.DateTime(timezone=True)), sa.Column("executed_by_identity_user_id", sa.String(64)), sa.Column("purged_idempotency_records", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["scheduled_by_identity_user_id"], ["identity_users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["cancelled_by_identity_user_id"], ["identity_users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["executed_by_identity_user_id"], ["identity_users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"), sa.CheckConstraint("state IN ('scheduled', 'cancelled', 'executed', 'blocked')", name="deletion_plan_state"), sa.CheckConstraint("length(snapshot_digest) = 64 AND length(confirmation_digest) = 64", name="deletion_plan_digests"), sa.CheckConstraint("grace_seconds BETWEEN 60 AND 2592000", name="deletion_plan_grace"), sa.CheckConstraint("purged_idempotency_records IS NULL OR purged_idempotency_records >= 0", name="deletion_plan_purge_count"))
    op.create_index("ix_deletion_plans_project_due", "deletion_plans", ["project_id", "due_at"])
    op.create_table("deletion_tombstones", sa.Column("id", sa.String(64), nullable=False), sa.Column("project_id", sa.String(64), nullable=False), sa.Column("plan_id", sa.String(64), nullable=False), sa.Column("snapshot_digest", sa.String(64), nullable=False), sa.Column("export_manifest_digest", sa.String(64), nullable=False), sa.Column("purged_idempotency_records", sa.Integer(), nullable=False), sa.Column("claim_ceiling", sa.Text(), nullable=False), sa.Column("executed_by_identity_user_id", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["export_manifest_digest"], ["artifacts.digest"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["executed_by_identity_user_id"], ["identity_users.id"], name="fk_tombstones_executed_identity", ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("plan_id"), sa.CheckConstraint("length(snapshot_digest) = 64 AND length(export_manifest_digest) = 64", name="deletion_tombstone_digests"), sa.CheckConstraint("purged_idempotency_records >= 0", name="deletion_tombstone_purge_count"))
    if op.get_bind().dialect.name == "sqlite":
        op.execute("CREATE TRIGGER deletion_tombstones_no_update BEFORE UPDATE ON deletion_tombstones BEGIN SELECT RAISE(ABORT, 'deletion tombstones are append-only'); END")
        op.execute("CREATE TRIGGER deletion_tombstones_no_delete BEFORE DELETE ON deletion_tombstones BEGIN SELECT RAISE(ABORT, 'deletion tombstones are append-only'); END")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION scaffold_arena_deletion_tombstone_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'deletion tombstones are append-only'; RETURN NULL; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER deletion_tombstones_no_mutation BEFORE UPDATE OR DELETE ON deletion_tombstones FOR EACH ROW EXECUTE FUNCTION scaffold_arena_deletion_tombstone_append_only()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER deletion_tombstones_no_update")
        op.execute("DROP TRIGGER deletion_tombstones_no_delete")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER deletion_tombstones_no_mutation ON deletion_tombstones")
        op.execute("DROP FUNCTION scaffold_arena_deletion_tombstone_append_only()")
    op.drop_table("deletion_tombstones")
    op.drop_index("ix_deletion_plans_project_due", table_name="deletion_plans")
    op.drop_table("deletion_plans")
