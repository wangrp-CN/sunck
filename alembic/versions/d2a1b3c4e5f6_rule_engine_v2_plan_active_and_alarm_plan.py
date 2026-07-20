"""规则引擎 v2：作业计划时间窗 + 告警归属计划。

- work_plan 增加 plan_start / plan_end（结构化时间窗，用于规则引擎时间范围门控）
- alarm 增加 work_plan_id（外键→work_plan，可空，索引），实现告警→业务溯源

Revision ID: d2a1b3c4e5f6
Revises: abb59fa24a09
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d2a1b3c4e5f6"
down_revision = "abb59fa24a09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) work_plan 时间窗
    op.add_column(
        "work_plan",
        sa.Column("plan_start", sa.DateTime(), nullable=True, comment="计划生效开始(空=不限制)"),
    )
    op.add_column(
        "work_plan",
        sa.Column("plan_end", sa.DateTime(), nullable=True, comment="计划生效结束(空=不限制)"),
    )

    # 2) alarm 归属计划
    op.add_column(
        "alarm",
        sa.Column("work_plan_id", sa.Integer(), nullable=True, comment="归属作业计划"),
    )
    op.create_index("ix_alarm_work_plan_id", "alarm", ["work_plan_id"])
    op.create_foreign_key(
        "fk_alarm_work_plan_id",
        "alarm",
        "work_plan",
        ["work_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_alarm_work_plan_id", "alarm", type_="foreignkey")
    op.drop_index("ix_alarm_work_plan_id", table_name="alarm")
    op.drop_column("alarm", "work_plan_id")
    op.drop_column("work_plan", "plan_end")
    op.drop_column("work_plan", "plan_start")
