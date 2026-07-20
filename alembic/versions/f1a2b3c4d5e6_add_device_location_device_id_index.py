"""为 device_location 增加 (device_no, id) 索引

支撑 location_service.latest_locations 的「按设备取最新一条」查询
（DISTINCT ON (device_no) ORDER BY device_no, id DESC），将对高频时序大表的
全表 GROUP BY 扫描降为索引扫描，复杂度与设备数成正比。

Revision ID: f1a2b3c4d5e6
Revises: e9f3b2c1a4d5
Create Date: 2026-07-20 09:30:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e9f3b2c1a4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_device_location_device_id",
        "device_location",
        ["device_no", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_device_location_device_id", table_name="device_location")
