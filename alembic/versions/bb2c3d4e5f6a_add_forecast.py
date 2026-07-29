"""add forecast (Phase 5 智能化预测 - 预测基座)

Revision ID: bb2c3d4e5f6a
Revises: aa1b2c3d4e5f
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb2c3d4e5f6a"
down_revision: str | None = "aa1b2c3d4e5f"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecast",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("metric", sa.String(length=32), nullable=False, server_default="risk_index"),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("last_value", sa.Float(), nullable=False),
        sa.Column("slope", sa.Float(), nullable=False),
        sa.Column("intercept", sa.Float(), nullable=False),
        sa.Column("forecast_value", sa.Float(), nullable=False),
        sa.Column("forecast_level", sa.String(length=8), nullable=True),
        sa.Column("forecast_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forecast_project", "forecast", ["project_id"])
    op.create_index(
        "ix_forecast_key",
        "forecast",
        ["scope_type", "ref_id", "metric", "horizon_days"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_key", table_name="forecast")
    op.drop_index("ix_forecast_project", table_name="forecast")
    op.drop_table("forecast")
