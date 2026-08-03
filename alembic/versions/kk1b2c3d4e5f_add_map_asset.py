"""add map_asset (系统管理·地图资源库)

Revision ID: kk1b2c3d4e5f
Revises: jj0a1b2c3d4e
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "kk1b2c3d4e5f"
down_revision: str | None = "jj0a1b2c3d4e"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "map_asset",
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
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("center_lng", sa.Float(), nullable=True),
        sa.Column("center_lat", sa.Float(), nullable=True),
        sa.Column("zoom", sa.Integer(), nullable=True),
        sa.Column("coverage_wkt", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("operator", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_map_asset_project_id", "map_asset", ["project_id"], unique=False)
    op.create_index("ix_map_asset_type", "map_asset", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_map_asset_type", table_name="map_asset")
    op.drop_index("ix_map_asset_project_id", table_name="map_asset")
    op.drop_table("map_asset")
