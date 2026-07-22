"""隐患治理闭环域模型：人工/巡检发现的安全隐患，经整改→复核→销号形成治理闭环。

与「告警(系统自动触发)」互补：告警是设备越界等自动产生；隐患是现场人员发现、
需指派整改责任人、限期整改、复核销号的人工治理流程。数据范围经 project 关联(VIA_PROJECT)。
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.person import Person
from app.model.project import Project


class Hazard(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "hazard"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    title: Mapped[str] = mapped_column(String(255), comment="隐患标题")
    # 等级：重大/较大/一般/低
    level: Mapped[str] = mapped_column(String(16), default="一般", comment="隐患等级")
    # 类别：施工安全/设备设施/环境/管理/其他
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="隐患类别")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="隐患描述")
    location_desc: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="位置描述"
    )
    # 坐标：入库/判定用 WGS-84（与设备一致），对外展示转 GCJ-02 由前端处理
    lng: Mapped[float | None] = mapped_column(Float, nullable=True, comment="经度(WGS-84)")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True, comment="纬度(WGS-84)")

    # 发现信息
    discovered_by_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="发现人"
    )
    discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发现时间(带时区)"
    )
    # 来源：人工/巡检/系统
    source: Mapped[str] = mapped_column(String(32), default="人工", comment="来源")

    # 状态机：待整改/整改中/待复核/已销号/已驳回
    status: Mapped[str] = mapped_column(
        String(16), default="待整改", index=True, comment="隐患状态"
    )

    # 整改责任人（关联人员）
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="整改责任人(人员ID)",
    )
    assignee: Mapped["Person"] = relationship("Person", lazy="selectin")
    # 整改期限
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, comment="整改期限(带时区)"
    )

    # 整改留痕
    rectify_note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="整改说明")
    rectify_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改提交时间(带时区)"
    )

    # 复核留痕
    verify_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="复核人")
    verify_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="复核时间(带时区)"
    )
    verify_note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="复核意见")

    # 销号时间（终态标记）
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="销号时间(带时区)"
    )
