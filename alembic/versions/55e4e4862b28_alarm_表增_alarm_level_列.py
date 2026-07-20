"""alarm 表增 alarm_level 列

Revision ID: 55e4e4862b28
Revises: 891f2b8d8e8f
Create Date: 2026-07-14 10:09:14.961511
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "55e4e4862b28"
down_revision: Union[str, None] = "891f2b8d8e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alarm",
        sa.Column(
            "alarm_level",
            sa.String(length=16),
            nullable=False,
            server_default="警告",
            comment="告警级别(严重/警告/提示)",
        ),
    )


def downgrade() -> None:
    op.drop_column("alarm", "alarm_level")
