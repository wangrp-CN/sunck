"""实时定位/轨迹域模型：设备上报的时序位置数据。

对应需求 §3.1 接口 1（实时定位数据上传）以及大机/列车设备携带的坐标。
与三类设备「配置表」(locate_device 等) 不同，本表是高频写入的**时序数据**，
按 (device_no, report_time) 索引，支撑：实时打点、最新位置查询、轨迹回放（阶段4）。

分表/时序方案（阶段5）预留：当前单表 + 复合索引满足演示与中小规模；
后续可按 device_no 哈希或按月分区，不影响上层查询接口。
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DEVICE_TYPE_LOCATE
from app.model.base import Base, TimestampMixin
from app.model.project import Project


class DeviceLocation(Base, TimestampMixin):
    __tablename__ = "device_location"

    device_type: Mapped[str] = mapped_column(
        String(32),
        default=DEVICE_TYPE_LOCATE,
        comment="设备类型(locate/anti_intrusion/train_approach)",
    )
    device_no: Mapped[str] = mapped_column(String(64), comment="设备编号")
    device_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="设备名称(冗余便于展示)"
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True, comment="归属项目"
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    longitude: Mapped[float | None] = mapped_column(Float, nullable=True, comment="经度(WGS-84)")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, comment="纬度(WGS-84)")
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True, comment="高程(米)")
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True, comment="定位精度(米)")
    speed: Mapped[float | None] = mapped_column(Float, nullable=True, comment="速度(米/秒)")
    bearing: Mapped[float | None] = mapped_column(Float, nullable=True, comment="方位角(度)")

    status: Mapped[str] = mapped_column(
        String(16), default="在线", comment="设备状态(在线/离线/低电量)"
    )
    report_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="设备侧上报时间戳"
    )
    raw_payload: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="原始报文(JSON,用于追溯)"
    )

    __table_args__ = (
        Index(
            "ix_device_location_device_time",
            "device_no",
            "report_time",
        ),
        Index(
            "ix_device_location_project_time",
            "project_id",
            "report_time",
        ),
        # 支撑 latest_locations 的「按设备取最新一条」：DISTINCT ON (device_no)
        # ORDER BY device_no, id DESC 走该索引做索引扫描，避免对时序大表全表 GROUP BY。
        Index(
            "ix_device_location_device_id",
            "device_no",
            "id",
        ),
    )
