"""电子围栏表新增「围栏描述」字段。

对应原型《新增/编辑/查看电子围栏》中的「围栏描述」多行文本框（选填）。

Revision ID: pp5f6a7b8c9e
Revises: oo4e5f6a7b8d
Create Date: 2026-08-06
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "pp5f6a7b8c9e"
down_revision: str | None = "oo4e5f6a7b8d"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "electronic_fence",
        sa.Column("description", sa.Text(), nullable=True, comment="围栏描述"),
    )


def downgrade() -> None:
    op.drop_column("electronic_fence", "description")
