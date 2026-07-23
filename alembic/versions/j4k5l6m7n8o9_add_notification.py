"""新增通知中心表 notification

多渠道通知（站内信/短信/语音）的统一落库载体；站内信由前端铃铛读取，
短信/语音为预留渠道（落库留痕，待接入第三方网关）。

Revision Id: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-07-23 09:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=16), nullable=False, server_default="in_app"),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="alarm"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=512), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_notification_user_id", "user_id"),
        sa.Index("ix_notification_channel", "channel"),
        sa.Index("ix_notification_category", "category"),
        sa.Index("ix_notification_is_read", "is_read"),
    )


def downgrade() -> None:
    op.drop_table("notification")
