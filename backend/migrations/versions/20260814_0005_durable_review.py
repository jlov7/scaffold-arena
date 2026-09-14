"""add durable read-only evaluation and blind review records

Revision ID: 20260814_0005
Revises: 20260814_0004
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0005"
down_revision = "20260814_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evaluations", recreate="always") as batch:
        batch.add_column(sa.Column("project_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("batch_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("evaluator_version", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("evaluator_digest", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("input_artifact_digest", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("output_artifact_digest", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("trace_artifact_digest", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("grader_plan", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("result_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("cost_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("cost_usd", sa.Float(), nullable=True))
        batch.add_column(sa.Column("exclusion_state", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("adjudication_state", sa.String(length=32), nullable=True))
        batch.create_foreign_key("fk_evaluations_project_id_projects", "projects", ["project_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("annotations", recreate="always") as batch:
        batch.add_column(sa.Column("project_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("batch_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("item_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("annotator_pseudonym", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("assignment_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("score", sa.Float(), nullable=True))
        batch.create_foreign_key("fk_annotations_project_id_projects", "projects", ["project_id"], ["id"], ondelete="RESTRICT")
        batch.create_unique_constraint("annotations_assignment_hash", ["assignment_hash"])
    op.create_table(
        "annotation_batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("batch_hash", sa.String(length=64), nullable=False), sa.Column("protocol_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluator", sa.String(length=128), nullable=False), sa.Column("evaluator_version", sa.String(length=128), nullable=False),
        sa.Column("evaluator_digest", sa.String(length=64), nullable=False), sa.Column("grader_plan", sa.JSON(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "batch_hash", name="project_batch_hash"),
        sa.CheckConstraint("length(batch_hash) = 64 AND length(protocol_hash) = 64 AND length(evaluator_digest) = 64", name="batch_digests"),
    )
    op.create_table(
        "annotation_assignments",
        sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False), sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("annotator_pseudonym", sa.String(length=128), nullable=False), sa.Column("blind_payload_digest", sa.String(length=64), nullable=False),
        sa.Column("assignment_hash", sa.String(length=64), nullable=False), sa.Column("identity_state", sa.String(length=32), nullable=False, server_default="identity_unverified"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["batch_id"], ["annotation_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["blind_payload_digest"], ["artifacts.digest"], ondelete="RESTRICT"),
        sa.UniqueConstraint("batch_id", "item_id", "annotator_pseudonym", name="batch_item_pseudonym"),
        sa.UniqueConstraint("assignment_hash", name="assignment_hash"),
        sa.CheckConstraint("length(blind_payload_digest) = 64 AND length(assignment_hash) = 64", name="assignment_digests"),
    )
    op.create_table(
        "annotation_adjudications",
        sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False), sa.Column("adjudicator_pseudonym", sa.String(length=128), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False), sa.Column("decision", sa.String(length=128), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False), sa.Column("evidence_ref", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["batch_id"], ["annotation_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_ref"], ["artifacts.digest"], ondelete="RESTRICT"),
        sa.UniqueConstraint("batch_id", "item_id", name="batch_item_adjudication"),
        sa.CheckConstraint("final_score >= 0 AND final_score <= 1", name="adjudication_score"),
    )
    op.create_index("ix_evaluations_project_batch", "evaluations", ["project_id", "batch_id"])
    op.create_index("ix_annotations_project_batch", "annotations", ["project_id", "batch_id"])


def downgrade() -> None:
    op.drop_index("ix_annotations_project_batch", table_name="annotations")
    op.drop_index("ix_evaluations_project_batch", table_name="evaluations")
    op.drop_table("annotation_adjudications")
    op.drop_table("annotation_assignments")
    op.drop_table("annotation_batches")
    with op.batch_alter_table("annotations", recreate="always") as batch:
        batch.drop_constraint("fk_annotations_project_id_projects", type_="foreignkey")
        batch.drop_constraint("annotations_assignment_hash", type_="unique")
        for column in ("score", "assignment_hash", "annotator_pseudonym", "item_id", "batch_id", "project_id"):
            batch.drop_column(column)
    with op.batch_alter_table("evaluations", recreate="always") as batch:
        batch.drop_constraint("fk_evaluations_project_id_projects", type_="foreignkey")
        for column in ("adjudication_state", "exclusion_state", "cost_usd", "cost_status", "result_hash", "grader_plan", "trace_artifact_digest", "output_artifact_digest", "input_artifact_digest", "evaluator_digest", "evaluator_version", "batch_id", "project_id"):
            batch.drop_column(column)
