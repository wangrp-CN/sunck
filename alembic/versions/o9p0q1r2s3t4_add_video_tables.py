"""新增视频通道/AI 事件表 video_channel / video_event（P3·⑧ 视频AI PoC）

视频通道登记台账 + 外部推理服务回推的 AI 事件留痕(可选联动 alarm_id)。
重推理不在平台落地。数据范围经 project 关联(VIA_PROJECT)。

Revision Id: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-07-24 10:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "o9p0q1r2s3t4"
down_revision: Union[str, None] = "n8o9p0q1r2s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_channel",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("channel_no", sa.String(length=64), nullable=False),
        sa.Column("stream_url", sa.String(length=512), nullable=True),
        sa.Column("vendor", sa.String(length=64), nullable=True),
        sa.Column("location_desc", sa.String(length=255), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="在线"),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint("channel_no", name="uq_video_channel_no"),
        sa.Index("ix_video_channel_project_id", "project_id"),
        sa.Index("ix_video_channel_is_deleted", "is_deleted"),
    )
    op.create_table(
        "video_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("video_channel.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("snapshot_url", sa.String(length=512), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("handled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "alarm_id",
            sa.Integer(),
            sa.ForeignKey("alarm.id", ondelete="SET NULL"),
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
        sa.Index("ix_video_event_channel_id", "channel_id"),
        sa.Index("ix_video_event_project_id", "project_id"),
        sa.Index("ix_video_event_event_type", "event_type"),
        sa.Index("ix_video_event_event_time", "event_time"),
        sa.Index("ix_video_event_alarm_id", "alarm_id"),
    )


def downgrade() -> None:
    op.drop_table("video_event")
    op.drop_table("video_channel")
