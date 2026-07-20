"""删除未使用的 dict_data 死模型表

Revision ID: e9f3b2c1a4d5
Revises: e3b2c1d4f5a6
Create Date: 2026-07-20 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f3b2c1a4d5"
down_revision: Union[str, None] = "e3b2c1d4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("dict_data")


def downgrade() -> None:
    op.create_table(
        "dict_data",
        sa.Column("dict_type", sa.String(length=64), nullable=False, comment="字典类型"),
        sa.Column("dict_label", sa.String(length=64), nullable=False, comment="显示名"),
        sa.Column("dict_value", sa.String(length=64), nullable=False, comment="存储值"),
        sa.Column("sort", sa.Integer(), nullable=False, comment="排序"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, comment="更新时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dict_data")),
    )
