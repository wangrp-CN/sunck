"""设备指令下发闭环：device_command 表（状态追踪 + 回执 + 重试）

- device_command：每次平台→设备下行指令的全生命周期记录（pending/sent/acked/failed），
  承载 cmd_id 回执关联、重试计数与告警溯源(alarm_id)。

Revision Id: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-07-28 16:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w2x3y4z5a6b7"
down_revision: Union[str, Sequence[str], None] = "v1w2x3y4z5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_command",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("device_no", sa.String(length=64), nullable=False),
        sa.Column("device_type", sa.String(length=32), nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "alarm_id",
            sa.Integer(),
            sa.ForeignKey("alarm.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_command_project_id", "device_command", ["project_id"])
    op.create_index("ix_device_command_device_no", "device_command", ["device_no"])
    op.create_index("ix_device_command_status", "device_command", ["status"])
    op.create_index("ix_device_command_alarm_id", "device_command", ["alarm_id"])


def downgrade() -> None:
    op.drop_index("ix_device_command_alarm_id", table_name="device_command")
    op.drop_index("ix_device_command_status", table_name="device_command")
    op.drop_index("ix_device_command_device_no", table_name="device_command")
    op.drop_index("ix_device_command_project_id", table_name="device_command")
    op.drop_table("device_command")
