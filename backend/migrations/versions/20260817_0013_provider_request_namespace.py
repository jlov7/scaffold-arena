"""namespace provider request identities by pinned endpoint

Revision ID: 20260817_0013
Revises: 20260816_0012
Create Date: 2026-08-17
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "20260817_0013"
down_revision = "20260816_0012"
branch_labels = None
depends_on = None


def _legacy_namespace(provider: str) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "provider_request_namespace": "legacy-provider-only-v1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("invocation_records") as batch:
        batch.add_column(
            sa.Column("provider_request_namespace", sa.String(64), nullable=True)
        )

    connection = op.get_bind()
    records = sa.table(
        "invocation_records",
        sa.column("id", sa.String(128)),
        sa.column("provider", sa.String(128)),
        sa.column("provider_request_namespace", sa.String(64)),
    )
    rows = connection.execute(
        sa.select(records.c.id, records.c.provider)
    ).mappings().all()
    for row in rows:
        connection.execute(
            records.update()
            .where(records.c.id == row["id"])
            .values(
                provider_request_namespace=_legacy_namespace(str(row["provider"]))
            )
        )

    op.drop_index("ix_invocation_provider_request", table_name="invocation_records")
    with op.batch_alter_table("invocation_records") as batch:
        batch.alter_column(
            "provider_request_namespace",
            existing_type=sa.String(64),
            nullable=False,
        )
        batch.create_check_constraint(
            "invocation_request_namespace_digest",
            "length(provider_request_namespace) = 64",
        )
    op.create_index(
        "ix_invocation_provider_request",
        "invocation_records",
        ["provider_request_namespace", "provider_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_invocation_provider_request", table_name="invocation_records")
    with op.batch_alter_table("invocation_records") as batch:
        batch.drop_constraint(
            "invocation_request_namespace_digest",
            type_="check",
        )
        batch.drop_column("provider_request_namespace")
    op.create_index(
        "ix_invocation_provider_request",
        "invocation_records",
        ["provider", "provider_request_id"],
    )
