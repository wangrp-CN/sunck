"""add map_drawing (系统管理·地图手动绘制)

Revision ID: ll2c3d4e5f6a
Revises: kk1b2c3d4e5f
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ll2c3d4e5f6a"
down_revision: str | None = "kk1b2c3d4e5f"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "map_drawing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("geometry", sa.Text(), nullable=False),
        sa.Column("center_lng", sa.Float(), nullable=True),
        sa.Column("center_lat", sa.Float(), nullable=True),
        sa.Column("length_m", sa.Float(), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("operator", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_map_drawing_project_id", "map_drawing", ["project_id"], unique=False)
    op.create_index("ix_map_drawing_kind", "map_drawing", ["kind"], unique=False)
    op.create_index("ix_map_drawing_mode", "map_drawing", ["mode"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_map_drawing_mode", table_name="map_drawing")
    op.drop_index("ix_map_drawing_kind", table_name="map_drawing")
    op.drop_index("ix_map_drawing_project_id", table_name="map_drawing")
    op.drop_table("map_drawing")
