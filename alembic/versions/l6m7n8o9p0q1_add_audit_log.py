"""新增操作审计表 audit_log

记录关键写操作（谁/何时/模块/动作/结果/来源IP），支撑监管平台操作审计需求。
落库时快照操作人 user_id/username/dept_id，便于按部门数据范围检索。

Revision Id: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-07-23 15:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l6m7n8o9p0q1"
down_revision: Union[str, None] = "k5l6m7n8o9p0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column(
            "dept_id",
            sa.Integer(),
            sa.ForeignKey("department.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("module", sa.String(length=48), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("query", sa.String(length=512), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_audit_log_user_id", "user_id"),
        sa.Index("ix_audit_log_dept_id", "dept_id"),
        sa.Index("ix_audit_log_action", "action"),
        sa.Index("ix_audit_log_module", "module"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
