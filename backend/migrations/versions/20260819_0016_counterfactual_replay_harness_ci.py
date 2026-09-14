"""add provider-free counterfactual replay and Harness CI custody indexes

Revision ID: 20260819_0016
Revises: 20260818_0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260819_0016"
down_revision = "20260818_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterfactual_replays",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("binding_digest", sa.String(64), nullable=False),
        sa.Column("report_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("evidence_maturity", sa.String(32), nullable=False),
        sa.Column("claim_ceiling", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "request_digest", name="uq_counterfactual_replay_project_request"),
        sa.UniqueConstraint("project_id", "report_artifact_digest", name="uq_counterfactual_replay_project_report"),
        sa.CheckConstraint("length(request_digest) = 64", name="counterfactual_request_digest"),
        sa.CheckConstraint("length(binding_digest) = 64", name="counterfactual_binding_digest"),
        sa.CheckConstraint("length(report_artifact_digest) = 64", name="counterfactual_report_digest"),
        sa.CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="counterfactual_verdict"),
        sa.CheckConstraint("evidence_maturity IN ('temporal_correlation', 'diagnostic_divergence', 'paired_replay', 'replicated_intervention', 'confirmatory_eligibility')", name="counterfactual_maturity"),
    )
    op.create_index("ix_counterfactual_replays_project_created", "counterfactual_replays", ["project_id", "created_at"])
    op.create_table(
        "harness_ci_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("replay_report_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("report_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("claim_ceiling", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "request_digest", name="uq_harness_ci_project_request"),
        sa.UniqueConstraint("project_id", "report_artifact_digest", name="uq_harness_ci_project_report"),
        sa.CheckConstraint("length(request_digest) = 64", name="harness_ci_request_digest"),
        sa.CheckConstraint("length(replay_report_digest) = 64", name="harness_ci_replay_digest"),
        sa.CheckConstraint("length(report_artifact_digest) = 64", name="harness_ci_report_digest"),
        sa.CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="harness_ci_verdict"),
    )
    op.create_index("ix_harness_ci_reports_project_created", "harness_ci_reports", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_harness_ci_reports_project_created", table_name="harness_ci_reports")
    op.drop_table("harness_ci_reports")
    op.drop_index("ix_counterfactual_replays_project_created", table_name="counterfactual_replays")
    op.drop_table("counterfactual_replays")
