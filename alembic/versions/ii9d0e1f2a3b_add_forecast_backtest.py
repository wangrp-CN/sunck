"""add forecast_backtest (预测回测 / A/B 对照)

Revision ID: ii9d0e1f2a3b
Revises: hh8c9d0e1f2a
Create Date: 2026-07-31
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ii9d0e1f2a3b"
down_revision: str | None = "hh8c9d0e1f2a"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "forecast_backtest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_version", sa.String(length=16), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_value", sa.Float(), nullable=False),
        sa.Column("forecast_lower", sa.Float(), nullable=True),
        sa.Column("forecast_upper", sa.Float(), nullable=True),
        sa.Column("breach", sa.Boolean(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("hit", sa.Boolean(), nullable=True),
        sa.Column("lead_hours", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fb_model_anchor", "forecast_backtest", ["model_version", "anchor_at"], unique=False
    )
    op.create_index(
        "ix_fb_scope", "forecast_backtest", ["scope_type", "ref_id", "metric"], unique=False
    )
    op.create_index("ix_fb_project", "forecast_backtest", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fb_project", table_name="forecast_backtest")
    op.drop_index("ix_fb_scope", table_name="forecast_backtest")
    op.drop_index("ix_fb_model_anchor", table_name="forecast_backtest")
    op.drop_table("forecast_backtest")
