"""数据字典 / 枚举中心域模型（P3·⑦）。

提供可维护的枚举字典，替代散落在代码/前端的硬编码选项：
- DictType：字典类型（如 device_type / alarm_type / hazard_category）
  - system=True 为系统内置，仅可读、不可删改（保障平台核心枚举稳定）
- DictItem：字典项（label/value/排序/是否启用/扩展备注）

数据范围：字典为全局配置，不绑定项目/部门；按 dict:* 权限管控。
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, TimestampMixin


class DictType(Base, TimestampMixin):
    __tablename__ = "dict_type"

    code: Mapped[str] = mapped_column(String(64), unique=True, comment="类型编码(唯一)")
    name: Mapped[str] = mapped_column(String(64), comment="类型名称")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="说明")
    system: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否系统内置(内置不可删改)"
    )
    items: Mapped[list["DictItem"]] = relationship(
        "DictItem",
        lazy="selectin",
        back_populates="type",
        cascade="all, delete-orphan",
        order_by="DictItem.sort",
    )


class DictItem(Base, TimestampMixin):
    __tablename__ = "dict_item"

    type_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("dict_type.code", ondelete="CASCADE"),
        index=True,
        comment="所属字典类型编码",
    )
    type: Mapped["DictType"] = relationship("DictType", lazy="selectin", back_populates="items")
    label: Mapped[str] = mapped_column(String(128), comment="显示名称")
    value: Mapped[str] = mapped_column(String(128), comment="存储值")
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序(升序)")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
    ext: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="扩展字段(颜色/图标等)"
    )
