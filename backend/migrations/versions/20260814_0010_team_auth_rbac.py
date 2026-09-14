"""add durable team OIDC identity, membership, session, and audit tables

Revision ID: 20260814_0010
Revises: 20260814_0009
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0010"
down_revision = "20260814_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("identity_users", sa.Column("id", sa.String(64), nullable=False), sa.Column("issuer", sa.Text(), nullable=False), sa.Column("subject", sa.String(512), nullable=False), sa.Column("email", sa.String(320)), sa.Column("display_name", sa.String(255)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("issuer", "subject", name="identity_issuer_subject"))
    op.create_table("project_memberships", sa.Column("project_id", sa.String(64), nullable=False), sa.Column("identity_user_id", sa.String(64), nullable=False), sa.Column("role", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["identity_user_id"], ["identity_users.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("project_id", "identity_user_id"), sa.CheckConstraint("role IN ('admin', 'operator', 'reviewer', 'viewer')", name="membership_role"))
    op.create_table("auth_sessions", sa.Column("id", sa.String(64), nullable=False), sa.Column("token_digest", sa.String(64), nullable=False), sa.Column("identity_user_id", sa.String(64), nullable=False), sa.Column("csrf_token", sa.String(128), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("rotated_from_id", sa.String(64)), sa.Column("last_seen_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["identity_user_id"], ["identity_users.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["rotated_from_id"], ["auth_sessions.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("token_digest"), sa.CheckConstraint("length(token_digest) = 64", name="session_token_digest"))
    op.create_index("ix_auth_sessions_identity_expires", "auth_sessions", ["identity_user_id", "expires_at"])
    op.create_table("oidc_login_transactions", sa.Column("id", sa.String(64), nullable=False), sa.Column("state_digest", sa.String(64), nullable=False), sa.Column("browser_binding_digest", sa.String(64), nullable=False), sa.Column("nonce", sa.String(128), nullable=False), sa.Column("code_verifier", sa.String(256), nullable=False), sa.Column("redirect_uri", sa.Text(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("consumed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("state_digest"), sa.CheckConstraint("length(state_digest) = 64", name="oidc_state_digest"), sa.CheckConstraint("length(browser_binding_digest) = 64", name="oidc_browser_binding_digest"))
    op.create_table("team_settings", sa.Column("project_id", sa.String(64), nullable=False), sa.Column("retention_days", sa.Integer()), sa.Column("updated_by_identity_user_id", sa.String(64)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["updated_by_identity_user_id"], ["identity_users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("project_id"), sa.CheckConstraint("retention_days IS NULL OR retention_days BETWEEN 1 AND 3650", name="retention_days_range"))
    op.create_table("team_audit_events", sa.Column("id", sa.String(64), nullable=False), sa.Column("request_id", sa.String(64), nullable=False), sa.Column("project_id", sa.String(64)), sa.Column("identity_user_id", sa.String(64)), sa.Column("event_type", sa.String(128), nullable=False), sa.Column("method", sa.String(16)), sa.Column("path", sa.Text()), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["identity_user_id"], ["identity_users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_team_audit_events_project_created", "team_audit_events", ["project_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute("CREATE TRIGGER team_audit_events_no_update BEFORE UPDATE ON team_audit_events BEGIN SELECT RAISE(ABORT, 'team audit events are append-only'); END")
        op.execute("CREATE TRIGGER team_audit_events_no_delete BEFORE DELETE ON team_audit_events BEGIN SELECT RAISE(ABORT, 'team audit events are append-only'); END")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION scaffold_arena_team_audit_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'team audit events are append-only'; RETURN NULL; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER team_audit_events_no_mutation BEFORE UPDATE OR DELETE ON team_audit_events FOR EACH ROW EXECUTE FUNCTION scaffold_arena_team_audit_append_only()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER team_audit_events_no_update")
        op.execute("DROP TRIGGER team_audit_events_no_delete")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER team_audit_events_no_mutation ON team_audit_events")
        op.execute("DROP FUNCTION scaffold_arena_team_audit_append_only()")
    op.drop_index("ix_team_audit_events_project_created", table_name="team_audit_events")
    op.drop_table("team_audit_events")
    op.drop_table("team_settings")
    op.drop_table("oidc_login_transactions")
    op.drop_index("ix_auth_sessions_identity_expires", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("project_memberships")
    op.drop_table("identity_users")
