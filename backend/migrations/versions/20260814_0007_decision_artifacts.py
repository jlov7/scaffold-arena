"""add immutable decision brief and claim ledger artifacts

Revision ID: 20260814_0007
Revises: 20260814_0006
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0007"
down_revision = "20260814_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_briefs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("analysis_report_id", sa.String(length=64), nullable=False),
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("report_digest", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("brief_hash", sa.String(length=64), nullable=False),
        sa.Column("ledger_hash", sa.String(length=64), nullable=False),
        sa.Column("brief_artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("ledger_artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("claim_ceiling", sa.String(length=64), nullable=False),
        sa.Column("claim_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_report_id"], ["analysis_reports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["brief_artifact_digest"], ["artifacts.digest"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ledger_artifact_digest"], ["artifacts.digest"], ondelete="RESTRICT"),
        sa.UniqueConstraint("analysis_report_id", name="decision_briefs_analysis_report"),
        sa.CheckConstraint("length(report_digest) = 64 AND length(request_digest) = 64 AND length(brief_hash) = 64 AND length(ledger_hash) = 64 AND length(brief_artifact_digest) = 64 AND length(ledger_artifact_digest) = 64", name="decision_brief_digests"),
        sa.CheckConstraint("verdict IN ('PASS', 'HOLD', 'REJECT')", name="decision_brief_verdict"),
    )
    op.create_index("ix_decision_briefs_project_created", "decision_briefs", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_decision_briefs_project_created", table_name="decision_briefs")
    op.drop_table("decision_briefs")
