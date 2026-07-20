"""新增通用附件表 attachment

- 通过 (entity_type, entity_id) 关联任意业务实体（作业计划/设备/人员/机械/告警等）
- 媒体对象存 MinIO，本表仅存 key 与预览代理 URL

Revision ID: e3b2c1d4f5a6
Revises: d2a1b3c4e5f6
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b2c1d4f5a6"
down_revision: Union[str, Sequence[str], None] = "d2a1b3c4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, comment="更新时间"),
        sa.Column(
            "created_by",
            sa.Integer(),
            nullable=True,
            comment="创建人ID(数据范围-仅本人)",
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="是否软删除",
        ),
        sa.Column("entity_type", sa.String(length=32), nullable=False, comment="关联实体类型"),
        sa.Column("entity_id", sa.Integer(), nullable=False, comment="关联实体ID"),
        sa.Column("media_key", sa.String(length=512), nullable=False, comment="MinIO 对象 key"),
        sa.Column("url", sa.String(length=1024), nullable=False, comment="预览代理 URL"),
        sa.Column("filename", sa.String(length=255), nullable=False, comment="原始文件名"),
        sa.Column(
            "content_type",
            sa.String(length=128),
            nullable=False,
            server_default="application/octet-stream",
            comment="MIME 类型",
        ),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0", comment="字节大小"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachment_id", "attachment", ["id"])
    op.create_index("ix_attachment_entity_type", "attachment", ["entity_type"])
    op.create_index("ix_attachment_entity_id", "attachment", ["entity_id"])
    op.create_index("ix_attachment_created_by", "attachment", ["created_by"])
    op.create_index(
        "ix_attachment_entity", "attachment", ["entity_type", "entity_id", "is_deleted"]
    )


def downgrade() -> None:
    op.drop_index("ix_attachment_entity", table_name="attachment")
    op.drop_index("ix_attachment_created_by", table_name="attachment")
    op.drop_index("ix_attachment_entity_id", table_name="attachment")
    op.drop_index("ix_attachment_entity_type", table_name="attachment")
    op.drop_index("ix_attachment_id", table_name="attachment")
    op.drop_table("attachment")
