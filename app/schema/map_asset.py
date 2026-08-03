"""地图资源库 Schema：创建/更新/输出/分页。

地图资源为全局配置（不绑定项目/部门），时间字段统一以「北京时间墙钟」字符串对外。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class MapAssetBase(BaseModel):
    name: str = Field(..., description="资源名称")
    type: str = Field(..., description="资源类型")
    project_id: int | None = Field(None, description="关联项目(可选)")
    center_lng: float | None = Field(None, description="默认视图中心经度")
    center_lat: float | None = Field(None, description="默认视图中心纬度")
    zoom: int | None = Field(None, description="默认视图缩放级别")
    coverage_wkt: str | None = Field(None, description="覆盖区域(WKT)")
    image_url: str | None = Field(None, description="平面图/底图图片 MinIO 链接")
    remark: str | None = Field(None, description="备注")
    operator: str | None = Field(None, description="维护人")


class MapAssetCreate(MapAssetBase):
    pass


class MapAssetUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    project_id: int | None = None
    center_lng: float | None = None
    center_lat: float | None = None
    zoom: int | None = None
    coverage_wkt: str | None = None
    image_url: str | None = None
    remark: str | None = None
    operator: str | None = None


class MapAssetOut(MapAssetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class MapAssetPage(BaseModel):
    total: int
    items: list[MapAssetOut]
    page: int = 1
    size: int = 20
