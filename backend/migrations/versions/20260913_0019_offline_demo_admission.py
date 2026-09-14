"""Persist bounded bundled offline-demo admission state.

Revision ID: 20260913_0019
Revises: 20260823_0018
"""

from __future__ import annotations

from alembic import op

from persistence_v1.schema import offline_demo_admissions, offline_demo_runtime_locks


revision = "20260913_0019"
down_revision = "20260823_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    offline_demo_admissions.create(bind=bind, checkfirst=True)
    offline_demo_runtime_locks.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    offline_demo_runtime_locks.drop(bind=bind, checkfirst=True)
    offline_demo_admissions.drop(bind=bind, checkfirst=True)
