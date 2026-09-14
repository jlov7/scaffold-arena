"""add immutable Genome v1 and ACP bridge query indexes

Revision ID: 20260818_0014
Revises: 20260817_0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0014"
down_revision = "20260817_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("genomes", sa.Column("id", sa.String(128), primary_key=True), sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False), sa.Column("schema", sa.String(64), nullable=False), sa.Column("digest", sa.String(64), nullable=False), sa.Column("descriptor_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False), sa.Column("authority_status", sa.String(32), nullable=False), sa.Column("claim_ceiling", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("project_id", "digest", name="uq_genomes_project_digest"), sa.CheckConstraint("length(digest) = 64 AND length(descriptor_artifact_digest) = 64", name="genomes_digests"))
    op.create_index("ix_genomes_project_created", "genomes", ["project_id", "created_at"])
    op.create_table("genome_sources", sa.Column("genome_id", sa.String(128), sa.ForeignKey("genomes.id", ondelete="CASCADE"), primary_key=True), sa.Column("source_id", sa.String(128), primary_key=True), sa.Column("uri", sa.Text(), nullable=False), sa.Column("revision", sa.Text()), sa.Column("content_digest", sa.String(64)), sa.Column("source_date", sa.String(10)), sa.Column("license_spdx", sa.String(128)), sa.Column("provenance", sa.String(32), nullable=False))
    op.create_table("genome_certifications", sa.Column("id", sa.String(128), primary_key=True), sa.Column("genome_id", sa.String(128), sa.ForeignKey("genomes.id", ondelete="RESTRICT"), nullable=False), sa.Column("checker_digest", sa.String(64), nullable=False), sa.Column("result_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False), sa.Column("verdict", sa.String(16), nullable=False), sa.Column("authority_ceiling", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="genome_certification_verdict"))
    op.create_table("acp_registry_snapshots", sa.Column("id", sa.String(128), primary_key=True), sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False), sa.Column("registry_schema_version", sa.String(64), nullable=False), sa.Column("source_revision", sa.Text()), sa.Column("content_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("id", "project_id", name="uq_acp_snapshot_id_project"))
    op.create_table("acp_identities", sa.Column("id", sa.String(128), primary_key=True), sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False), sa.Column("snapshot_id", sa.String(128), sa.ForeignKey("acp_registry_snapshots.id", ondelete="RESTRICT"), nullable=False), sa.Column("agent_id", sa.String(128), nullable=False), sa.Column("version", sa.String(128), nullable=False), sa.Column("distribution_ref", sa.Text(), nullable=False), sa.Column("distribution_digest", sa.String(64), nullable=False), sa.Column("argv_digest", sa.String(64), nullable=False), sa.Column("license_spdx", sa.String(128)), sa.Column("approval_status", sa.String(32), nullable=False, server_default="pending"), sa.UniqueConstraint("project_id", "snapshot_id", "agent_id", name="uq_acp_identity_project_snapshot_agent"), sa.UniqueConstraint("id", "project_id", name="uq_acp_identity_id_project"), sa.ForeignKeyConstraint(["snapshot_id", "project_id"], ["acp_registry_snapshots.id", "acp_registry_snapshots.project_id"], name="fk_acp_identity_snapshot_project"))
    op.create_table("acp_bridge_runs", sa.Column("id", sa.String(128), primary_key=True), sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False), sa.Column("identity_id", sa.String(128), sa.ForeignKey("acp_identities.id", ondelete="RESTRICT"), nullable=False), sa.Column("policy_digest", sa.String(64), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("transcript_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT")), sa.Column("receipt_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT")), sa.Column("cancellation_status", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["identity_id", "project_id"], ["acp_identities.id", "acp_identities.project_id"], name="fk_acp_run_identity_project"))
    op.create_index("ix_acp_bridge_runs_project_created", "acp_bridge_runs", ["project_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute("CREATE TRIGGER acp_identity_project_matches_snapshot BEFORE INSERT ON acp_identities BEGIN SELECT CASE WHEN (SELECT project_id FROM acp_registry_snapshots WHERE id = NEW.snapshot_id) != NEW.project_id THEN RAISE(ABORT, 'ACP identity project must match registry snapshot project') END; END")
        op.execute("CREATE TRIGGER acp_run_project_matches_identity BEFORE INSERT ON acp_bridge_runs BEGIN SELECT CASE WHEN (SELECT project_id FROM acp_identities WHERE id = NEW.identity_id) != NEW.project_id THEN RAISE(ABORT, 'ACP run project must match identity project') END; END")
        op.execute("CREATE TRIGGER acp_identity_identity_is_immutable BEFORE UPDATE OF project_id, snapshot_id ON acp_identities BEGIN SELECT RAISE(ABORT, 'ACP identity project and snapshot are immutable'); END")
        op.execute("CREATE TRIGGER acp_run_identity_is_immutable BEFORE UPDATE OF project_id, identity_id ON acp_bridge_runs BEGIN SELECT RAISE(ABORT, 'ACP run project and identity are immutable'); END")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS acp_run_identity_is_immutable")
        op.execute("DROP TRIGGER IF EXISTS acp_identity_identity_is_immutable")
        op.execute("DROP TRIGGER IF EXISTS acp_run_project_matches_identity")
        op.execute("DROP TRIGGER IF EXISTS acp_identity_project_matches_snapshot")
    op.drop_index("ix_acp_bridge_runs_project_created", table_name="acp_bridge_runs")
    op.drop_table("acp_bridge_runs"); op.drop_table("acp_identities"); op.drop_table("acp_registry_snapshots")
    op.drop_table("genome_certifications"); op.drop_table("genome_sources")
    op.drop_index("ix_genomes_project_created", table_name="genomes"); op.drop_table("genomes")
