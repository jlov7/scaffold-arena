"""add execution-scoped attempt event cursors

Revision ID: 20260814_0003
Revises: 20260814_0002
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0003"
down_revision = "20260814_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attempt_events", sa.Column("execution_id", sa.String(length=64), nullable=True))
    op.add_column("attempt_events", sa.Column("execution_sequence", sa.Integer(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT attempt_events.id, episodes.execution_id
        FROM attempt_events
        JOIN attempts ON attempts.id = attempt_events.attempt_id
        JOIN episodes ON episodes.id = attempts.episode_id
        ORDER BY episodes.execution_id, attempt_events.created_at, attempt_events.id
    """)).mappings()
    current_execution_id = None
    execution_sequence = 0
    for row in rows:
        execution_id = row["execution_id"]
        if execution_id != current_execution_id:
            current_execution_id = execution_id
            execution_sequence = 0
        execution_sequence += 1
        bind.execute(
            sa.text("UPDATE attempt_events SET execution_id = :execution_id, execution_sequence = :execution_sequence WHERE id = :id"),
            {"id": row["id"], "execution_id": execution_id, "execution_sequence": execution_sequence},
        )

    with op.batch_alter_table("attempt_events", recreate="always") as batch:
        batch.alter_column("execution_id", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("execution_sequence", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_attempt_events_execution_id_executions", "executions", ["execution_id"], ["id"], ondelete="CASCADE")
        batch.create_unique_constraint("execution_event_sequence", ["execution_id", "execution_sequence"])
        batch.create_check_constraint("positive_execution_sequence", "execution_sequence > 0")

    op.create_index("ix_attempt_events_execution_sequence", "attempt_events", ["execution_id", "execution_sequence"])
    op.create_table(
        "execution_event_cursors",
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("last_sequence >= 0", name="nonnegative_last_sequence"),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    cursor_rows = bind.execute(sa.text("""
        SELECT execution_id, MAX(execution_sequence) AS last_sequence
        FROM attempt_events
        GROUP BY execution_id
    """)).mappings()
    for row in cursor_rows:
        bind.execute(
            sa.text("INSERT INTO execution_event_cursors (execution_id, last_sequence) VALUES (:execution_id, :last_sequence)"),
            {"execution_id": row["execution_id"], "last_sequence": row["last_sequence"]},
        )


def downgrade() -> None:
    op.drop_table("execution_event_cursors")
    op.drop_index("ix_attempt_events_execution_sequence", table_name="attempt_events")
    with op.batch_alter_table("attempt_events", recreate="always") as batch:
        batch.drop_constraint("positive_execution_sequence", type_="check")
        batch.drop_constraint("execution_event_sequence", type_="unique")
        batch.drop_constraint("fk_attempt_events_execution_id_executions", type_="foreignkey")
        batch.drop_column("execution_sequence")
        batch.drop_column("execution_id")
