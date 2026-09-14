"""persistence v1 baseline

Revision ID: 20260814_0001
Revises:
Create Date: 2026-08-14
"""

from alembic import op

from migrations.baseline_20260814 import metadata

revision = "20260814_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind())
