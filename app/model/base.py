"""ORM 基类与通用混入。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一命名约定，保证迁移文件名稳定
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), comment="更新时间"
    )


class CreatorMixin:
    """创建人混入：用于『仅本人』数据范围过滤（data_scope=4）。"""

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="创建人ID(数据范围-仅本人)",
    )


class SoftDeleteMixin:
    """软删除混入：逻辑删除，避免物理删除导致关联数据悬空。

    业务表统一携带 is_deleted，读取时需显式追加 .where(Model.is_deleted.is_(False))。
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否软删除"
    )
