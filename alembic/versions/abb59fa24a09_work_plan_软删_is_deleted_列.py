"""work_plan 软删 is_deleted 列

Revision ID: abb59fa24a09
Revises: 55e4e4862b28
Create Date: 2026-07-14 10:11:49.556805
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abb59fa24a09"
down_revision: Union[str, None] = "55e4e4862b28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_plan",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="是否软删除",
        ),
    )


def downgrade() -> None:
    op.drop_column("work_plan", "is_deleted")
