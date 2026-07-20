"""阶段1：实时定位/轨迹表 + 告警查询索引

Revision ID: 3a9f1c7e842
Revises: 1560808cdb62
Create Date: 2026-07-13 16:00:00.000000

为阶段1「实时链路闭环」新增高频时序表 device_location（设备上报坐标/状态），
并在 alarm 上补充 (project_id, alarm_time) 复合索引以支撑实时告警列表查询。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a9f1c7e842"
down_revision: Union[str, None] = "1560808cdb62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_location",
        sa.Column("device_type", sa.String(length=32), nullable=False, comment="设备类型"),
        sa.Column("device_no", sa.String(length=64), nullable=False, comment="设备编号"),
        sa.Column("device_name", sa.String(length=128), nullable=True, comment="设备名称(冗余)"),
        sa.Column("project_id", sa.Integer(), nullable=True, comment="归属项目"),
        sa.Column("longitude", sa.Float(), nullable=True, comment="经度(WGS-84)"),
        sa.Column("latitude", sa.Float(), nullable=True, comment="纬度(WGS-84)"),
        sa.Column("altitude", sa.Float(), nullable=True, comment="高程(米)"),
        sa.Column("accuracy", sa.Float(), nullable=True, comment="定位精度(米)"),
        sa.Column("speed", sa.Float(), nullable=True, comment="速度(米/秒)"),
        sa.Column("bearing", sa.Float(), nullable=True, comment="方位角(度)"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="设备状态"),
        sa.Column(
            "report_time", sa.DateTime(timezone=True), nullable=True, comment="设备侧上报时间"
        ),
        sa.Column("raw_payload", sa.Text(), nullable=True, comment="原始报文(JSON)"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, comment="更新时间"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_device_location_project_id_project"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_location")),
    )
    op.create_index(
        op.f("ix_device_location_device_time"),
        "device_location",
        ["device_no", "report_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_location_project_time"),
        "device_location",
        ["project_id", "report_time"],
        unique=False,
    )
    # 告警列表查询索引（按项目+时间倒序）
    op.create_index(
        op.f("ix_alarm_project_time"),
        "alarm",
        ["project_id", "alarm_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_alarm_project_time"), table_name="alarm")
    op.drop_index(op.f("ix_device_location_project_time"), table_name="device_location")
    op.drop_index(op.f("ix_device_location_device_time"), table_name="device_location")
    op.drop_table("device_location")
