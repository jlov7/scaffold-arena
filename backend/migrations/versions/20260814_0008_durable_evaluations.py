"""make evaluations one immutable record per attempt

Revision ID: 20260814_0008
Revises: 20260814_0007
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0008"
down_revision = "20260814_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evaluations") as batch:
        batch.create_unique_constraint("evaluation_attempt", ["attempt_id"])
        batch.add_column(sa.Column("result_artifact_digest", sa.String(length=64), nullable=True))
    with op.batch_alter_table("jobs") as batch:
        batch.create_unique_constraint("attempt_kind", ["attempt_id", "kind"])


def downgrade() -> None:
    with op.batch_alter_table("evaluations") as batch:
        batch.drop_column("result_artifact_digest")
        batch.drop_constraint("evaluation_attempt", type_="unique")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("attempt_kind", type_="unique")
