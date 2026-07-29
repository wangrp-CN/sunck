"""add duty_roster (🅱 告警治理与值班体系 - 值班排班)

Revision ID: aa1b2c3d4e5f
Revises: z9a0b1c2d3e4
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa1b2c3d4e5f"
down_revision: str | None = "z9a0b1c2d3e4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "duty_roster",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("shift", sa.String(length=16), nullable=False, server_default="白班"),
        sa.Column("duty_role", sa.String(length=32), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_duty_project", "duty_roster", ["project_id"])
    op.create_index("ix_duty_user", "duty_roster", ["user_id"])
    op.create_index("ix_duty_window", "duty_roster", ["project_id", "start_time", "end_time"])


def downgrade() -> None:
    op.drop_index("ix_duty_window", table_name="duty_roster")
    op.drop_index("ix_duty_user", table_name="duty_roster")
    op.drop_index("ix_duty_project", table_name="duty_roster")
    op.drop_table("duty_roster")
