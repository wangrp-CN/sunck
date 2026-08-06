"""电子围栏管理相关 Schema（请求/响应模型）。

geometry_wkt 以 WKT 文本存储（如 POLYGON((...))），前端由高德地图绘制后回填。
created_at 序列化为「北京时间墙钟」字符串（YYYY-MM-DD HH:mm:ss），与列表页
《电子围栏列表》的「创建时间」列展示格式对齐。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class FenceCreate(BaseModel):
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    name: str = Field(..., max_length=128, description="围栏名称")
    description: str | None = Field(None, description="围栏描述(选填)")
    fence_type: str | None = Field(
        None, max_length=32, description="围栏类型(普通防区/预警防区/报警防区)"
    )
    enabled: bool = Field(True, description="是否启用")
    geometry_wkt: str | None = Field(None, description="围栏几何(WKT文本)")


class FenceUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    name: str | None = Field(None, max_length=128, description="围栏名称")
    description: str | None = Field(None, description="围栏描述")
    fence_type: str | None = Field(None, max_length=32, description="围栏类型")
    enabled: bool | None = Field(None, description="是否启用")
    geometry_wkt: str | None = Field(None, description="围栏几何(WKT文本)")


class FenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    # 冗余归属项目名称，列表页「项目名称」列直接展示，免去前端二次字典查询
    project_name: str | None = None
    name: str
    description: str | None = None
    fence_type: str | None = None
    enabled: bool
    geometry_wkt: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_created_at(self, v: datetime | None) -> str | None:
        """统一按北京时间输出 `YYYY-MM-DD HH:mm:ss`，前端直接落表格。"""
        if v is None:
            return None
        if v.tzinfo is None:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return v.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


class FencePage(BaseModel):
    items: list[FenceOut]
    total: int
    page: int
    size: int
