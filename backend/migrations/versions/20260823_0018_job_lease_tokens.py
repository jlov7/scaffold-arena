"""Fence each durable job claim with an opaque lease token.

Revision ID: 20260823_0018
Revises: 20260819_0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260823_0018"
down_revision = "20260819_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("lease_token", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("lease_token")
