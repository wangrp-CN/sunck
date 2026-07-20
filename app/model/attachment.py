"""通用附件模型：将媒体文件关联到任意业务实体。

通过 (entity_type, entity_id) 关联，避免给每张表都加 media_urls 列：
- 作业计划(work_plan) 现场照片
- 设备(device) / 人员(person) / 机械(machine) 档案图
- 告警(alarm) 处置留痕（与既有 alarm.media_urls 互补，告警沿用 media_urls 字段）
- 围栏(fence) / 项目(project) 等均可扩展

媒体对象存于 MinIO（见 app/core/minio_client.py），本表仅存 key 与预览代理 URL。
"""

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import mapped_column

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin


class Attachment(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "attachment"

    entity_type = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="关联实体类型(work_plan/device/person/machine/alarm/...)",
    )
    entity_id = mapped_column(Integer, nullable=False, index=True, comment="关联实体ID")
    media_key = mapped_column(String(512), nullable=False, comment="MinIO 对象 key")
    url = mapped_column(String(1024), nullable=False, comment="预览代理 URL(/api/v1/media/{key})")
    filename = mapped_column(String(255), nullable=False, comment="原始文件名")
    content_type = mapped_column(
        String(128), nullable=False, default="application/octet-stream", comment="MIME 类型"
    )
    size = mapped_column(Integer, nullable=False, default=0, comment="字节大小")

    __table_args__ = (
        # 列表查询主路径：(entity_type, entity_id) 过滤 + 软删隔离
        Index("ix_attachment_entity", "entity_type", "entity_id", "is_deleted"),
    )
