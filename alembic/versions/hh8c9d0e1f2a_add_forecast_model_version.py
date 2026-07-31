"""add forecast.model_version (预测模型升级 + A/B 对照)

Revision ID: hh8c9d0e1f2a
Revises: gg7b8c9d0e1f
Create Date: 2026-07-31
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "hh8c9d0e1f2a"
down_revision: str | None = "gg7b8c9d0e1f"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "forecast",
        sa.Column(
            "model_version",
            sa.String(length=16),
            nullable=False,
            server_default="ols_v1",
        ),
    )
    op.create_index("ix_forecast_model", "forecast", ["model_version"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_forecast_model", table_name="forecast")
    op.drop_column("forecast", "model_version")
