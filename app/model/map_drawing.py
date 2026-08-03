"""地图手动绘制域模型（系统管理·⑧ 地图维护 - 手动标注）。

用于人工补录/纠偏地图上未及时刷新的道路或地点：
- 画点(kind=point)：自由画点(free) / 坐标画点(coord)
- 画线(kind=line)：自由画线(free) / 沿路画线(road)

geometry 统一存 JSON 文本：`[[lng, lat], ...]`（GCJ-02，与前端地图一致）。
- point：数组长度为 1
- line：数组长度 >= 2

数据范围：与地图资源库一致，按 map:* 权限管控，可选关联项目。
"""

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, SoftDeleteMixin, TimestampMixin


class MapDrawing(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "map_drawing"

    name: Mapped[str] = mapped_column(String(128), comment="标注名称（点名称/线名称）")
    kind: Mapped[str] = mapped_column(String(16), comment="标注类型: point/line")
    mode: Mapped[str] = mapped_column(String(16), comment="绘制模式: free/coord/road")
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联项目(可选)",
    )
    geometry: Mapped[str] = mapped_column(Text, comment="坐标串 JSON: [[lng,lat],...] (GCJ-02)")
    center_lng: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="定位经度（点=自身/线=首点）"
    )
    center_lat: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="定位纬度（点=自身/线=首点）"
    )
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True, comment="线长度(米)")
    color: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="展示颜色")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="标注人")
