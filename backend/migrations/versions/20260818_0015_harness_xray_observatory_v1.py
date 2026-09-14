"""add inert Harness X-Ray and persisted-event observatory indexes

Revision ID: 20260818_0015
Revises: 20260818_0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0015"
down_revision = "20260818_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "xray_snapshots",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_uri", sa.Text()), sa.Column("source_revision", sa.Text()),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_ceiling", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "source_digest", name="uq_xray_snapshots_project_digest"),
        sa.CheckConstraint("length(source_digest) = 64", name="xray_snapshot_digest"),
    )
    op.create_index("ix_xray_snapshots_project_created", "xray_snapshots", ["project_id", "created_at"])
    op.create_table(
        "xray_findings",
        sa.Column("snapshot_id", sa.String(128), sa.ForeignKey("xray_snapshots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("finding_id", sa.String(128), primary_key=True),
        sa.Column("evidence_state", sa.String(16), nullable=False),
        sa.Column("statement_digest", sa.String(64), nullable=False),
        sa.CheckConstraint("evidence_state IN ('declared', 'observed', 'inferred', 'verified', 'unsupported', 'unknown')", name="xray_finding_state"),
        sa.CheckConstraint("length(statement_digest) = 64", name="xray_finding_digest"),
    )
    op.create_table(
        "observatory_reports",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ledger_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("fidelity_level", sa.String(32), nullable=False),
        sa.Column("claim_ceiling", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "attempt_id", "ledger_digest", name="uq_observatory_report_snapshot"),
        sa.CheckConstraint("length(ledger_digest) = 64", name="observatory_ledger_digest"),
        sa.CheckConstraint("fidelity_level IN ('unknown', 'declared', 'assigned', 'available', 'triggered', 'applied', 'activated', 'observed', 'downstream_pathway_detected')", name="observatory_fidelity_level"),
    )
    op.create_index("ix_observatory_reports_project_attempt", "observatory_reports", ["project_id", "attempt_id"])
    op.create_table(
        "xray_analyses",
        sa.Column("analysis_digest", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("report_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("claim_ceiling", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "source_digest", "source_kind", name="uq_xray_analysis_source"),
        sa.CheckConstraint("length(analysis_digest) = 64", name="xray_analysis_digest"),
        sa.CheckConstraint("source_kind IN ('auto', 'repository', 'acp', 'cli', 'sdk', 'otel_bundle', 'recorded_run')", name="xray_analysis_source_kind"),
    )
    op.create_index("ix_xray_analyses_project_created", "xray_analyses", ["project_id", "created_at"])
    op.create_table(
        "observatory_analyses",
        sa.Column("analysis_digest", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("report_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("claim_ceiling", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(analysis_digest) = 64", name="observatory_analysis_digest"),
    )
    op.create_index("ix_observatory_analyses_project_created", "observatory_analyses", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_observatory_analyses_project_created", table_name="observatory_analyses")
    op.drop_table("observatory_analyses")
    op.drop_index("ix_xray_analyses_project_created", table_name="xray_analyses")
    op.drop_table("xray_analyses")
    op.drop_index("ix_observatory_reports_project_attempt", table_name="observatory_reports")
    op.drop_table("observatory_reports")
    op.drop_table("xray_findings")
    op.drop_index("ix_xray_snapshots_project_created", table_name="xray_snapshots")
    op.drop_table("xray_snapshots")
