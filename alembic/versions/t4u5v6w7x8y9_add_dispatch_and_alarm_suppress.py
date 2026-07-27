"""新增根因派单表 dispatch_order + 告警抑制字段（#80 / 告警风暴抑制 v2）

- dispatch_order：根因派单闭环工单（来源 correlation/alarm/manual，状态机 待派→处理中→已闭环）。
- alarm.suppressed_count / last_suppressed_at：被风暴抑制合并掉的重复告警计数与最近抑制时间。

Revision Id: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-07-27 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "t4u5v6w7x8y9"
down_revision: Union[str, Sequence[str], None] = "s3t4u5v6w7x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dispatch_order",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("root_cause_hint", sa.Text(), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("assignee_name", sa.String(length=64), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("last_action_note", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignee_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dispatch_project_status", "dispatch_order", ["project_id", "status"], unique=False
    )
    op.create_index(
        "ix_dispatch_source", "dispatch_order", ["source_type", "source_id"], unique=False
    )
    op.create_index("ix_dispatch_created_at", "dispatch_order", ["created_at"], unique=False)
    op.create_index("ix_dispatch_is_deleted", "dispatch_order", ["is_deleted"], unique=False)

    op.add_column(
        "alarm", sa.Column("suppressed_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "alarm",
        sa.Column("last_suppressed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alarm", "last_suppressed_at")
    op.drop_column("alarm", "suppressed_count")
    op.drop_index("ix_dispatch_is_deleted", table_name="dispatch_order")
    op.drop_index("ix_dispatch_source", table_name="dispatch_order")
    op.drop_index("ix_dispatch_project_status", table_name="dispatch_order")
    op.drop_index("ix_dispatch_created_at", table_name="dispatch_order")
    op.drop_table("dispatch_order")
