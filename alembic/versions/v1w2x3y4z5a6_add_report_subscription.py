"""定期订阅推送：report_subscription 表（模块①·报告与触达增强）

- report_subscription：用户级效能运营报告定期生成订阅（按订阅人数据范围生成，
  到点经通知中心触达；支持 daily/weekly/monthly 调度 + 运行记录）。

Revision Id: v1w2x3y4z5a6
Revises: u9v0w1x2y3z4
Create Date: 2026-07-28 13:50:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v1w2x3y4z5a6"
down_revision: Union[str, Sequence[str], None] = "u9v0w1x2y3z4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_subscription",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("fmt", sa.String(length=8), nullable=False, server_default="excel"),
        sa.Column("days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("frequency", sa.String(length=8), nullable=False, server_default="daily"),
        sa.Column("send_hour", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("send_weekday", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("channels", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=8), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_subscription_user_id", "report_subscription", ["user_id"])
    op.create_index("ix_report_subscription_project_id", "report_subscription", ["project_id"])
    op.create_index("ix_report_subscription_enabled", "report_subscription", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_report_subscription_enabled", table_name="report_subscription")
    op.drop_index("ix_report_subscription_project_id", table_name="report_subscription")
    op.drop_index("ix_report_subscription_user_id", table_name="report_subscription")
    op.drop_table("report_subscription")
