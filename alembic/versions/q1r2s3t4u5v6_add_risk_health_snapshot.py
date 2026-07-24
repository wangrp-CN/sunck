"""新增风险/健康分时序快照表 risk_health_snapshot（智能核心 v2）

把「项目风险分 / 设备健康分」按时间落库为序列，供对比大屏趋势线、阈值预警与
跨周期对比使用。聚合口径与 devices/health、dashboard/project-compare 端点一致。

Revision Id: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-07-24 14:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q1r2s3t4u5v6"
down_revision: Union[str, None] = "p0q1r2s3t4u5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_health_snapshot",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("risk_index", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(length=8), nullable=True),
        sa.Column("raw_score", sa.Integer(), nullable=True),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column("health_level", sa.String(length=8), nullable=True),
        sa.Column("online_state", sa.String(length=16), nullable=True),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rhs_scope_ref", "risk_health_snapshot", ["scope_type", "ref_id"], unique=False
    )
    op.create_index("ix_rhs_snapshot_at", "risk_health_snapshot", ["snapshot_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_rhs_snapshot_at", table_name="risk_health_snapshot")
    op.drop_index("ix_rhs_scope_ref", table_name="risk_health_snapshot")
    op.drop_table("risk_health_snapshot")
