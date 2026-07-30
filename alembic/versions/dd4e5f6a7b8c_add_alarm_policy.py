"""add alarm_policy + alarm.escalated_at (🅱 M4 告警收敛/抑制/升级策略)

Revision ID: dd4e5f6a7b8c
Revises: cc3d4e5f6a7b
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd4e5f6a7b8c"
down_revision: str | None = "cc3d4e5f6a7b"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alarm_policy",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("alarm_type", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("suppress_window_seconds", sa.Integer(), nullable=True),
        sa.Column("silence_start", sa.String(length=5), nullable=True),
        sa.Column("silence_end", sa.String(length=5), nullable=True),
        sa.Column("escalate_after_minutes", sa.Integer(), nullable=True),
        sa.Column("escalate_to_level", sa.String(length=16), server_default="严重", nullable=False),
        sa.Column(
            "escalate_channels", sa.String(length=64), server_default="in_app", nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alarm_policy_project", "alarm_policy", ["project_id"])
    op.create_index(
        "ix_alarm_policy_match", "alarm_policy", ["project_id", "alarm_type", "enabled"]
    )
    # 告警升级留痕：升级时间（空=未升级），供升级任务幂等与前端展示
    op.add_column("alarm", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("alarm", "escalated_at")
    op.drop_index("ix_alarm_policy_match", table_name="alarm_policy")
    op.drop_index("ix_alarm_policy_project", table_name="alarm_policy")
    op.drop_table("alarm_policy")
