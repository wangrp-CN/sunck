"""主数据表(设备/人员/机械/围栏)软删 is_deleted 列

Revision ID: bad8cfaec1e5
Revises: 15f5d6d28d7d
Create Date: 2026-07-14 09:37:15.673006
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bad8cfaec1e5"
down_revision: Union[str, None] = "15f5d6d28d7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 为主数据表统一追加软删除标记，与部门/用户/项目保持一致
    for table in (
        "anti_intrusion_device",
        "electronic_fence",
        "locate_device",
        "machine",
        "person",
        "train_approach_device",
    ):
        op.add_column(
            table,
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
                comment="是否软删除",
            ),
        )


def downgrade() -> None:
    for table in (
        "train_approach_device",
        "person",
        "machine",
        "locate_device",
        "electronic_fence",
        "anti_intrusion_device",
    ):
        op.drop_column(table, "is_deleted")
