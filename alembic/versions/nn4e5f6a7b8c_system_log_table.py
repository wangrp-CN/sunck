"""系统日志表：记录应用运行时的异常、警告与关键事件。

表 sys_log 字段：
- id: 主键自增
- level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- module: 来源模块标识
- message: 日志摘要
- detail: 详细上下文 Text
- traceback: 异常堆栈 Text (仅 ERROR/CRITICAL)
- source: 触发来源
- user_id: 关联用户ID (FK→user.id, SET NULL)
- created_at / updated_at: 时间戳

Revision ID: nn4e5f6a7b8c
Revises: mm3d4e5f6a7b
Create Date: 2026-08-05
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "nn4e5f6a7b8c"
down_revision: str | None = "mm3d4e5f6a7b"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "system_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "level",
            sa.String(length=16),
            nullable=False,
            server_default="INFO",
            comment="日志级别",
        ),
        sa.Column("module", sa.String(length=48), nullable=False, comment="来源模块"),
        sa.Column("message", sa.String(length=512), nullable=False, comment="日志摘要"),
        sa.Column("detail", sa.Text(), nullable=True, comment="详细上下文"),
        sa.Column("traceback", sa.Text(), nullable=True, comment="异常堆栈"),
        sa.Column("source", sa.String(length=128), nullable=True, comment="触发来源"),
        sa.Column("user_id", sa.Integer(), nullable=True, comment="关联用户ID"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
    )
    # 为常用过滤字段创建索引
    op.create_index("ix_system_log_level", "system_log", ["level"])
    op.create_index("ix_system_log_module", "system_log", ["module"])
    op.create_index("ix_system_log_user_id", "system_log", ["user_id"])
    op.create_index("ix_system_log_created_at", "system_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_system_log_created_at", table_name="system_log")
    op.drop_index("ix_system_log_user_id", table_name="system_log")
    op.drop_index("ix_system_log_module", table_name="system_log")
    op.drop_index("ix_system_log_level", table_name="system_log")
    op.drop_table("system_log")
