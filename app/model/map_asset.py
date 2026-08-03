"""地图资源库域模型（系统管理·⑧ 地图维护）。

地图资源库集中管理可复用的地理底图/平面图资源：
- 站点平面图(station_plan)、平面图图片(plan_image)、卫星影像(satellite)、自定义底图(custom_basemap)
- 默认视图（中心经纬度 + 缩放级别）、覆盖区域(WKT)、平面图/底图图片 MinIO 链接
- 可选关联项目(project_id)，不强制绑定

数据范围：地图资源为全局配置，不绑定项目/部门；按 map:* 权限管控。
"""

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, SoftDeleteMixin, TimestampMixin


class MapAsset(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "map_asset"

    name: Mapped[str] = mapped_column(String(128), comment="资源名称")
    type: Mapped[str] = mapped_column(
        String(32),
        comment="资源类型: station_plan/plan_image/satellite/custom_basemap",
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联项目(可选)",
    )
    center_lng: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="默认视图中心经度"
    )
    center_lat: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="默认视图中心纬度"
    )
    zoom: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="默认视图缩放级别")
    coverage_wkt: Mapped[str | None] = mapped_column(Text, nullable=True, comment="覆盖区域(WKT)")
    image_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="平面图/底图图片 MinIO 链接"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="维护人")
