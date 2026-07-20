"""project 软删除 is_deleted 列

Revision ID: 15f5d6d28d7d
Revises: 3a9f1c7e842
Create Date: 2026-07-14 09:26:22.774464
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "15f5d6d28d7d"
down_revision: Union[str, None] = "3a9f1c7e842"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仅新增 project 表的软删除标记（与部门/用户保持一致）
    op.add_column(
        "project",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="是否软删除",
        ),
    )


def downgrade() -> None:
    op.drop_column("project", "is_deleted")
