"""作业计划绑定明细：人员↔定位设备配对、大机六要素、围栏逐条规则

对齐原型《新增作业计划》三步向导：
- work_plan_person  += device_no（该人员在本计划中佩戴的定位设备）
- work_plan_machine += guard_person_id / driver_person_id /
                       arm_device_no / body_device_no / voice_device_no
- work_plan_fence   += monitor_target / trigger_condition / time_range / dwell_time

全部可空，历史数据无需回填；WorkPlan.rule_json 保留为计划级聚合规则（规则引擎 v2 判定入口）。

Revision ID: mm3d4e5f6a7b
Revises: ll2c3d4e5f6a
Create Date: 2026-08-05
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "mm3d4e5f6a7b"
down_revision: str | None = "ll2c3d4e5f6a"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 人员绑定：配对定位设备
    op.add_column(
        "work_plan_person",
        sa.Column("device_no", sa.String(length=64), nullable=True, comment="人员定位设备编号"),
    )

    # 大机绑定：防护/驾驶人员 + 三类车载设备
    op.add_column(
        "work_plan_machine",
        sa.Column("guard_person_id", sa.Integer(), nullable=True, comment="防护人员"),
    )
    op.add_column(
        "work_plan_machine",
        sa.Column("driver_person_id", sa.Integer(), nullable=True, comment="驾驶人员"),
    )
    op.add_column(
        "work_plan_machine",
        sa.Column(
            "arm_device_no", sa.String(length=64), nullable=True, comment="大机前臂定位设备编号"
        ),
    )
    op.add_column(
        "work_plan_machine",
        sa.Column(
            "body_device_no", sa.String(length=64), nullable=True, comment="大机机身定位设备编号"
        ),
    )
    op.add_column(
        "work_plan_machine",
        sa.Column(
            "voice_device_no", sa.String(length=64), nullable=True, comment="车载语音设备编号"
        ),
    )
    op.create_foreign_key(
        "fk_work_plan_machine_guard_person",
        "work_plan_machine",
        "person",
        ["guard_person_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_work_plan_machine_driver_person",
        "work_plan_machine",
        "person",
        ["driver_person_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 围栏绑定：逐围栏规则四要素
    op.add_column(
        "work_plan_fence",
        sa.Column("monitor_target", sa.String(length=32), nullable=True, comment="监控目标"),
    )
    op.add_column(
        "work_plan_fence",
        sa.Column(
            "trigger_condition", sa.String(length=16), nullable=True, comment="触发条件(进入/离开)"
        ),
    )
    op.add_column(
        "work_plan_fence",
        sa.Column("time_range", sa.String(length=64), nullable=True, comment="生效时间范围"),
    )
    op.add_column(
        "work_plan_fence",
        sa.Column("dwell_time", sa.Integer(), nullable=True, comment="停留时间(秒)"),
    )


def downgrade() -> None:
    op.drop_column("work_plan_fence", "dwell_time")
    op.drop_column("work_plan_fence", "time_range")
    op.drop_column("work_plan_fence", "trigger_condition")
    op.drop_column("work_plan_fence", "monitor_target")

    op.drop_constraint(
        "fk_work_plan_machine_driver_person", "work_plan_machine", type_="foreignkey"
    )
    op.drop_constraint("fk_work_plan_machine_guard_person", "work_plan_machine", type_="foreignkey")
    op.drop_column("work_plan_machine", "voice_device_no")
    op.drop_column("work_plan_machine", "body_device_no")
    op.drop_column("work_plan_machine", "arm_device_no")
    op.drop_column("work_plan_machine", "driver_person_id")
    op.drop_column("work_plan_machine", "guard_person_id")

    op.drop_column("work_plan_person", "device_no")
