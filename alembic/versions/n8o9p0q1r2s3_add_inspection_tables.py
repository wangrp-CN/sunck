"""新增巡检/打卡表 inspection_task / inspection_record（P3·⑨ 履职闭环）

巡检任务(状态机 待巡检→巡检中→已完成/已取消) + 打卡记录(WGS-84 坐标，
结果=异常可转隐患 hazard_id 溯源)。数据范围经 project 关联(VIA_PROJECT)。

Revision Id: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-07-24 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n8o9p0q1r2s3"
down_revision: Union[str, None] = "m7n8o9p0q1r2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inspection_task",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "assignee_id",
            sa.Integer(),
            sa.ForeignKey("person.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="待巡检"),
        sa.Column("required_checkins", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_inspection_task_project_id", "project_id"),
        sa.Index("ix_inspection_task_assignee_id", "assignee_id"),
        sa.Index("ix_inspection_task_status", "status"),
        sa.Index("ix_inspection_task_is_deleted", "is_deleted"),
    )
    op.create_table(
        "inspection_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("inspection_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("checkin_by_name", sa.String(length=64), nullable=True),
        sa.Column("checkin_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False, server_default="正常"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "hazard_id",
            sa.Integer(),
            sa.ForeignKey("hazard.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_inspection_record_task_id", "task_id"),
        sa.Index("ix_inspection_record_project_id", "project_id"),
        sa.Index("ix_inspection_record_hazard_id", "hazard_id"),
    )


def downgrade() -> None:
    op.drop_table("inspection_record")
    op.drop_table("inspection_task")
