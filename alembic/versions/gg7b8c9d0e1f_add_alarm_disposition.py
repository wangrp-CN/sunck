"""add alarm_disposition (处置效果闭环)

Revision ID: gg7b8c9d0e1f
Revises: ff6a7b8c9d0e
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "gg7b8c9d0e1f"
down_revision: str | None = "ff6a7b8c9d0e"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "alarm_disposition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("alarm_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("playbook_id", sa.Integer(), nullable=True),
        sa.Column("knowledge_refs", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("action_taken", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["alarm_id"], ["alarm.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_disposition_alarm", "alarm_disposition", ["alarm_id"], unique=False)
    op.create_index("ix_disposition_project", "alarm_disposition", ["project_id"], unique=False)
    op.create_index("ix_disposition_outcome", "alarm_disposition", ["outcome"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_disposition_outcome", table_name="alarm_disposition")
    op.drop_index("ix_disposition_project", table_name="alarm_disposition")
    op.drop_index("ix_disposition_alarm", table_name="alarm_disposition")
    op.drop_table("alarm_disposition")
