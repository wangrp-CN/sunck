"""新增风险预警去重状态表 risk_alert_state（智能核心 v2 · 阈值预警）

记录每个项目「最近一次下发站内信预警所依据的快照时刻」，用于避免定时快照任务重跑
或手动重复触发时对同一越阈快照重复轰炸（降噪）。project_id 以 unique 约束保证每
项目一行。

Revision Id: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-07-24 15:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r2s3t4u5v6w7"
down_revision: Union[str, Sequence[str], None] = "q1r2s3t4u5v6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_alert_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_risk_index", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_risk_alert_state"),
        sa.UniqueConstraint("project_id", name="uq_risk_alert_state_project"),
    )
    op.create_index(
        "ix_risk_alert_state_project_id", "risk_alert_state", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_risk_alert_state_project_id", table_name="risk_alert_state")
    op.drop_table("risk_alert_state")
