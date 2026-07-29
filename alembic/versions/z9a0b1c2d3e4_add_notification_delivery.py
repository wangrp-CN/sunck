"""add notification_delivery (P2① 短信/语音网关触达记录)

Revision ID: z9a0b1c2d3e4
Revises: w2x3y4z5a6b7
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z9a0b1c2d3e4"
down_revision: str | None = "w2x3y4z5a6b7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_delivery",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(length=16), nullable=False, index=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="mock"),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("biz_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("code", sa.String(length=32), nullable=True),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="sent", index=True
        ),
        sa.Column("raw", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_delivery_user_id", "notification_delivery", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_delivery_user_id", table_name="notification_delivery")
    op.drop_table("notification_delivery")
