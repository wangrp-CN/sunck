"""新增跨设备根因关联事件组表 correlated_event_group（智能核心 v2 · #77）

将一段时间内「同项目 + 同空间范围（围栏/地理网格/单机）+ 时间窗近邻」的告警聚合成
*事件组*，揭示跨设备共因。本表为派生滚动表：每次计算全量重算（删旧插新）。

Revision Id: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-07-24 16:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "s3t4u5v6w7x8"
down_revision: Union[str, Sequence[str], None] = "r2s3t4u5v6w7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "correlated_event_group",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("project_name", sa.String(length=128), nullable=True),
        sa.Column("spatial_type", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("fence_name", sa.String(length=128), nullable=True),
        sa.Column("grid_cell", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alarm_count", sa.Integer(), nullable=False),
        sa.Column("device_count", sa.Integer(), nullable=False),
        sa.Column("is_cross_device", sa.Boolean(), nullable=False),
        sa.Column("max_level", sa.String(length=16), nullable=True),
        sa.Column("device_nos", sa.Text(), nullable=True),
        sa.Column("levels", sa.Text(), nullable=True),
        sa.Column("alarm_types", sa.Text(), nullable=True),
        sa.Column("alarm_ids", sa.Text(), nullable=True),
        sa.Column("root_cause_hint", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_correlated_event_group"),
    )
    op.create_index("ix_ceg_project_id", "correlated_event_group", ["project_id"], unique=False)
    op.create_index(
        "ix_ceg_computed_at",
        "correlated_event_group",
        ["computed_at"],
        unique=False,
    )
    op.create_index(
        "ix_ceg_project_computed",
        "correlated_event_group",
        ["project_id", "computed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ceg_project_computed", table_name="correlated_event_group")
    op.drop_index("ix_ceg_computed_at", table_name="correlated_event_group")
    op.drop_index("ix_ceg_project_id", table_name="correlated_event_group")
    op.drop_table("correlated_event_group")
