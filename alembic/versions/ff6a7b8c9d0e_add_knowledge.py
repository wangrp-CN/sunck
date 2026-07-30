"""add knowledge_article (🅱 知识库自动检索关联链接)

Revision ID: ff6a7b8c9d0e
Revises: ee5f6a7b8c9d
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff6a7b8c9d0e"
down_revision: str | None = "ee5f6a7b8c9d"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_article",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("tags", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_project", "knowledge_article", ["project_id"], unique=False)
    op.create_index("ix_knowledge_source", "knowledge_article", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_knowledge_source", table_name="knowledge_article")
    op.drop_index("ix_knowledge_project", table_name="knowledge_article")
    op.drop_table("knowledge_article")
