"""设备管理域模型：三类设备，对应需求 §2.7。

- LocateDevice      人机定位设备
- AntiIntrusionDevice 大机防侵限设备
- TrainApproachDevice 列车接近报警设备
"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class LocateDevice(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "locate_device"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    name: Mapped[str] = mapped_column(String(128), comment="设备名称")
    device_no: Mapped[str] = mapped_column(String(64), unique=True, comment="设备编号")
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="设备类型")
    function: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="设备功能")
    sn: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="设备SN码")
    status: Mapped[str] = mapped_column(String(16), default="在线", comment="设备状态")


class AntiIntrusionDevice(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "anti_intrusion_device"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    name: Mapped[str] = mapped_column(String(128), comment="设备名称")
    device_no: Mapped[str] = mapped_column(String(64), unique=True, comment="设备编号")
    sn: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="设备SN码")
    device_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="设备类型(anti_intrusion)"
    )
    longitude: Mapped[float | None] = mapped_column(comment="经度")
    latitude: Mapped[float | None] = mapped_column(comment="纬度")
    status: Mapped[str] = mapped_column(String(16), default="在线", comment="设备状态")


class TrainApproachDevice(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "train_approach_device"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    name: Mapped[str] = mapped_column(String(128), comment="设备名称")
    device_no: Mapped[str] = mapped_column(String(64), unique=True, comment="设备编号")
    sn: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="设备SN码")
    device_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="设备类型(train_approach)"
    )
    direction: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="设备方位")
    longitude: Mapped[float | None] = mapped_column(comment="经度")
    latitude: Mapped[float | None] = mapped_column(comment="纬度")
    status: Mapped[str] = mapped_column(String(16), default="在线", comment="设备状态")
