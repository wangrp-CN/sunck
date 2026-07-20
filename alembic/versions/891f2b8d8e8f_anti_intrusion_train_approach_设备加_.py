"""anti_intrusion/train_approach 设备加 device_type 列

Revision ID: 891f2b8d8e8f
Revises: bad8cfaec1e5
Create Date: 2026-07-14 09:57:02.355465
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "891f2b8d8e8f"
down_revision: Union[str, None] = "bad8cfaec1e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "anti_intrusion_device",
        sa.Column(
            "device_type", sa.String(length=32), nullable=True, comment="设备类型(anti_intrusion)"
        ),
    )
    op.add_column(
        "train_approach_device",
        sa.Column(
            "device_type", sa.String(length=32), nullable=True, comment="设备类型(train_approach)"
        ),
    )


def downgrade() -> None:
    op.drop_column("train_approach_device", "device_type")
    op.drop_column("anti_intrusion_device", "device_type")
