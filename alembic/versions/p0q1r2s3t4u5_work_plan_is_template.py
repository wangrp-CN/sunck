"""work_plan 新增 is_template 列（P3·⑩ 计划模板/克隆）

模板计划不参与执行与规则判定，仅作为克隆蓝本；列表默认过滤模板。

Revision Id: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-07-24 10:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p0q1r2s3t4u5"
down_revision: Union[str, None] = "o9p0q1r2s3t4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_plan",
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_work_plan_is_template", "work_plan", ["is_template"])


def downgrade() -> None:
    op.drop_index("ix_work_plan_is_template", table_name="work_plan")
    op.drop_column("work_plan", "is_template")
