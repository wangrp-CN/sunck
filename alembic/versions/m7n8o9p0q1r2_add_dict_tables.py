"""新增数据字典表 dict_type / dict_item（P3·⑦ 枚举中心）

dict_type.system=True 为系统内置类型（只读）；dict_item 经 type_code 级联。

Revision Id: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-07-24 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m7n8o9p0q1r2"
down_revision: Union[str, None] = "l6m7n8o9p0q1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dict_type",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_dict_type_code"),
    )
    op.create_table(
        "dict_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "type_code",
            sa.String(length=64),
            sa.ForeignKey("dict_type.code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("ext", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_dict_item_type_code", "type_code"),
    )


def downgrade() -> None:
    op.drop_table("dict_item")
    op.drop_table("dict_type")
