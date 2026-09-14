"""add immutable execution-bound analysis reports

Revision ID: 20260814_0006
Revises: 20260814_0005
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0006"
down_revision = "20260814_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("study_pack_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_digest", sa.String(length=64), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("report_digest", sa.String(length=64), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_digest"], ["artifacts.digest"], ondelete="RESTRICT"),
        sa.UniqueConstraint("execution_id", name="analysis_reports_execution"),
        sa.CheckConstraint("length(spec_hash) = 64 AND length(study_pack_hash) = 64 AND length(configuration_digest) = 64 AND length(input_digest) = 64 AND length(report_digest) = 64 AND length(artifact_digest) = 64", name="analysis_report_digests"),
    )
    op.create_index("ix_analysis_reports_project_experiment", "analysis_reports", ["project_id", "experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_reports_project_experiment", table_name="analysis_reports")
    op.drop_table("analysis_reports")
