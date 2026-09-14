"""add provider-free Arena Forge, planner, and process-safety custody indexes

Revision ID: 20260819_0017
Revises: 20260819_0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260819_0017"
down_revision = "20260819_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forge_proposals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("proposal_digest", sa.String(64), nullable=False),
        sa.Column("proposal_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("proposer_identity", sa.String(128), nullable=False),
        sa.Column("base_genome_digest", sa.String(64), nullable=False),
        sa.Column("candidate_genome_digest", sa.String(64), nullable=False),
        sa.Column("mechanism_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("claim_scope", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "proposal_digest", name="uq_forge_proposal_project_digest"),
        sa.CheckConstraint("length(proposal_digest) = 64 AND length(proposal_artifact_digest) = 64", name="forge_proposal_digests"),
        sa.CheckConstraint("length(base_genome_digest) = 64 AND length(candidate_genome_digest) = 64", name="forge_proposal_genome_digests"),
        sa.CheckConstraint("state IN ('PENDING_APPROVAL', 'APPROVED', 'ADMITTED', 'REJECTED', 'QUARANTINED', 'INCONCLUSIVE')", name="forge_proposal_state"),
        sa.CheckConstraint("claim_scope IN ('fixture_contract', 'recorded_observation', 'product_control')", name="forge_proposal_claim_scope"),
    )
    op.create_index("ix_forge_proposals_project_created", "forge_proposals", ["project_id", "created_at"])
    op.create_table(
        "forge_approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("proposal_digest", sa.String(64), nullable=False),
        sa.Column("approval_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("approver_identity", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "proposal_digest", name="uq_forge_approval_project_proposal"),
        sa.UniqueConstraint("project_id", "approval_artifact_digest", name="uq_forge_approval_project_artifact"),
        sa.CheckConstraint("length(proposal_digest) = 64 AND length(approval_artifact_digest) = 64", name="forge_approval_digests"),
        sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED')", name="forge_approval_decision"),
    )
    op.create_table(
        "process_safety_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("report_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "request_digest", name="uq_process_safety_project_request"),
        sa.UniqueConstraint("project_id", "report_artifact_digest", name="uq_process_safety_project_report"),
        sa.CheckConstraint("length(request_digest) = 64 AND length(report_artifact_digest) = 64 AND length(policy_digest) = 64", name="process_safety_digests"),
        sa.CheckConstraint("verdict IN ('PASS', 'HOLD', 'FAIL')", name="process_safety_verdict"),
    )
    op.create_index("ix_process_safety_reports_project_created", "process_safety_reports", ["project_id", "created_at"])
    op.create_table(
        "forge_evaluations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("proposal_digest", sa.String(64), nullable=False),
        sa.Column("evaluation_digest", sa.String(64), nullable=False),
        sa.Column("evaluation_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("receipt_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("evaluator_identity", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("process_safety_report_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "evaluation_digest", name="uq_forge_evaluation_project_digest"),
        sa.UniqueConstraint("project_id", "receipt_artifact_digest", name="uq_forge_evaluation_project_receipt"),
        sa.CheckConstraint("length(proposal_digest) = 64 AND length(evaluation_digest) = 64", name="forge_evaluation_digests"),
        sa.CheckConstraint("length(evaluation_artifact_digest) = 64 AND length(receipt_artifact_digest) = 64 AND length(process_safety_report_digest) = 64", name="forge_evaluation_artifact_digests"),
        sa.CheckConstraint("outcome IN ('ADMITTED', 'REJECTED', 'QUARANTINED', 'INCONCLUSIVE')", name="forge_evaluation_outcome"),
    )
    op.create_index("ix_forge_evaluations_project_created", "forge_evaluations", ["project_id", "created_at"])
    op.create_table(
        "forge_planner_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("report_artifact_digest", sa.String(64), sa.ForeignKey("artifacts.digest", ondelete="RESTRICT"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "request_digest", name="uq_forge_planner_project_request"),
        sa.UniqueConstraint("project_id", "report_artifact_digest", name="uq_forge_planner_project_report"),
        sa.CheckConstraint("length(request_digest) = 64 AND length(report_artifact_digest) = 64", name="forge_planner_digests"),
        sa.CheckConstraint("mode IN ('exploratory', 'confirmatory')", name="forge_planner_mode"),
        sa.CheckConstraint("verdict IN ('READY', 'HOLD')", name="forge_planner_verdict"),
    )
    op.create_index("ix_forge_planner_reports_project_created", "forge_planner_reports", ["project_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        op.execute("""
        CREATE TRIGGER forge_evaluations_no_update
        BEFORE UPDATE ON forge_evaluations
        BEGIN SELECT RAISE(ABORT, 'Evolution Receipts are immutable'); END
        """)
        op.execute("""
        CREATE TRIGGER forge_evaluations_no_delete
        BEFORE DELETE ON forge_evaluations
        BEGIN SELECT RAISE(ABORT, 'Evolution Receipts are immutable'); END
        """)
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION scaffold_arena_forge_evolution_receipt_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Evolution Receipts are immutable'; RETURN NULL; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("""
        CREATE TRIGGER forge_evaluations_no_mutation
        BEFORE UPDATE OR DELETE ON forge_evaluations
        FOR EACH ROW EXECUTE FUNCTION scaffold_arena_forge_evolution_receipt_immutable()
        """)


def downgrade() -> None:
    op.drop_index("ix_forge_planner_reports_project_created", table_name="forge_planner_reports")
    op.drop_table("forge_planner_reports")
    op.drop_index("ix_forge_evaluations_project_created", table_name="forge_evaluations")
    op.drop_table("forge_evaluations")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS scaffold_arena_forge_evolution_receipt_immutable()")
    op.drop_index("ix_process_safety_reports_project_created", table_name="process_safety_reports")
    op.drop_table("process_safety_reports")
    op.drop_table("forge_approvals")
    op.drop_index("ix_forge_proposals_project_created", table_name="forge_proposals")
    op.drop_table("forge_proposals")
