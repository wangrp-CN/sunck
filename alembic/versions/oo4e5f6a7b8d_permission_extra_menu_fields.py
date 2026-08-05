"""Permission 表扩展菜单元数据字段。

为支持菜单管理的高级配置，在 permission 表中新增：
- redirect: 默认跳转地址
- is_hidden: 是否隐藏路由
- is_cache: 是否缓存路由(KeepAlive)
- is_affix: 是否聚合路由
- is_external: 是否外链(外部打开)

Revision ID: oo4e5f6a7b8d
Revises: nn4e5f6a7b8c
Create Date: 2026-08-05
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "oo4e5f6a7b8d"
down_revision: str | None = "nn4e5f6a7b8c"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "permission",
        sa.Column("redirect", sa.String(length=200), nullable=True, comment="默认跳转地址"),
    )
    op.add_column(
        "permission",
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="是否隐藏路由",
        ),
    )
    op.add_column(
        "permission",
        sa.Column(
            "is_cache",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="是否缓存路由(KeepAlive)",
        ),
    )
    op.add_column(
        "permission",
        sa.Column(
            "is_affix",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="是否聚合路由",
        ),
    )
    op.add_column(
        "permission",
        sa.Column(
            "is_external",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="是否外链(外部打开)",
        ),
    )


def downgrade() -> None:
    op.drop_column("permission", "is_external")
    op.drop_column("permission", "is_affix")
    op.drop_column("permission", "is_cache")
    op.drop_column("permission", "is_hidden")
    op.drop_column("permission", "redirect")
