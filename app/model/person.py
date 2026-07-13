"""人员与大型机械管理域模型：对应需求 §2.8。"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, TimestampMixin
from app.model.project import Project


class Person(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "person"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    person_no: Mapped[str] = mapped_column(String(64), comment="人员工号")
    name: Mapped[str] = mapped_column(String(64), comment="姓名")
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="性别")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="电话")
    # 防护人员/施工人员/管理人员
    person_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="人员类型")
    icon: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="人员图标")
    # 绑定的定位设备编号（骨架预留）
    device_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="绑定设备编号")


class Machine(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "machine"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    machine_no: Mapped[str] = mapped_column(String(64), comment="大机编号")
    machine_type: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="大机类型")
    spec_model: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="规格及型号")
    description: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="大机设备说明"
    )
