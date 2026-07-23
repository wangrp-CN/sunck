"""add alarm composite indexes

告警时序/状态查询索引（基础设施审计 · 查询索引缺口补齐）：
- ix_alarm_alarm_time(alarm_time)：趋势/近期/分页的 range + order_by 核心列，
  原无索引，大表上走全表扫 + 排序。
- ix_alarm_handle_status_time(handle_status, alarm_time)：看板「待处理计数」与
  「按状态取近期」复合过滤。

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-07-23
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k5l6m7n8o9p0"
down_revision: str = "j4k5l6m7n8o9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index("ix_alarm_alarm_time", "alarm", ["alarm_time"])
    op.create_index("ix_alarm_handle_status_time", "alarm", ["handle_status", "alarm_time"])


def downgrade() -> None:
    op.drop_index("ix_alarm_handle_status_time", table_name="alarm")
    op.drop_index("ix_alarm_alarm_time", table_name="alarm")
