"""WorkPlan.plan_start/plan_end 改为带时区 timestamptz（#11 深化）

现有 naive 值视为北京时间墙钟，转 timestamptz 时按 Asia/Shanghai 解释，
避免部署到 UTC 机时整体漂移 8 小时。应用侧 engine 已设
session timezone=Asia/Shanghai，保证 naive 输入按北京解释、读取为 aware 北京。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a01b2c3d4e5f"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "work_plan",
        "plan_start",
        type_=sa.DateTime(timezone=True),
        postgresql_using="plan_start AT TIME ZONE 'Asia/Shanghai'",
        existing_nullable=True,
    )
    op.alter_column(
        "work_plan",
        "plan_end",
        type_=sa.DateTime(timezone=True),
        postgresql_using="plan_end AT TIME ZONE 'Asia/Shanghai'",
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "work_plan",
        "plan_start",
        type_=sa.DateTime(),
        postgresql_using="plan_start AT TIME ZONE 'Asia/Shanghai'",
        existing_nullable=True,
    )
    op.alter_column(
        "work_plan",
        "plan_end",
        type_=sa.DateTime(),
        postgresql_using="plan_end AT TIME ZONE 'Asia/Shanghai'",
        existing_nullable=True,
    )
