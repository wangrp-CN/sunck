"""新增隐患治理闭环表 hazard

人工/巡检发现的安全隐患，经整改→复核→销号形成治理闭环，与系统自动产生的「告警」互补。
数据范围经 project 关联(VIA_PROJECT)。

Revision ID: h2i3j4k5l6
Revises: g1h2i3j4k5l6
Create Date: 2026-07-22 16:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h2i3j4k5l6"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hazard",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="一般"),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location_desc", sa.String(length=255), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("discovered_by_name", sa.String(length=64), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="人工"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="待整改"),
        sa.Column(
            "assignee_id",
            sa.Integer(),
            sa.ForeignKey("person.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rectify_note", sa.Text(), nullable=True),
        sa.Column("rectify_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verify_by_name", sa.String(length=64), nullable=True),
        sa.Column("verify_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verify_note", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_hazard_project_id", "project_id"),
        sa.Index("ix_hazard_status", "status"),
        sa.Index("ix_hazard_level", "level"),
        sa.Index("ix_hazard_assignee_id", "assignee_id"),
        sa.Index("ix_hazard_due_at", "due_at"),
        sa.Index("ix_hazard_is_deleted", "is_deleted"),
    )


def downgrade() -> None:
    op.drop_table("hazard")
