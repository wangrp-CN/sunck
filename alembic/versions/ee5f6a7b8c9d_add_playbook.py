"""add playbook (M5 处置预案/知识库联动)

Revision ID: ee5f6a7b8c9d
Revises: dd4e5f6a7b8c
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee5f6a7b8c9d"
down_revision: str | None = "dd4e5f6a7b8c"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "playbook",
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
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("alarm_type", sa.String(length=32), nullable=True),
        sa.Column("alarm_level", sa.String(length=16), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("trigger_condition", sa.Text(), nullable=True),
        sa.Column("references", sa.Text(), nullable=True),
        sa.Column("tags", sa.String(length=255), nullable=True),
        sa.Column("owner_role", sa.String(length=64), nullable=True),
        sa.Column("est_minutes", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_playbook_match",
        "playbook",
        ["project_id", "alarm_type", "alarm_level", "enabled"],
        unique=False,
    )
    op.create_index("ix_playbook_project", "playbook", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_playbook_project", table_name="playbook")
    op.drop_index("ix_playbook_match", table_name="playbook")
    op.drop_table("playbook")
