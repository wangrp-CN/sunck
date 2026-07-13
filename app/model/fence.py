"""电子围栏管理域模型：对应需求 §2.5（基于高德地图绘制多边形区域）。"""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, TimestampMixin
from app.model.project import Project


class ElectronicFence(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "electronic_fence"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    name: Mapped[str] = mapped_column(String(128), comment="围栏名称")
    # 围栏类型：人员/大机/列车 等（字典维护）
    fence_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="围栏类型")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    # 几何以 WKT 文本存储（如 POLYGON((...))），判定时使用 shapely/PostGIS
    geometry_wkt: Mapped[str | None] = mapped_column(Text, nullable=True, comment="围栏几何(WKT)")
