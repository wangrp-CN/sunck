"""告警 ↔ 隐患 双向关联（监测→治理闭环）

- alarm.hazard_id：告警一键转隐患后回填，告警侧可跳转到关联隐患。
- hazard.source_alarm_id：隐患溯源到来源告警。

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6
Create Date: 2026-07-23 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, None] = "h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alarm",
        sa.Column("hazard_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_alarm_hazard", "alarm", "hazard", ["hazard_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_alarm_hazard_id", "alarm", ["hazard_id"])

    op.add_column(
        "hazard",
        sa.Column("source_alarm_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_hazard_source_alarm",
        "hazard",
        "alarm",
        ["source_alarm_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_hazard_source_alarm_id", "hazard", ["source_alarm_id"])


def downgrade() -> None:
    op.drop_index("ix_hazard_source_alarm_id", table_name="hazard")
    op.drop_constraint("fk_hazard_source_alarm", "hazard", type_="foreignkey")
    op.drop_column("hazard", "source_alarm_id")

    op.drop_index("ix_alarm_hazard_id", table_name="alarm")
    op.drop_constraint("fk_alarm_hazard", "alarm", type_="foreignkey")
    op.drop_column("alarm", "hazard_id")
