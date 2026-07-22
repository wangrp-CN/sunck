"""为 work_plan 增加 actual_start / actual_end（甘特实际进度联动）

启动作业计划时回填 actual_start，完成时回填 actual_end，供前端甘特图展示
「计划窗 vs 实际窗」双色进度。

Revision ID: g1h2i3j4k5l6
Revises: a01b2c3d4e5f
Create Date: 2026-07-22 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "a01b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_plan",
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_plan",
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("work_plan", "actual_end")
    op.drop_column("work_plan", "actual_start")
