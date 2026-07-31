"""add external_feature (预测特征工程：外部特征表)

Revision ID: jj0a1b2c3d4e
Revises: ii9d0e1f2a3b
Create Date: 2026-07-31
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "jj0a1b2c3d4e"
down_revision: str | None = "ii9d0e1f2a3b"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "external_feature",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("feature_date", sa.Date(), nullable=False),
        sa.Column("feature_name", sa.String(length=48), nullable=False),
        sa.Column("feature_value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="mock"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "feature_date", "feature_name", name="uq_ext_feat"),
    )
    op.create_index(
        "ix_ext_feat_project_date", "external_feature", ["project_id", "feature_date"], unique=False
    )
    op.create_index(
        "ix_ext_feat_date_name", "external_feature", ["feature_date", "feature_name"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_ext_feat_date_name", table_name="external_feature")
    op.drop_index("ix_ext_feat_project_date", table_name="external_feature")
    op.drop_table("external_feature")
