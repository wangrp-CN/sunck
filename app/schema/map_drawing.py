"""地图手动绘制 Schema：创建/更新/输出/分页。

坐标以 `points: [[lng, lat], ...]` 传输（GCJ-02），落库时序列化为 geometry JSON 文本。
时间字段统一以「北京时间墙钟」字符串对外。
"""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.core.clock import LOCAL_TZ


class MapDrawingBase(BaseModel):
    name: str = Field(..., description="标注名称（点名称/线名称）")
    kind: str = Field(..., description="标注类型: point/line")
    mode: str = Field(..., description="绘制模式: free/coord/road")
    project_id: int | None = Field(None, description="关联项目(可选)")
    color: str | None = Field(None, description="展示颜色")
    remark: str | None = Field(None, description="备注")
    operator: str | None = Field(None, description="标注人")


class MapDrawingCreate(MapDrawingBase):
    points: list[list[float]] = Field(..., description="坐标串 [[lng,lat],...]；点=1 个，线>=2 个")


class MapDrawingUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    mode: str | None = None
    project_id: int | None = None
    points: list[list[float]] | None = None
    color: str | None = None
    remark: str | None = None
    operator: str | None = None


class MapDrawingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    mode: str
    project_id: int | None = None
    geometry: str = ""
    points: list[list[float]] = Field(default_factory=list)
    center_lng: float | None = None
    center_lat: float | None = None
    length_m: float | None = None
    color: str | None = None
    remark: str | None = None
    operator: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _fill_points(self) -> "MapDrawingOut":
        if not self.points and self.geometry:
            try:
                raw = json.loads(self.geometry)
            except (TypeError, ValueError):
                raw = []
            if isinstance(raw, list):
                self.points = [
                    [float(p[0]), float(p[1])]
                    for p in raw
                    if isinstance(p, (list, tuple)) and len(p) >= 2
                ]
        return self

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class MapDrawingPage(BaseModel):
    total: int
    items: list[MapDrawingOut]
    page: int = 1
    size: int = 20
