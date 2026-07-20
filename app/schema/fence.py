"""电子围栏管理相关 Schema（请求/响应模型）。

geometry_wkt 以 WKT 文本存储（如 POLYGON((...))），前端由高德地图绘制后回填。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FenceCreate(BaseModel):
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    name: str = Field(..., max_length=128, description="围栏名称")
    fence_type: str | None = Field(None, max_length=32, description="围栏类型(人员/大机/列车)")
    enabled: bool = Field(True, description="是否启用")
    geometry_wkt: str | None = Field(None, description="围栏几何(WKT文本)")


class FenceUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    name: str | None = Field(None, max_length=128, description="围栏名称")
    fence_type: str | None = Field(None, max_length=32, description="围栏类型")
    enabled: bool | None = Field(None, description="是否启用")
    geometry_wkt: str | None = Field(None, description="围栏几何(WKT文本)")


class FenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    name: str
    fence_type: str | None = None
    enabled: bool
    geometry_wkt: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None


class FencePage(BaseModel):
    items: list[FenceOut]
    total: int
    page: int
    size: int
