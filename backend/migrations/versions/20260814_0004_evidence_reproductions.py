"""add durable evidence receipt and reproduction bindings

Revision ID: 20260814_0004
Revises: 20260814_0003
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0004"
down_revision = "20260814_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evidence_receipts", recreate="always") as batch:
        batch.add_column(sa.Column("project_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("manifest_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("receipt_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("manifest_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("artifact_hashes", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("claim_ceiling", sa.Text(), nullable=True))
        batch.add_column(sa.Column("integrity_not_truth", sa.Boolean(), nullable=True))
        batch.create_foreign_key("fk_evidence_receipts_project_id_projects", "projects", ["project_id"], ["id"], ondelete="RESTRICT")
        batch.create_check_constraint("manifest_hash_digest", "manifest_hash IS NULL OR length(manifest_hash) = 64")
        batch.create_check_constraint("receipt_hash_digest", "receipt_hash IS NULL OR length(receipt_hash) = 64")
        batch.create_unique_constraint("evidence_receipts_receipt_hash", ["receipt_hash"])
    op.create_index("ix_evidence_receipts_project_created", "evidence_receipts", ["project_id", "created_at"])
    op.create_table(
        "evidence_receipt_artifacts",
        sa.Column("receipt_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["evidence_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_digest"], ["artifacts.digest"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("receipt_id", "artifact_digest"),
    )
    with op.batch_alter_table("reproductions", recreate="always") as batch:
        batch.alter_column("source_execution_id", existing_type=sa.String(length=64), nullable=True)
        batch.add_column(sa.Column("project_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("original_evidence_receipt_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("reproduced_evidence_receipt_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("reproduction_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("receipt_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("external_attestation", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("claim_ceiling", sa.Text(), nullable=True))
        batch.add_column(sa.Column("integrity_not_truth", sa.Boolean(), nullable=True))
        batch.create_foreign_key("fk_reproductions_project_id_projects", "projects", ["project_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_reproductions_original_receipt", "evidence_receipts", ["original_evidence_receipt_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_reproductions_reproduced_receipt", "evidence_receipts", ["reproduced_evidence_receipt_id"], ["id"], ondelete="RESTRICT")
        batch.create_check_constraint("reproduction_hash_digest", "reproduction_hash IS NULL OR length(reproduction_hash) = 64")
        batch.create_unique_constraint("reproductions_reproduction_hash", ["reproduction_hash"])
    op.create_index("ix_reproductions_project_created", "reproductions", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_reproductions_project_created", table_name="reproductions")
    with op.batch_alter_table("reproductions", recreate="always") as batch:
        batch.drop_constraint("reproductions_reproduction_hash", type_="unique")
        batch.drop_constraint("reproduction_hash_digest", type_="check")
        batch.drop_constraint("fk_reproductions_reproduced_receipt", type_="foreignkey")
        batch.drop_constraint("fk_reproductions_original_receipt", type_="foreignkey")
        batch.drop_constraint("fk_reproductions_project_id_projects", type_="foreignkey")
        batch.drop_column("integrity_not_truth")
        batch.drop_column("claim_ceiling")
        batch.drop_column("external_attestation")
        batch.drop_column("receipt_json")
        batch.drop_column("reproduction_hash")
        batch.drop_column("reproduced_evidence_receipt_id")
        batch.drop_column("original_evidence_receipt_id")
        batch.drop_column("project_id")
        batch.alter_column("source_execution_id", existing_type=sa.String(length=64), nullable=False)
    op.drop_table("evidence_receipt_artifacts")
    op.drop_index("ix_evidence_receipts_project_created", table_name="evidence_receipts")
    with op.batch_alter_table("evidence_receipts", recreate="always") as batch:
        batch.drop_constraint("evidence_receipts_receipt_hash", type_="unique")
        batch.drop_constraint("receipt_hash_digest", type_="check")
        batch.drop_constraint("manifest_hash_digest", type_="check")
        batch.drop_constraint("fk_evidence_receipts_project_id_projects", type_="foreignkey")
        batch.drop_column("integrity_not_truth")
        batch.drop_column("claim_ceiling")
        batch.drop_column("artifact_hashes")
        batch.drop_column("manifest_json")
        batch.drop_column("receipt_hash")
        batch.drop_column("manifest_hash")
        batch.drop_column("project_id")
