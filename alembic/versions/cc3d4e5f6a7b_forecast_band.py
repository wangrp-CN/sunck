"""forecast 置信带字段 (Phase 5 智能化预测 M2)

Revision ID: cc3d4e5f6a7b
Revises: bb2c3d4e5f6a
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc3d4e5f6a7b"
down_revision: str | None = "bb2c3d4e5f6a"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("forecast", sa.Column("std_resid", sa.Float(), nullable=True))
    op.add_column("forecast", sa.Column("forecast_lower", sa.Float(), nullable=True))
    op.add_column("forecast", sa.Column("forecast_upper", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("forecast", "forecast_upper")
    op.drop_column("forecast", "forecast_lower")
    op.drop_column("forecast", "std_resid")
