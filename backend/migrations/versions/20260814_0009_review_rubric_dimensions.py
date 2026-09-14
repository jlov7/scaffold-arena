"""store immutable per-dimension review adjudications

Revision ID: 20260814_0009
Revises: 20260814_0008
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0009"
down_revision = "20260814_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "annotation_adjudication_dimensions",
        sa.Column("adjudication_id", sa.String(length=64), nullable=False),
        sa.Column("metric_id", sa.String(length=128), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["adjudication_id"],
            ["annotation_adjudications.id"],
            name="fk_adjudication_dimensions_adjudication",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("adjudication_id", "metric_id"),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1",
            name=op.f("ck_annotation_adjudication_dimensions_score_range"),
        ),
    )


def downgrade() -> None:
    op.drop_table("annotation_adjudication_dimensions")
